"""Minecraft / Loader 管理器"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as ET
from packaging.version import Version

from ..models import LoaderVersion, OperationResult
from ..utils import (
    CancellationToken,
    ExceptionUtils,
    HTTPUtils,
    JavaUtils,
    PathUtils,
    RuntimePaths,
    ServerCommands,
    ServerDetectionVersionUtils,
    Singleton,
    SubprocessUtils,
    SystemUtils,
    atomic_write_json,
    get_logger,
    parse_version_safe,
)

logger = get_logger().bind(component="LoaderManager")


@dataclass(frozen=True, slots=True)
class LoaderSpec:
    """五種 server 類型的統一描述；差異資料化，共同流程留在 LoaderManager"""

    id: str
    cache_name: str
    api_url: str | None = None
    api_kind: str | None = None  # mojang_manifest / json / maven_xml
    stable_only: bool = True
    keep_latest: int | None = None
    installer_url: Callable[[str, str], str | None] | None = None
    installer_args: Callable[[str, str, str, str], list[str]] | None = None
    needs_vanilla: bool = False
    candidate_keys: Callable[[str], list[str]] | None = None
    normalize_loader_version: Callable[[str, str], str] | None = None
    parse_fallback_full_version: bool = False
    direct_download: bool = False


class LoaderManager(Singleton):
    """五種 Minecraft server 載入器的單一管理入口"""

    _initialized: bool = False
    LOADER_CACHE_TTL_SECONDS: int = 12 * 60 * 60
    SECURE_CHECKSUM_SUFFIXES: tuple[tuple[str, str], ...] = (("sha256", ".sha256"), ("sha512", ".sha512"))

    def __init__(self):
        if self._initialized:
            return

        cache_dir = RuntimePaths.ensure_dir(RuntimePaths.get_cache_dir())
        self.cache_dir = Path(cache_dir)
        self._version_cache: dict[str, list[LoaderVersion]] = {}
        self._preload_lock = threading.Lock()
        self._version_lock = threading.Lock()
        self._preloaded_once = False

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
            "forge": LoaderSpec(
                id="forge",
                cache_name="forge_versions_cache.json",
                api_url="https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml",
                api_kind="maven_xml",
                installer_url=lambda mc, loader: (
                    f"https://maven.minecraftforge.net/net/minecraftforge/forge/{mc}-{loader}/forge-{mc}-{loader}-installer.jar"
                ),
                installer_args=lambda java, _mc, _loader, installer: [java, "-jar", installer, "--installServer"],
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
                installer_args=lambda java, _mc, _loader, installer: [java, "-jar", installer, "--installServer"],
                candidate_keys=self._build_neoforge_mc_version_candidates,
                normalize_loader_version=self._normalize_neoforge_loader_version,
            ),
        }
        for loader_id, spec in self.LOADER_SPECS.items():
            setattr(self, f"{loader_id}_cache_file", str(self.cache_dir / spec.cache_name))

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

                if mc_clean and suffix_clean and mc_parts:
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
                        result.append(f"{mc_clean}-{suffix_clean}")
                elif mc_clean:
                    result.append(version)
                continue

            clean = re.sub(r"[^0-9.]", "", version).rstrip(".")
            if not clean:
                continue
            parts = clean.split(".")
            if len(parts) >= 6 and parts[0] == "1":
                result.append(f"{'.'.join(parts[:3])}-{'.'.join(parts[3:])}")
            elif len(parts) >= 3 and parts[0] in {"20", "21"}:
                result.append(f"1.{parts[0]}.{parts[1]}-{clean}")
            elif len(parts) >= 3:
                result.append(f"{parts[0]}.{parts[1]}-{parts[-1]}")
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

    def _record_cache_error(self, cache_file: str | Path, reason: str, details: dict | None = None):
        with suppress(Exception):
            ExceptionUtils.record_and_mark(
                RuntimeError(reason),
                Path(cache_file),
                reason=reason,
                details=details or {"cache_file": str(cache_file)},
            )

    def _write_cache(self, cache_file: str | Path, data: Any, label: str = "版本"):
        if not atomic_write_json(Path(cache_file), data):
            logger.warning(f"寫入 {label} 快取失敗: {cache_file}")
            return False
        return True

    def _read_json_cache(self, cache_file: str | Path):
        return PathUtils.load_json(Path(cache_file))

    # ------------------------------------------------------------------
    # 載入器：共用 API -> 篩選 -> 排序 -> 快取
    # ------------------------------------------------------------------

    def preload_loader_versions(self):
        """統一預抓五種 server 類型；API 差異由 LoaderSpec.api_kind 決定"""
        with self._preload_lock:
            if self._loader_cache_is_fresh():
                self._preloaded_once = True
                return
            for spec in self.LOADER_SPECS.values():
                try:
                    self._preload_loader(spec)
                except Exception as exc:
                    self._record_cache_error(
                        self._cache_path(spec.id), f"載入 {spec.id} 版本失敗", {"url": spec.api_url}
                    )
                    logger.exception(f"預抓 {spec.id} 版本失敗: {exc}")
            self._preloaded_once = True

    def _preload_loader(self, spec: LoaderSpec):
        data: Any = None
        if not spec.api_url:
            return
        if spec.api_kind == "mojang_manifest":
            data = self._fetch_minecraft_versions(spec)
        else:
            content = HTTPUtils.get_content(spec.api_url, timeout=15)
            if not content:
                return
            if spec.api_kind == "json":
                data = self._filter_loader_json(spec, self._decode_json(content))
            elif spec.api_kind == "maven_xml":
                data = self._build_loader_version_dict_from_metadata(content, allow_prerelease=not spec.stable_only)
                self._sort_version_dict(data, parse_fallback_full_version=spec.parse_fallback_full_version)
            else:
                return
        if data:
            self._write_cache(self._cache_path(spec.id), data, spec.id)

    @staticmethod
    def _decode_json(content: bytes) -> Any:
        import json

        return json.loads(content.decode("utf-8"))

    def _fetch_minecraft_versions(self, spec: LoaderSpec) -> list[dict]:
        manifest = self._decode_json(HTTPUtils.get_content(spec.api_url, timeout=15) or b"{}")
        versions = []
        cached = self._read_json_cache(self._cache_path(spec.id)) or []
        cache_map = {v["id"]: v for v in cached if isinstance(v, dict) and v.get("id")}
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
                try:
                    detail = HTTPUtils.get_json(entry["url"], timeout=10)
                    entry["server_url"] = detail.get("downloads", {}).get("server", {}).get("url", "") if detail else ""
                except Exception as exc:
                    entry["server_url"] = ""
                    logger.debug(f"查詢 Minecraft {entry['id']} server URL 失敗: {exc}")
            versions.append(entry)
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
            mc_version: 目标 Minecraft 版本
            loader_type: 載入器类型

        Returns:
            相容的載入器版本列表
        """
        loader_id = self._standardize_loader_id(loader_type)
        spec = self.LOADER_SPECS.get(loader_id)
        if not spec:
            return []
        if loader_id == "fabric" and not ServerDetectionVersionUtils.is_fabric_compatible_version(mc_version):
            return []
        cache_key = f"{loader_id}_{mc_version}"
        if cache_key in self._version_cache:
            return self._version_cache[cache_key]
        cache = self._read_json_cache(self._cache_path(loader_id))
        if not cache:
            return []
        try:
            if spec.direct_download:
                result = (
                    [LoaderVersion(version=mc_version)]
                    if any(
                        v.get("id") == mc_version and self._has_valid_server_url(v)
                        for v in cache
                        if isinstance(v, dict)
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
            self._record_cache_error(
                self._cache_path(loader_id), f"get_compatible_loader_versions_{loader_id}", {"mc_version": mc_version}
            )
            logger.exception(f"讀取 {loader_id} 相容版本失敗: {exc}")
            return []

    # ------------------------------------------------------------------
    # 版本 / 快取：Vanilla 也完全由 LoaderSpec 管理
    # ------------------------------------------------------------------

    @staticmethod
    def _has_valid_server_url(version: dict) -> bool:
        return bool(version.get("server_url"))

    def fetch_versions(self) -> list[dict]:
        """
        取得所有 Minecraft 版本資訊，並更新快取

        Returns:
            Minecraft 版本資訊列表
        """
        self._preload_loader(self.LOADER_SPECS["vanilla"])
        return self.get_versions(force_fetch=False)

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
            versions = self._read_json_cache(self._cache_path(spec.id)) or []
            return [v for v in versions if isinstance(v, dict) and self._has_valid_server_url(v)]
        except Exception as exc:
            self._record_cache_error(self._cache_path(spec.id), "get_versions failed", {"context": "get_versions"})
            logger.exception(f"取得 Minecraft 版本失敗: {exc}")
            return []

    def get_server_download_url(self, version_id: str) -> str | None:
        target = next((v for v in self.get_versions(False) if v.get("id") == version_id), None)
        return target.get("server_url") if target else None

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
        loader_id = self._standardize_loader_id(loader_type, loader_version)
        spec = self.LOADER_SPECS.get(loader_id)
        if not spec:
            return self._fail(progress_callback, f"不支援或無法識別的載入器類型: {loader_type}")
        if self._is_cancel_requested(cancel_flag):
            return False
        if spec.direct_download:
            url = self.get_server_download_url(minecraft_version)
            if not url:
                return self._fail(progress_callback, f"找不到 {minecraft_version} 的 Vanilla 伺服器下載位址")
            return HTTPUtils.download_file(
                url=url,
                local_path=str(download_path),
                progress_callback=None,
                cancel_check=lambda: self._is_cancel_requested(cancel_flag),
                failure_message_callback=progress_callback,
            )

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
        base_dir = Path(download_path).parent
        installer_path = str(self.cache_dir / f"{loader_id}-installer.jar")
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
        )

    def get_installer_download_url(self, loader_type: str, minecraft_version: str, loader_version: str) -> str | None:
        loader_id = self._standardize_loader_id(loader_type, loader_version)
        spec = self.LOADER_SPECS.get(loader_id)
        return spec.installer_url(minecraft_version, loader_version) if spec and spec.installer_url else None

    def _get_loader_installer_checksum(self, url: str) -> tuple[str | None, str | None]:
        for suffix, algorithm in self.SECURE_CHECKSUM_SUFFIXES:
            try:
                content = HTTPUtils.get_content(f"{url}{suffix}")
                if not content:
                    continue
                value = content.decode("utf-8", errors="replace").strip().split()
                if value:
                    return value[0], algorithm
            except Exception as exc:
                logger.debug(f"讀取 installer {algorithm} checksum 失敗: {exc}")
        return None, None

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
    ) -> bool | str:
        if self._is_cancel_requested(cancel_flag):
            return False

        base_dir = Path(download_path).parent
        installer_path = str(self.cache_dir / f"{loader_type}-installer.jar")

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

        expected_hash, hash_algo = self._get_loader_installer_checksum(installer_url)
        if not HTTPUtils.download_file_with_progress(
            installer_url,
            installer_path,
            progress_callback=progress_callback,
            cancel_flag=cancel_flag,
            expected_hash=expected_hash,
            hash_algo=hash_algo,
        ):
            return self._fail(
                progress_callback,
                f"下載 {loader_type} 安裝器失敗或被取消",
            )

        if self._is_cancel_requested(cancel_flag):
            return False

        if progress_callback:
            progress_callback(f"正在執行 {loader_type} 安裝程序 (這可能需要幾分鐘)...")

        process = None
        try:
            process = SubprocessUtils.create_no_window_process(installer_args, cwd=str(base_dir))
            SystemUtils.register_managed_process(base_dir, process.pid)

            while process.poll() is None:
                if self._is_cancel_requested(cancel_flag):
                    process.cancelled = True
                    self._cleanup_installer_process(
                        process,
                        base_dir,
                        installer_path,
                        f"使用者取消了 {loader_type} 安裝程序",
                    )
                    return False
                time.sleep(0.5)

            if process.returncode != 0:
                stdout, stderr = process.communicate()
                out_str = stdout.decode("utf-8", errors="replace") if stdout else ""
                err_str = stderr.decode("utf-8", errors="replace") if stderr else ""
                logger.error(
                    f"{loader_type} 安裝程序失敗 (代碼 {process.returncode})\nSTDOUT: {out_str}\nSTDERR: {err_str}"
                )
                self._cleanup_installer_process(
                    process,
                    base_dir,
                    installer_path,
                    f"{loader_type} 安裝失敗",
                    {"returncode": process.returncode, "stderr": err_str},
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
                ServerCommands.grant_execution_permission(str(base_dir))
                run_bat = base_dir / "run.bat"
                if run_bat.exists():
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
                installer_path,
                f"執行 {loader_type} 安裝程序發生例外",
                {"error": str(exc)},
            )
            return self._fail(
                progress_callback,
                f"執行 {loader_type} 安裝器時發生錯誤：{exc}",
            )

    def _cleanup_installer_process(
        self,
        process,
        base_dir: Path,
        installer_path: str,
        reason: str,
        details: dict | None = None,
    ):
        if process is None:
            return

        pid = int(getattr(process, "pid", 0) or 0)
        try:
            if pid and (process.poll() is None or bool(getattr(process, "cancelled", False))):
                SystemUtils.kill_process_tree(pid)
        except Exception as exc:
            logger.warning(f"終止安裝器進程樹失敗: {exc}")

        try:
            SystemUtils.kill_java_processes_in_path(base_dir)
        except Exception as exc:
            logger.warning(f"清理安裝器 Java 進程失敗: {exc}")

        with suppress(Exception):
            SystemUtils.unregister_managed_process(base_dir, pid)

        with suppress(Exception):
            ExceptionUtils.record_and_mark(
                RuntimeError(reason),
                Path(installer_path),
                reason=reason,
                details=details or {"installer": installer_path, "base_dir": str(base_dir)},
            )

    # ------------------------------------------------------------------
    # Cache / loader identity / 特殊差異
    # ------------------------------------------------------------------

    def clear_cache_file(self) -> OperationResult:
        """
        清除所有 Loader 快取檔案，包含版本快取與安裝器快取

        Returns:
            OperationResult: 清除快取的結果，包含成功與否的訊息
        """
        try:
            for spec in self.LOADER_SPECS.values():
                self._cache_path(spec.id)
                Path(self._cache_path(spec.id)).unlink(missing_ok=True)

            Path(self.version_cache_file).unlink(missing_ok=True)
            self._version_cache.clear()
            self._preloaded_once = False
            return OperationResult(True, "快取檔案已成功清除")
        except (PermissionError, OSError) as exc:
            logger.exception(f"清除 Loader 快取檔案失敗: {exc}")
            return OperationResult(False, f"清除 Loader 快取檔案失敗: {exc}")

    def _cache_path(self, loader_id: str) -> str:
        return str(self.cache_dir / self.LOADER_SPECS[loader_id].cache_name)

    def _loader_cache_files_exist(self) -> bool:
        return all(Path(self._cache_path(loader_id)).exists() for loader_id in self.LOADER_SPECS)

    def _loader_cache_is_fresh(self) -> bool:
        if not self._loader_cache_files_exist():
            return False
        now = time.time()
        ttl = max(1, int(self.LOADER_CACHE_TTL_SECONDS))
        try:
            return all(
                now - Path(self._cache_path(loader_id)).stat().st_mtime <= ttl for loader_id in self.LOADER_SPECS
            )
        except OSError:
            return False

    def _standardize_loader_id(self, loader_type: str, loader_version: str = "") -> str:
        return ServerDetectionVersionUtils.standardize_loader_type(loader_type, loader_version)

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
            if tail_parts and tail_parts[0] in {"20", "21"}:
                if len(tail_parts) == 1:
                    candidates.append(f"{tail_parts[0]}.0")
                else:
                    candidates.append(f"{tail_parts[0]}.{tail_parts[1]}")
                if len(tail_parts) >= 2:
                    candidates.append(f"{tail_parts[0]}.{tail_parts[1]}.0.0")
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
            content = HTTPUtils.get_content(url, timeout=15)
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
