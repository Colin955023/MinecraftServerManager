"""Minecraft / Loader 管理器"""

from __future__ import annotations

import concurrent.futures
import re
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

import orjson
from defusedxml import ElementTree as ET
from packaging.version import Version

from src.models import LoaderInstallerArtifact, LoaderSpec, LoaderVersion, OperationResult
from src.utils import (
    CancellationToken,
    HTTPClient,
    JavaUtils,
    RuntimePaths,
    SubprocessUtils,
    SystemUtils,
    atomic_write_json,
    get_logger,
    is_fabric_compatible_version,
    parse_version_safe,
    read_json,
    standardize_loader_type,
)

logger = get_logger().bind(component="LoaderManager")


class LoaderManager:
    """五種 Minecraft server 載入器的單一管理入口"""

    _initialized: bool = False
    LOADER_CACHE_TTL_SECONDS: int = 12 * 60 * 60
    SECURE_CHECKSUM_SUFFIXES: tuple[tuple[str, str], ...] = (
        (".sha512", "sha512"),
        (".sha256", "sha256"),
        (".sha1", "sha1"),
    )

    def __init__(self):
        if self._initialized:
            return

        cache_dir = RuntimePaths.ensure_dir(RuntimePaths.get_cache_dir())
        self.cache_dir = Path(cache_dir)
        self.version_cache_dir = Path(RuntimePaths.get_version_cache_dir())
        self.installer_cache_dir = Path(RuntimePaths.get_installer_cache_dir())
        self._migrate_legacy_cache()

        self._version_cache: dict[str, list[LoaderVersion]] = {}
        self._preload_lock = threading.Lock()

        self.LOADER_SPECS: dict[str, LoaderSpec] = {
            "vanilla": LoaderSpec(
                id="vanilla",
                cache_name="mc_versions_cache.json",
                api_url="https://piston-meta.mojang.com/mc/game/version_manifest.json",
                api_kind="mojang_manifest",
                direct_download=True,
            ),
            "fabric": LoaderSpec(
                id="fabric",
                cache_name="fabric_versions_cache.json",
                api_url="https://meta.fabricmc.net/v2/versions/loader",
                api_kind="json",
                needs_vanilla=True,
                installer_url=lambda _mc, _loader: (
                    "https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.1.1/fabric-installer-1.1.1.jar"
                ),
                installer_args=lambda java, mc, loader, installer: [
                    java,
                    "-Dfile.encoding=UTF-8",
                    "-Dsun.stdout.encoding=UTF-8",
                    "-Dsun.stderr.encoding=UTF-8",
                    "-jar",
                    installer,
                    "server",
                    "-mcversion",
                    mc,
                    "-loader",
                    loader,
                    "-dir",
                    "{base_dir}",
                ],
            ),
            "quilt": LoaderSpec(
                id="quilt",
                cache_name="quilt_versions_cache.json",
                api_url="https://meta.quiltmc.org/v3/versions/loader",
                api_kind="json",
                keep_latest=1,
                needs_vanilla=True,
                installer_url=self._quilt_installer_url,
                installer_args=lambda java, mc, loader, installer: [
                    java,
                    "-Dfile.encoding=UTF-8",
                    "-Dsun.stdout.encoding=UTF-8",
                    "-Dsun.stderr.encoding=UTF-8",
                    "-jar",
                    installer,
                    "install",
                    "server",
                    mc,
                    loader,
                    "--install-dir={base_dir}",
                    "--download-server",
                ],
            ),
            "forge": LoaderSpec(
                id="forge",
                cache_name="forge_versions_cache.json",
                api_url="https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml",
                api_kind="maven_xml",
                installer_url=lambda mc, loader: (
                    f"https://maven.minecraftforge.net/net/minecraftforge/forge/{mc}-{loader}/forge-{mc}-{loader}-installer.jar"
                ),
                installer_args=lambda java, _mc, _loader, installer: [
                    java,
                    "-Dfile.encoding=UTF-8",
                    "-Dsun.stdout.encoding=UTF-8",
                    "-Dsun.stderr.encoding=UTF-8",
                    "-jar",
                    installer,
                    "--installServer",
                ],
            ),
            "neoforge": LoaderSpec(
                id="neoforge",
                cache_name="neoforge_versions_cache.json",
                api_url="https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml",
                api_kind="maven_xml",
                stable_only=False,
                parse_fallback_full_version=True,
                installer_url=lambda _mc, loader: (
                    f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{loader}/neoforge-{loader}-installer.jar"
                ),
                installer_args=lambda java, _mc, _loader, installer: [
                    java,
                    "-Dfile.encoding=UTF-8",
                    "-Dsun.stdout.encoding=UTF-8",
                    "-Dsun.stderr.encoding=UTF-8",
                    "-jar",
                    installer,
                    "--installServer",
                ],
                candidate_keys=self._build_neoforge_mc_version_candidates,
                normalize_loader_version=self._normalize_neoforge_loader_version,
            ),
        }
        for loader_id, spec in self.LOADER_SPECS.items():
            setattr(self, f"{loader_id}_cache_file", str(self.version_cache_dir / spec.cache_name))

        self._initialized = True

    # ------------------------------------------------------------------
    # 共用基礎：取消、快取、API、版本解析
    # ------------------------------------------------------------------

    @staticmethod
    def _is_cancel_requested(cancel_flag: dict | CancellationToken | Callable | None) -> bool:
        if not cancel_flag:
            return False
        try:
            if callable(cancel_flag):
                return bool(cancel_flag())
            if hasattr(cancel_flag, "is_cancelled") and callable(cancel_flag.is_cancelled):
                return bool(cancel_flag.is_cancelled())
            if isinstance(cancel_flag, dict):
                return bool(cancel_flag.get("cancelled") or cancel_flag.get("cancel"))
            if hasattr(cancel_flag, "cancelled"):
                return bool(cancel_flag.cancelled)
        except Exception:
            return False
        return False

    @staticmethod
    def _extract_xml_versions(content: bytes, stable_only: bool) -> list[str]:
        root = ET.fromstring(content)
        result = []
        for elem in root.findall(".//version"):
            value = (elem.text or "").strip()
            if not value:
                continue
            if stable_only and "-" in value:
                lower = value.lower()
                if any(k in lower for k in ("pre", "prelease", "beta", "alpha", "snapshot", "rc")):
                    continue
            result.append(value)
        return result

    @staticmethod
    def _normalize_version_strings(versions: list[str]) -> list[str]:
        """統一轉成 mc_version-loader_version"""
        result: list[str] = []

        for version in versions:
            if "-" in version:
                mc_part, suffix_part = version.split("-", 1)
                mc_clean = re.sub(r"[^0-9.]", "", mc_part).rstrip(".")
                suffix_clean = re.sub(r"[^0-9.]", "", suffix_part).rstrip(".")
                mc_parts = [p for p in mc_clean.split(".") if p]
                suffix_text = suffix_part.strip().rstrip(".")
                suffix_has_label = bool(re.search(r"[A-Za-z]", suffix_text))

                if mc_clean and mc_parts:
                    if mc_parts[0] == "1" and len(mc_parts) <= 3:
                        result.append(f"{mc_clean}-{suffix_text}")
                    elif len(mc_parts) > 3:
                        if mc_parts[0] == "1" and len(mc_parts) >= 6:
                            loader = ".".join(mc_parts[3:])
                            if suffix_text:
                                loader = f"{loader}-{suffix_text}"
                            result.append(f"{'.'.join(mc_parts[:3])}-{loader}")
                        elif mc_parts[0] in {"20", "21"} and len(mc_parts) >= 3:
                            loader = ".".join(mc_parts)
                            if suffix_text:
                                loader = f"{loader}-{suffix_text}"
                            result.append(f"1.{mc_parts[0]}.{mc_parts[1]}-{loader}")
                    elif mc_parts[0] in {"20", "21"} and suffix_has_label:
                        result.append(f"1.{mc_parts[0]}.{mc_parts[1]}-{mc_clean}-{suffix_text}")
                    else:
                        result.append(f"{mc_clean}-{suffix_text or suffix_clean}")
                elif mc_clean:
                    result.append(version)
                continue

            clean = re.sub(r"[^0-9.]", "", version).rstrip(".")
            if not clean:
                continue
            parts = clean.split(".")
            if len(parts) >= 6 and parts[0] == "1":
                result.append(f"{'.'.join(parts[:3])}-{'.'.join(parts[3:])}")
            elif len(parts) >= 3 and parts[0] == "47" and parts[1] == "1":
                result.append(f"1.20.1-{version}")
            elif len(parts) >= 2 and parts[0].isdigit() and int(parts[0]) >= 20:
                major = int(parts[0])
                minor = int(parts[1]) if parts[1].isdigit() else 0
                mc_str = f"1.{major}" if minor == 0 else f"1.{major}.{minor}"
                result.append(f"{mc_str}-{version}")
            elif len(parts) >= 3:
                result.append(f"{parts[0]}.{parts[1]}-{version}")
            elif len(parts) >= 2:
                result.append(clean)

        return result

    @staticmethod
    def _build_version_dict(versions: list[str]) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for version in versions:
            if "-" not in version:
                continue
            mc_version, _loader_version = version.split("-", 1)
            parts = mc_version.split(".")
            if len(parts) == 4:
                mc_version = ".".join(parts[:3])
            result.setdefault(mc_version, []).append(version)
        return result

    def _build_loader_version_dict_from_metadata(
        self, content: bytes, *, allow_prerelease: bool
    ) -> dict[str, list[str]]:
        versions = self._extract_xml_versions(content, stable_only=not allow_prerelease)
        return self._build_version_dict(self._normalize_version_strings(versions))

    def _write_cache(self, cache_file: str | Path, data: Any, label: str = "版本"):
        if not atomic_write_json(Path(cache_file), data):
            logger.warning(f"寫入 {label} 快取失敗: {cache_file}")
            return False
        return True

    # ------------------------------------------------------------------
    # 載入器：共用 API -> 篩選 -> 排序 -> 快取
    # ------------------------------------------------------------------

    def preload_loader_versions(self):
        """統一預抓五種 server 類型；API 差異由 LoaderSpec.api_kind 決定"""
        with self._preload_lock:
            if self._loader_cache_is_fresh():
                return
            for spec in self.LOADER_SPECS.values():
                try:
                    self._preload_loader(spec)
                except Exception as exc:
                    logger.exception(f"預抓 {spec.id} 版本失敗: {exc}")

    def _preload_loader(self, spec: LoaderSpec):
        data: Any = None
        if not spec.api_url:
            return
        if spec.api_kind == "mojang_manifest":
            data = self._fetch_minecraft_versions(spec)
        else:
            content = HTTPClient.fetch_bytes(spec.api_url, timeout=30)
            if not content:
                return
            if spec.api_kind == "json":
                data = self._filter_loader_json(spec, orjson.loads(content))
            elif spec.api_kind == "maven_xml":
                data = self._build_loader_version_dict_from_metadata(content, allow_prerelease=not spec.stable_only)
                self._sort_version_dict(data, parse_fallback_full_version=spec.parse_fallback_full_version)
            else:
                return
        if data:
            self._write_cache(self._cache_path(spec.id), data, spec.id)

    def _fetch_minecraft_versions(self, spec: LoaderSpec) -> list[dict]:
        manifest = orjson.loads(HTTPClient.fetch_bytes(spec.api_url, timeout=30) or b"{}")
        versions = []
        cached = read_json(Path(self._cache_path(spec.id))) or []
        cache_map = {v["id"]: v for v in cached if isinstance(v, dict) and v.get("id")}

        entries_to_fetch = []
        for item in manifest.get("versions", []):
            if item.get("type") != "release":
                continue
            entry = {
                "id": item.get("id"),
                "type": item.get("type"),
                "url": item.get("url"),
                "time": item.get("time"),
                "releaseTime": item.get("releaseTime"),
                "complianceLevel": item.get("complianceLevel", 0),
                "server_url": None,
            }
            old = cache_map.get(entry["id"])
            if old and old.get("time") == entry["time"] and old.get("server_url") is not None:
                entry["server_url"] = old["server_url"]
            else:
                entries_to_fetch.append(entry)
            versions.append(entry)

        if entries_to_fetch:

            def fetch_single_server_url(ent: dict) -> None:
                try:
                    detail = HTTPClient.fetch_json(ent["url"], timeout=10)
                    ent["server_url"] = detail.get("downloads", {}).get("server", {}).get("url", "") if detail else ""
                except Exception as exc:
                    ent["server_url"] = ""
                    logger.debug(f"查詢 Minecraft {ent['id']} server URL 失敗: {exc}")

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(fetch_single_server_url, entries_to_fetch))

        return versions

    def _filter_loader_json(self, spec: LoaderSpec, data: list[dict]) -> list[dict]:
        items = [v for v in data if isinstance(v, dict)]
        if spec.id == "fabric":
            return [v for v in items if v.get("stable", False)]
        if spec.id == "quilt":
            stable = [v for v in items if v.get("stable", False)]
            if not stable:
                keywords = ("pre", "prelease", "beta", "alpha", "snapshot", "rc")
                stable = [
                    v for v in items if v.get("version") and not any(k in str(v["version"]).lower() for k in keywords)
                ]
            stable.sort(
                key=lambda v: (
                    parse_version_safe(str(v.get("version", "")), fallback=Version("0.0.0")),
                    int(v.get("build", 0) or 0),
                ),
                reverse=True,
            )
            return stable[: spec.keep_latest] if spec.keep_latest else stable
        return items

    def _sort_version_dict(self, version_dict: dict[str, list[str]], *, parse_fallback_full_version: bool):
        for mc_version, versions in version_dict.items():
            versions.sort(
                key=lambda full: (
                    parse_version_safe(full.split("-", 1)[1], fallback=Version("0.0.0"))
                    if "-" in full
                    else (
                        parse_version_safe(full, fallback=Version("0.0.0"))
                        if parse_fallback_full_version
                        else Version("0.0.0")
                    ),
                    full,
                ),
                reverse=True,
            )
            version_dict[mc_version] = versions[:5]

    def get_compatible_loader_versions(self, mc_version: str, loader_type: str) -> list[LoaderVersion]:
        """
        取得指定 Minecraft 版本的相容載入器版本列表

        Args:
            mc_version: 目標 Minecraft 版本
            loader_type: 載入器類型

        Returns:
            相容的載入器版本列表
        """
        loader_id = standardize_loader_type(loader_type)
        spec = self.LOADER_SPECS.get(loader_id)
        if not spec:
            return []
        if loader_id == "fabric" and not is_fabric_compatible_version(mc_version):
            return []
        cache_key = f"{loader_id}_{mc_version}"
        if cache_key in self._version_cache:
            return self._version_cache[cache_key]
        cache = read_json(Path(self._cache_path(loader_id)))
        if not cache:
            return []
        try:
            if spec.direct_download:
                result = (
                    [LoaderVersion(version=mc_version)]
                    if any(
                        v.get("id") == mc_version and bool(v.get("server_url")) for v in cache if isinstance(v, dict)
                    )
                    else []
                )
            elif spec.api_kind == "json":
                result = [
                    LoaderVersion(version=str(v["version"])) for v in cache if isinstance(v, dict) and v.get("version")
                ]
            else:
                candidates = spec.candidate_keys(mc_version) if spec.candidate_keys else [mc_version]
                matched = next((key for key in candidates if isinstance(cache.get(key), list)), None)
                if not matched:
                    return []
                normalize = spec.normalize_loader_version or (lambda _key, value: value)
                result = [
                    LoaderVersion(version=normalize(matched, str(full).split("-", 1)[1]))
                    for full in cache[matched]
                    if "-" in str(full)
                ]
            if result:
                self._version_cache[cache_key] = result
            return result
        except Exception as exc:
            logger.exception(f"讀取 {loader_id} 相容版本失敗: {exc}")
            return []

    # ------------------------------------------------------------------
    # 版本 / 快取：Vanilla 也完全由 LoaderSpec 管理
    # ------------------------------------------------------------------

    def get_versions(self, force_fetch: bool = False) -> list[dict]:
        """
        取得快取的 Minecraft 版本資訊，若快取不存在或過期則重新抓取

        Args:
            force_fetch: 是否強制重新抓取

        Returns:
            Minecraft 版本資訊列表
        """
        spec = self.LOADER_SPECS["vanilla"]
        try:
            if force_fetch or not Path(self._cache_path(spec.id)).exists():
                self._preload_loader(spec)
            versions = read_json(Path(self._cache_path(spec.id))) or []
            return [v for v in versions if isinstance(v, dict) and bool(v.get("server_url"))]
        except Exception as exc:
            logger.exception(f"取得 Minecraft 版本失敗: {exc}")
            return []

    def get_server_download_url(self, version_id: str) -> str | None:
        target = next((v for v in self.get_versions(False) if v.get("id") == version_id), None)
        return target.get("server_url") if target else None

    def _download_vanilla_server(
        self, minecraft_version: str, download_path: str, progress_callback=None, cancel_flag=None
    ) -> bool:
        """下載載入器安裝器所需的官方原版 server.jar"""
        url = self.get_server_download_url(minecraft_version)
        if not url:
            self._fail(progress_callback, f"找不到 {minecraft_version} 的 Vanilla 伺服器下載位址")
            return False
        result = HTTPClient.download_file(
            url,
            download_path,
            progress_callback=progress_callback,
            cancel_check=lambda: self._is_cancel_requested(cancel_flag),
        )
        if not result.success:
            return self._fail(progress_callback, result.message)
        return True

    # ------------------------------------------------------------------
    # 下載 / installer：五種載入器共用同一條流程
    # ------------------------------------------------------------------

    def download_server_jar_with_progress(
        self,
        loader_type: str,
        minecraft_version: str,
        loader_version: str,
        download_path: str,
        progress_callback=None,
        cancel_flag: dict | CancellationToken | Callable | None = None,
        user_java_path: str | None = None,
        installer_artifact: LoaderInstallerArtifact | None = None,
    ) -> bool | str:
        """
        下載指定載入器的伺服器檔案，並在需要時執行安裝器

        Args:
            loader_type: 載入器類型
            minecraft_version: Minecraft 版本
            loader_version: 載入器版本
            download_path: 下載路徑
            progress_callback: 進度回調函數
            cancel_flag: 取消標誌
            user_java_path: 使用者 Java 路徑

        Returns:
            下載結果
        """
        loader_id = standardize_loader_type(loader_type, loader_version)
        spec = self.LOADER_SPECS.get(loader_id)
        if not spec:
            return self._fail(progress_callback, f"不支援或無法識別的載入器類型: {loader_type}")
        if self._is_cancel_requested(cancel_flag):
            return False
        if spec.direct_download:
            url = self.get_server_download_url(minecraft_version)
            if not url:
                return self._fail(progress_callback, f"找不到 {minecraft_version} 的 Vanilla 伺服器下載位址")
            result = HTTPClient.download_file(
                url=url,
                local_path=str(download_path),
                progress_callback=None,
                cancel_check=lambda: self._is_cancel_requested(cancel_flag),
            )
            return True if result.success else self._fail(progress_callback, result.message)

        java_path = (
            user_java_path
            if user_java_path and Path(user_java_path).exists()
            else JavaUtils.get_best_java_path(minecraft_version, ask_download=False)
        )
        if not java_path:
            return False
        installer_url = spec.installer_url(minecraft_version, loader_version) if spec.installer_url else None
        if not installer_url:
            return self._fail(progress_callback, f"找不到 {loader_id} 安裝器下載網址")
        if installer_artifact is not None and installer_artifact.url != installer_url:
            return self._fail(progress_callback, "Loader installer 建立計畫已失效")
        artifact = installer_artifact or self.resolve_installer_artifact(
            loader_type,
            minecraft_version,
            loader_version,
        )
        if artifact is None:
            return self._fail(progress_callback, f"找不到 {loader_id} 安裝器下載資訊")
        base_dir = Path(download_path).parent
        installer_path = str(self.installer_cache_dir / f"{loader_id}-installer.jar")
        args = (
            spec.installer_args(java_path, minecraft_version, loader_version, installer_path)
            if spec.installer_args
            else []
        )
        args = [arg.replace("{base_dir}", str(base_dir)).replace("{installer}", installer_path) for arg in args]
        return self._download_and_run_installer(
            installer_url=installer_url,
            installer_args=args,
            minecraft_version=minecraft_version,
            download_path=download_path,
            progress_callback=progress_callback,
            cancel_flag=cancel_flag,
            need_vanilla=spec.needs_vanilla,
            loader_type=loader_id,
            expected_hash=artifact.expected_hash,
            hash_algorithm=artifact.hash_algorithm,
        )

    def resolve_installer_artifact(
        self,
        loader_type: str,
        minecraft_version: str,
        loader_version: str,
    ) -> LoaderInstallerArtifact | None:
        """
        解析並固定一次建立流程使用的 installer URL 與 checksum

        Args:
            loader_type: 載入器類型
            minecraft_version: Minecraft 版本
            loader_version: 載入器版本

        Returns:
            需要安裝器時回傳下載資訊；直接下載型載入器回傳 None
        """
        loader_id = standardize_loader_type(loader_type, loader_version)
        spec = self.LOADER_SPECS.get(loader_id)
        if spec is None:
            raise ValueError(f"不支援或無法識別的載入器類型: {loader_type}")
        if spec.direct_download:
            return None
        url = spec.installer_url(minecraft_version, loader_version) if spec.installer_url else None
        if not url:
            raise ValueError(f"找不到 {loader_id} 安裝器下載網址")
        for suffix, algorithm in self.SECURE_CHECKSUM_SUFFIXES:
            urls_to_try = []
            if url.lower().endswith(".jar"):
                urls_to_try.append(url[:-4] + suffix)
            urls_to_try.append(url + suffix)

            for target_url in urls_to_try:
                try:
                    content = HTTPClient.fetch_bytes(target_url, timeout=5, log_errors=False)
                    if not content:
                        continue
                    value = content.decode("utf-8", errors="replace").strip().split()
                    if value:
                        logger.info(f"成功取得校驗碼 (網址: {target_url}, 演算法: {algorithm})")
                        return LoaderInstallerArtifact(url, value[0], algorithm)
                except Exception as exc:
                    logger.debug(f"讀取 installer {algorithm} checksum 失敗 ({target_url}): {exc}")
        return LoaderInstallerArtifact(url, None, None)

    def _download_and_run_installer(
        self,
        *,
        installer_url: str,
        installer_args: list[str],
        minecraft_version: str,
        download_path: str,
        progress_callback=None,
        cancel_flag=None,
        need_vanilla: bool = False,
        loader_type: str = "loader",
        expected_hash: str | None = None,
        hash_algorithm: str | None = None,
    ) -> bool | str:
        if self._is_cancel_requested(cancel_flag):
            return False

        base_dir = Path(download_path).parent
        installer_path = str(self.installer_cache_dir / f"{loader_type}-installer.jar")

        if need_vanilla:
            if progress_callback:
                progress_callback("正在準備原版伺服器檔案...")
            if not self._download_vanilla_server(
                minecraft_version,
                str(base_dir / "server.jar"),
                progress_callback,
                cancel_flag,
            ):
                return False

        if self._is_cancel_requested(cancel_flag):
            return False

        if progress_callback:
            progress_callback(f"正在下載 {loader_type} 安裝器...")

        download_result = HTTPClient.download_file(
            installer_url,
            installer_path,
            progress_callback=progress_callback,
            cancel_check=lambda: self._is_cancel_requested(cancel_flag),
            expected_hash=expected_hash,
            expected_hash_algorithm=hash_algorithm,
        )
        if not download_result.success:
            return self._fail(
                progress_callback,
                download_result.message or f"下載 {loader_type} 安裝器失敗或被取消",
            )

        if self._is_cancel_requested(cancel_flag):
            return False

        if progress_callback:
            progress_callback(f"正在執行 {loader_type} 安裝程序 (這可能需要幾分鐘)...")

        process = None
        try:
            process = SubprocessUtils.create_no_window_process(installer_args, cwd=str(base_dir))
            SystemUtils.register_managed_process(base_dir, process.pid)

            output_lines: list[str] = []
            error_lines: list[str] = []

            def _decode_stream_line(raw: bytes) -> str:
                if not raw:
                    return ""
                with suppress(UnicodeDecodeError):
                    return raw.decode("utf-8")
                import locale

                encodings_to_try = ("cp950", "big5", "gbk", "cp936", locale.getpreferredencoding(False))
                for enc in encodings_to_try:
                    if not enc:
                        continue
                    try:
                        return raw.decode(enc)
                    except UnicodeDecodeError, LookupError:
                        continue
                return raw.decode("utf-8", errors="replace")

            def read_stream(stream, sink: list[str], is_err: bool = False) -> None:
                try:
                    for line in iter(stream.readline, b""):
                        text = _decode_stream_line(line).strip()
                        if text:
                            sink.append(text)
                            if is_err:
                                logger.warning(f"[{loader_type} stderr] {text}")
                            else:
                                logger.info(f"[{loader_type}] {text}")
                                if progress_callback and not self._is_cancel_requested(cancel_flag):
                                    display_text = text if len(text) <= 80 else text[:77] + "..."
                                    progress_callback(f"正在執行 {loader_type} 安裝: {display_text}")
                except Exception as ex:
                    logger.debug(f"讀取安裝程序輸出例外: {ex}")
                finally:
                    with suppress(Exception):
                        stream.close()

            t_out = threading.Thread(target=read_stream, args=(process.stdout, output_lines, False), daemon=True)
            t_err = threading.Thread(target=read_stream, args=(process.stderr, error_lines, True), daemon=True)
            t_out.start()
            t_err.start()

            while process.poll() is None:
                if self._is_cancel_requested(cancel_flag):
                    process.cancelled = True
                    self._cleanup_installer_process(
                        process,
                        base_dir,
                    )
                    return False
                time.sleep(0.3)

            t_out.join(timeout=2.0)
            t_err.join(timeout=2.0)

            if process.returncode != 0:
                out_str = "\n".join(output_lines[-50:])
                err_str = "\n".join(error_lines[-50:])
                logger.error(
                    f"{loader_type} 安裝程序失敗 (代碼 {process.returncode})\nSTDOUT: {out_str}\nSTDERR: {err_str}"
                )
                self._cleanup_installer_process(
                    process,
                    base_dir,
                )
                return self._fail(
                    progress_callback,
                    f"{loader_type} 安裝程序執行失敗，請查看日誌了解詳情",
                )

            with suppress(Exception):
                SystemUtils.unregister_managed_process(base_dir, process.pid)

            if progress_callback:
                progress_callback("安裝成功，正在清理臨時檔案...")

            if loader_type in {"forge", "neoforge"}:
                run_bat = base_dir / "run.bat"
                if run_bat.exists():
                    return "run.bat"
                forge_jars = list(base_dir.glob(f"{loader_type}*.jar")) or list(base_dir.glob("*.jar"))
                for jar in forge_jars:
                    if loader_type in jar.name.lower() and "installer" not in jar.name.lower():
                        return jar.name
                if (base_dir / "win_args.txt").exists() or (base_dir / "user_jvm_args.txt").exists():
                    return "run.bat"
                return self._fail(
                    progress_callback,
                    f"{loader_type} 安裝完成但找不到啟動腳本 (run.bat)",
                )

            return True

        except Exception as exc:
            logger.exception(f"執行 {loader_type} 安裝器時發生錯誤: {exc}")
            self._cleanup_installer_process(
                process,
                base_dir,
            )
            return self._fail(
                progress_callback,
                f"執行 {loader_type} 安裝器時發生錯誤：{exc}",
            )

    def _cleanup_installer_process(
        self,
        process,
        base_dir: Path,
    ):
        if process is None:
            return

        pid = int(getattr(process, "pid", 0) or 0)
        try:
            if pid and (process.poll() is None or bool(getattr(process, "cancelled", False))):
                SystemUtils.kill_process_tree(pid)
        except Exception as exc:
            logger.warning(f"終止安裝器行程樹失敗: {exc}")

        try:
            SystemUtils.kill_java_processes_in_path(base_dir)
        except Exception as exc:
            logger.warning(f"清理安裝器 Java 行程失敗: {exc}")

        with suppress(Exception):
            SystemUtils.unregister_managed_process(base_dir, pid)

    # ------------------------------------------------------------------
    # Cache / loader identity / 特殊差異
    # ------------------------------------------------------------------

    def _migrate_legacy_cache(self) -> None:
        """將舊版扁平 Cache 目錄內的快取檔案自動遷移至子目錄"""
        try:
            if not self.cache_dir.exists():
                return
            for item in self.cache_dir.iterdir():
                if item.is_file():
                    if item.name.endswith("_cache.json") or item.name.endswith(".json"):
                        target = self.version_cache_dir / item.name
                        if not target.exists():
                            item.rename(target)
                        else:
                            item.unlink(missing_ok=True)
                    elif item.name.endswith("-installer.jar") or item.name.endswith(".jar"):
                        target = self.installer_cache_dir / item.name
                        if not target.exists():
                            item.rename(target)
                        else:
                            item.unlink(missing_ok=True)
        except Exception as exc:
            logger.debug(f"快取檔案遷移跳過或發生例外: {exc}")

    def clear_cache_file(self) -> OperationResult:
        """
        清除所有 Loader 快取檔案，包含版本快取與安裝器快取

        Returns:
            OperationResult: 清除快取的結果，包含成功與否的訊息
        """
        try:
            for spec in self.LOADER_SPECS.values():
                Path(self._cache_path(spec.id)).unlink(missing_ok=True)
                (self.cache_dir / spec.cache_name).unlink(missing_ok=True)
                (self.version_cache_dir / spec.cache_name).unlink(missing_ok=True)

            if self.installer_cache_dir.exists():
                for jar in self.installer_cache_dir.glob("*.jar"):
                    jar.unlink(missing_ok=True)
            if self.cache_dir.exists():
                for jar in self.cache_dir.glob("*-installer.jar"):
                    jar.unlink(missing_ok=True)

            self._version_cache.clear()
            return OperationResult(True, "快取檔案已成功清除")
        except (PermissionError, OSError) as exc:
            logger.exception(f"清除 Loader 快取檔案失敗: {exc}")
            return OperationResult(False, f"清除 Loader 快取檔案失敗: {exc}")

    def _cache_path(self, loader_id: str) -> str:
        cache_name = self.LOADER_SPECS[loader_id].cache_name
        if self.cache_dir != Path(RuntimePaths.get_cache_dir()):
            return str(self.cache_dir / cache_name)
        return str(self.version_cache_dir / cache_name)

    def _loader_cache_is_fresh(self) -> bool:
        if not all(Path(self._cache_path(loader_id)).exists() for loader_id in self.LOADER_SPECS):
            return False
        now = time.time()
        ttl = max(1, int(self.LOADER_CACHE_TTL_SECONDS))
        try:
            return all(
                now - Path(self._cache_path(loader_id)).stat().st_mtime <= ttl for loader_id in self.LOADER_SPECS
            )
        except OSError:
            return False

    @staticmethod
    def _build_neoforge_mc_version_candidates(mc_version: str) -> list[str]:
        normalized = str(mc_version or "").strip()
        if not normalized:
            return []

        candidates = [normalized]
        parts = normalized.split(".")

        if len(parts) >= 2:
            candidates.append(f"{parts[0]}.{parts[1]}")
        if len(parts) >= 3:
            candidates.append(".".join(parts[:3]))

        if normalized.startswith("1."):
            tail = normalized[2:]
            if tail:
                candidates.append(tail)
            tail_parts = tail.split(".") if tail else []
            if tail_parts and tail_parts[0].isdigit() and int(tail_parts[0]) >= 20:
                if len(tail_parts) == 1:
                    candidates.append(f"{tail_parts[0]}.0")
                else:
                    candidates.append(f"{tail_parts[0]}.{tail_parts[1]}")
                if len(tail_parts) >= 2:
                    candidates.append(f"{tail_parts[0]}.{tail_parts[1]}.0.0")
        elif len(parts) >= 2 and parts[0].isdigit() and int(parts[0]) >= 20:
            candidates.append(f"1.{parts[0]}.{parts[1]}")
            candidates.append(f"1.{normalized}")
            candidates.append(f"{parts[0]}.{parts[1]}.0.0")
            candidates.append(f"1.{parts[0]}")
        elif len(parts) >= 2 and all(p.isdigit() for p in parts[:2]):
            candidates.append(f"{parts[0]}.{parts[1]}.0.0")

        return list(dict.fromkeys(candidates))

    @staticmethod
    def _normalize_neoforge_loader_version(matched_key: str, loader_version: str) -> str:
        return loader_version if "." in loader_version else f"{matched_key}.{loader_version}"

    def _quilt_installer_url(self, _minecraft_version: str, _loader_version: str) -> str:
        version = self._get_latest_quilt_installer_version() or "0.12.1"
        return (
            "https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/"
            f"{version}/quilt-installer-{version}.jar"
        )

    def _get_latest_quilt_installer_version(self) -> str | None:
        url = "https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/maven-metadata.xml"
        try:
            content = HTTPClient.fetch_bytes(url, timeout=30)
            if not content:
                return None
            root = ET.fromstring(content)
            value = root.findtext(".//versioning/release") or root.findtext(".//versioning/latest")
            return value.strip() if value else None
        except Exception as exc:
            logger.exception(f"讀取 Quilt installer metadata 失敗: {exc}")
            return None

    @staticmethod
    def _fail(progress_callback, message: str, debug: str = "") -> bool:
        if progress_callback:
            progress_callback(message)
        if debug:
            logger.debug(debug)
        else:
            logger.warning(message)
        return False


__all__ = ["LoaderManager"]
