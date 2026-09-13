"""Minecraft / Loader 管理器"""

from __future__ import annotations

import re
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as ET
from packaging.version import Version

from src.models import ProgressEvent
from src.utils import (
    CancellationToken,
    HashUtils,
    HTTPClient,
    JavaUtils,
    OperationResult,
    RuntimePaths,
    atomic_write_json,
    delete_within,
    get_logger,
    list_bounded_directory,
    parse_version_safe,
    read_json,
    resolve_stable_directory,
    standardize_loader_type,
)

from .loader_adapters import (
    InstallerCommandContext,
    LoaderAdapter,
    LoaderInstallerArtifact,
    LoaderVersion,
    build_loader_adapters,
    resolve_installer_url,
)
from .loader_installer import run_installer_process

logger = get_logger().bind(component="LoaderManager")
_VERSION_FALLBACK = Version("0.0.0")


class LoaderManager:
    """五種 Minecraft server 載入器的單一管理入口"""

    _initialized: bool = False
    LOADER_CACHE_TTL_SECONDS: int = 12 * 60 * 60
    SECURE_CHECKSUM_SUFFIXES: tuple[tuple[str, str], ...] = (
        (".sha512", "sha512"),
        (".sha256", "sha256"),
        (".sha1", "sha1"),
    )
    _INSTALLER_METADATA_NAME = "installers.json"

    def __init__(self):
        if self._initialized:
            return

        cache_dir = resolve_stable_directory(RuntimePaths.get_cache_dir(), create=True)
        self.cache_dir = Path(cache_dir)
        self.version_cache_dir = Path(RuntimePaths.get_version_cache_dir())
        self.installer_cache_dir = Path(RuntimePaths.get_installer_cache_dir())
        self._version_cache: dict[str, list[LoaderVersion]] = {}
        self._preload_lock = threading.Lock()

        self._adapters = build_loader_adapters(self)
        self._prune_installer_cache()
        self._initialized = True

    # ------------------------------------------------------------------
    # 共用基礎：取消、快取、API、版本解析
    # ------------------------------------------------------------------

    @staticmethod
    def _is_cancel_requested(cancel_flag: dict | CancellationToken | Callable | None) -> bool:
        if not cancel_flag:
            return False
        if callable(cancel_flag):
            return bool(cancel_flag())
        is_cancelled = getattr(cancel_flag, "is_cancelled", None)
        if callable(is_cancelled):
            return bool(is_cancelled())
        if isinstance(cancel_flag, dict):
            return bool(cancel_flag.get("cancelled") or cancel_flag.get("cancel"))
        if hasattr(cancel_flag, "cancelled"):
            return bool(cancel_flag.cancelled)
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
                mc_part, _, suffix_part = version.partition("-")
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
        result: defaultdict[str, list[str]] = defaultdict(list)
        for version in versions:
            if "-" not in version:
                continue
            mc_version = version.partition("-")[0]
            parts = mc_version.split(".")
            if len(parts) == 4:
                mc_version = ".".join(parts[:3])
            result[mc_version].append(version)
        return dict(result)

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
        """統一預抓五種 server 類型；每個 internal adapter 擁有自己的解析器"""
        with self._preload_lock:
            if self._loader_cache_is_fresh():
                return
            for spec in self._adapters.values():
                try:
                    self._preload_loader(spec)
                except Exception as e:
                    logger.exception(f"預抓 {spec.id} 版本失敗: {e}")

    def _preload_loader(self, spec: LoaderAdapter):
        data: Any = spec.metadata_loader(spec) if spec.metadata_loader is not None else None
        if data:
            self._write_cache(self._cache_path(spec.id), data, spec.id)

    def _fetch_json_versions(self, spec: LoaderAdapter) -> list[dict]:
        if not spec.api_url:
            return []
        data = HTTPClient.fetch_json(spec.api_url, timeout=30)
        if not isinstance(data, list):
            return []
        return self._filter_loader_json(spec, data)

    def _fetch_maven_versions(self, spec: LoaderAdapter) -> dict[str, list[str]]:
        if not spec.api_url:
            return {}
        content = HTTPClient.fetch_bytes(spec.api_url, timeout=30)
        if not content:
            return {}
        data = self._build_loader_version_dict_from_metadata(content, allow_prerelease=not spec.stable_only)
        self._sort_version_dict(data, parse_fallback_full_version=spec.parse_fallback_full_version)
        return data

    def _fetch_minecraft_versions(self, spec: LoaderAdapter) -> list[dict]:
        manifest = HTTPClient.fetch_json(spec.api_url, timeout=30)
        if not isinstance(manifest, dict):
            manifest = {}
        versions = []
        cached = read_json(Path(self._cache_path(spec.id))) or []
        cache_map = {v["id"]: v for v in cached if isinstance(v, dict) and v.get("id")}

        entries_to_fetch = []
        for item in manifest.get("versions", []):
            if not isinstance(item, dict) or item.get("type") != "release":
                continue
            entry = {
                "id": item.get("id"),
                "type": item.get("type"),
                "url": item.get("url"),
                "time": item.get("time"),
                "releaseTime": item.get("releaseTime"),
                "complianceLevel": item.get("complianceLevel", 0),
                "server_url": None,
                "server_sha1": None,
            }
            old = cache_map.get(entry["id"])
            old_server = self._server_download_info_from_entry(old)
            if old and old.get("time") == entry["time"] and old_server is not None:
                entry["server_url"], entry["server_sha1"] = old_server
            else:
                entries_to_fetch.append(entry)
            versions.append(entry)

        if entries_to_fetch:

            def fetch_single_server_download(ent: dict) -> None:
                try:
                    detail = HTTPClient.fetch_json(ent["url"], timeout=10)
                    if not isinstance(detail, dict):
                        detail = {}
                    downloads = detail.get("downloads")
                    server = downloads.get("server", {}) if isinstance(downloads, dict) else {}
                    if not isinstance(server, dict):
                        server = {}
                    raw_url = server.get("url")
                    ent["server_url"] = raw_url.strip() if isinstance(raw_url, str) else ""
                    ent["server_sha1"] = self._normalize_server_sha1(server.get("sha1")) or ""
                except Exception as e:
                    ent["server_url"] = ""
                    ent["server_sha1"] = ""
                    logger.debug("查詢 Minecraft %s server URL 失敗: %s", ent["id"], type(e).__name__)

            with ThreadPoolExecutor(max_workers=8) as executor:
                for _ in executor.map(fetch_single_server_download, entries_to_fetch):
                    pass

        return versions

    def _filter_loader_json(self, spec: LoaderAdapter, data: list[dict]) -> list[dict]:
        items = [v for v in data if isinstance(v, dict)]
        return spec.filter_versions(items) if spec.filter_versions is not None else items

    @staticmethod
    def _sort_version_dict(
        version_dict: dict[str, list[str]], *, parse_fallback_full_version: bool = False
    ) -> dict[str, list[str]]:
        version_dict.update(
            {
                mc_version: sorted(
                    versions,
                    key=lambda full: (
                        parse_version_safe(full.partition("-")[2], fallback=_VERSION_FALLBACK)
                        if "-" in full
                        else (
                            parse_version_safe(full, fallback=_VERSION_FALLBACK)
                            if parse_fallback_full_version
                            else _VERSION_FALLBACK
                        ),
                        full,
                    ),
                    reverse=True,
                )
                for mc_version, versions in version_dict.items()
            }
        )
        return version_dict

    @staticmethod
    def _compatible_direct_versions(spec: LoaderAdapter, mc_version: str, cache: Any) -> list[LoaderVersion]:
        if not spec.direct_download:
            return []
        return (
            [LoaderVersion(version=mc_version)]
            if any(
                isinstance(version, dict)
                and version.get("id") == mc_version
                and LoaderManager._server_download_info_from_entry(version) is not None
                for version in cache
            )
            else []
        )

    @staticmethod
    def _compatible_json_versions(spec: LoaderAdapter, mc_version: str, cache: Any) -> list[LoaderVersion]:
        if not mc_version:
            return []
        versions = [
            LoaderVersion(version=str(version["version"]))
            for version in cache
            if isinstance(version, dict) and version.get("version")
        ]
        return versions[: spec.keep_latest] if spec.keep_latest else versions

    @staticmethod
    def _compatible_maven_versions(spec: LoaderAdapter, mc_version: str, cache: Any) -> list[LoaderVersion]:
        candidates = spec.candidate_keys(mc_version) if spec.candidate_keys else [mc_version]
        matched = next((key for key in candidates if isinstance(cache.get(key), list)), None)
        if not matched:
            return []
        versions = []
        for full in cache[matched]:
            if "-" not in str(full):
                continue
            loader_version = str(full).partition("-")[2]
            if spec.normalize_loader_version is not None:
                loader_version = spec.normalize_loader_version(matched, loader_version)
            versions.append(LoaderVersion(version=loader_version))
        return versions

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
        spec = self._adapters.get(loader_id)
        if not spec:
            return []
        if spec.compatibility_guard is not None and not spec.compatibility_guard(mc_version):
            return []
        cache_key = f"{loader_id}_{mc_version}"
        cache: Any
        if spec.direct_download:
            cache = self.get_versions()
        else:
            if cache_key in self._version_cache:
                return self._version_cache[cache_key]
            cache = read_json(Path(self._cache_path(loader_id)))
        if not cache:
            self._version_cache.pop(cache_key, None)
            return []
        if cache_key in self._version_cache:
            return self._version_cache[cache_key]
        try:
            if spec.compatible_version_loader is None:
                return []
            result = spec.compatible_version_loader(spec, mc_version, cache)
            if result:
                self._version_cache[cache_key] = result
            return result
        except Exception as e:
            logger.exception(f"讀取 {loader_id} 相容版本失敗: {e}")
            return []

    # ------------------------------------------------------------------
    # 版本 / 快取：Vanilla 也完全由 internal adapter 管理
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_server_sha1(value: Any) -> str:
        digest, _algorithm = HashUtils.normalize_expected_hash(str(value or ""), "sha1")
        return digest

    @classmethod
    def _server_download_info_from_entry(cls, entry: Any) -> tuple[str, str] | None:
        if not isinstance(entry, dict):
            return None
        url = entry.get("server_url")
        digest = cls._normalize_server_sha1(entry.get("server_sha1"))
        if not isinstance(url, str) or not url.strip() or not digest:
            return None
        return url.strip(), digest

    def get_versions(self, force_fetch: bool = False) -> list[dict]:
        """
        取得快取的 Minecraft 版本資訊，若快取不存在或過期則重新抓取

        Args:
            force_fetch: 是否強制重新抓取

        Returns:
            Minecraft 版本資訊列表
        """
        spec = self._adapters["vanilla"]
        cache_path = Path(self._cache_path(spec.id))
        try:
            versions = read_json(cache_path) or []
            cache_needs_refresh = not versions or any(
                self._server_download_info_from_entry(version) is None for version in versions
            )
            if force_fetch or not cache_path.exists() or cache_needs_refresh:
                self._preload_loader(spec)
                versions = read_json(cache_path) or []
            return [v for v in versions if self._server_download_info_from_entry(v) is not None]
        except Exception as e:
            logger.exception(f"取得 Minecraft 版本失敗: {e}")
            return []

    def _get_server_download_info(self, version_id: str) -> tuple[str, str] | None:
        target = next((v for v in self.get_versions(False) if v.get("id") == version_id), None)
        return self._server_download_info_from_entry(target)

    def _download_vanilla_server(
        self, minecraft_version: str, download_path: str, progress_callback=None, cancel_flag=None
    ) -> bool:
        """下載載入器安裝器所需的官方原版 server.jar"""
        download_info = self._get_server_download_info(minecraft_version)
        if download_info is None:
            self._fail(progress_callback, f"找不到具備完整性摘要的 {minecraft_version} Vanilla 伺服器檔案")
            return False
        url, expected_sha1 = download_info
        result = HTTPClient.download_file(
            url,
            download_path,
            progress_callback=(
                lambda done, total: (
                    progress_callback(ProgressEvent("vanilla_download", "正在下載原版伺服器檔案...", done, total))
                    if progress_callback
                    else None
                )
            ),
            cancel_check=lambda: self._is_cancel_requested(cancel_flag),
            expected_hash=expected_sha1,
            expected_hash_algorithm="sha1",
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
            progress_callback: 進度回呼函式
            cancel_flag: 取消標誌
            user_java_path: 使用者 Java 路徑

        Returns:
            下載結果
        """
        loader_id = standardize_loader_type(loader_type, loader_version)
        spec = self._adapters.get(loader_id)
        if not spec:
            return self._fail(progress_callback, f"不支援或無法識別的載入器類型: {loader_type}")
        if self._is_cancel_requested(cancel_flag):
            return False
        if spec.direct_download:
            download_info = self._get_server_download_info(minecraft_version)
            if download_info is None:
                return self._fail(progress_callback, f"找不到具備完整性摘要的 {minecraft_version} Vanilla 伺服器檔案")
            url, expected_sha1 = download_info
            result = HTTPClient.download_file(
                url=url,
                local_path=str(download_path),
                progress_callback=(
                    lambda done, total: (
                        progress_callback(ProgressEvent("server_download", "正在下載伺服器檔案...", done, total))
                        if progress_callback
                        else None
                    )
                ),
                cancel_check=lambda: self._is_cancel_requested(cancel_flag),
                expected_hash=expected_sha1,
                expected_hash_algorithm="sha1",
            )
            return True if result.success else self._fail(progress_callback, result.message)

        java_path = (
            user_java_path
            if user_java_path and Path(user_java_path).exists()
            else JavaUtils.get_best_java_path(minecraft_version)
        )
        if not java_path:
            return False
        installer_url = resolve_installer_url(spec, minecraft_version, loader_version)
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
        if artifact.url != installer_url or not HashUtils.is_valid_expected_hash(
            artifact.expected_hash, artifact.hash_algorithm
        ):
            return self._fail(progress_callback, f"{loader_id} installer 缺少可驗證的完整性摘要")
        base_dir = Path(download_path).parent
        installer_path = str(self.installer_cache_dir / f"{loader_id}-installer.jar")
        command_context = InstallerCommandContext(
            java_path=java_path,
            minecraft_version=minecraft_version,
            loader_version=loader_version,
            installer_path=installer_path,
        )
        args = spec.installer_args(command_context) if spec.installer_args else []
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
            post_install_result=spec.post_install_result,
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
        spec = self._adapters.get(loader_id)
        if spec is None:
            raise ValueError(f"不支援或無法識別的載入器類型: {loader_type}")
        if spec.direct_download:
            return None
        url = resolve_installer_url(spec, minecraft_version, loader_version)
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
                    if value and HashUtils.is_valid_expected_hash(value[0], algorithm):
                        logger.info(f"成功取得 {loader_id} 安裝器校驗碼 (演算法: {algorithm})")
                        return LoaderInstallerArtifact(
                            url,
                            value[0].lower(),
                            algorithm,
                            self._installer_version_from_url(url),
                        )
                except Exception as e:
                    logger.debug("讀取 %s 安裝器 %s 校驗碼失敗: %s", loader_id, algorithm, type(e).__name__)
        return LoaderInstallerArtifact(url, None, None, self._installer_version_from_url(url))

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
        post_install_result: Callable[[Path, str], str | None] | None = None,
        expected_hash: str | None = None,
        hash_algorithm: str | None = None,
    ) -> bool | str:
        if self._is_cancel_requested(cancel_flag):
            return False
        if not HashUtils.is_valid_expected_hash(expected_hash, hash_algorithm):
            return self._fail(progress_callback, "Loader installer 缺少可驗證的完整性摘要")

        base_dir = Path(download_path).parent
        installer_path = str(self.installer_cache_dir / f"{loader_type}-installer.jar")

        if need_vanilla:
            if progress_callback:
                progress_callback(ProgressEvent("vanilla_prepare", "正在準備原版伺服器檔案..."))
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
            progress_callback(ProgressEvent("installer_download", f"正在下載 {loader_type} 安裝器..."))

        download_result = HTTPClient.download_file(
            installer_url,
            installer_path,
            progress_callback=(
                lambda done, total: (
                    progress_callback(
                        ProgressEvent("installer_download", f"正在下載 {loader_type} 安裝器...", done, total)
                    )
                    if progress_callback
                    else None
                )
            ),
            cancel_check=lambda: self._is_cancel_requested(cancel_flag),
            expected_hash=expected_hash,
            expected_hash_algorithm=hash_algorithm,
        )
        if not download_result.success:
            return self._fail(
                progress_callback,
                download_result.message or f"下載 {loader_type} 安裝器失敗或被取消",
            )
        self._record_installer_cache(
            loader_type,
            installer_url,
            expected_hash or "",
            hash_algorithm or "",
        )

        if self._is_cancel_requested(cancel_flag):
            return False

        if progress_callback:
            progress_callback(
                ProgressEvent("installer", f"正在執行 {loader_type} 安裝程序（這可能需要幾分鐘）...", 0, 100)
            )

        return run_installer_process(
            installer_args=installer_args,
            base_dir=base_dir,
            loader_type=loader_type,
            progress_callback=progress_callback,
            cancel_check=lambda: self._is_cancel_requested(cancel_flag),
            fail_callback=lambda message: self._fail(progress_callback, message),
            post_install_result=post_install_result,
        )

    # ------------------------------------------------------------------
    # Cache / loader identity / 特殊差異
    # ------------------------------------------------------------------

    def _prune_installer_cache(self) -> None:
        """移除可明確識別的舊版安裝器與過期暫存檔"""
        now = time.time()
        known = set(self._adapters)
        try:
            for item in list_bounded_directory(self.installer_cache_dir, reject_reparse=False):
                name = item.name.casefold()
                if not item.is_file():
                    continue
                if name.endswith(".part") and now - item.stat().st_mtime > 24 * 60 * 60:
                    delete_within(self.installer_cache_dir, item)
                    continue
                match = re.fullmatch(r"([a-z]+)-installer-.+\.jar", name)
                if match and match.group(1) in known:
                    delete_within(self.installer_cache_dir, item)
        except OSError as e:
            logger.debug("清理舊版安裝器快取失敗: %s", e)

    @staticmethod
    def _installer_version_from_url(url: str) -> str:
        match = re.search(r"(?:installer-|/)(\d+(?:\.\d+)+(?:[-+][^/]+)?)\.jar$", url)
        return match.group(1) if match else ""

    def _record_installer_cache(self, loader_type: str, url: str, expected_hash: str, algorithm: str) -> None:
        metadata_path = self.installer_cache_dir / self._INSTALLER_METADATA_NAME
        existing = read_json(metadata_path, default={})
        metadata = existing if isinstance(existing, dict) else {}
        metadata[loader_type] = {
            "version": self._installer_version_from_url(url),
            "url": url,
            "hash": expected_hash,
            "algorithm": algorithm,
        }
        if not atomic_write_json(metadata_path, metadata, skip_if_unchanged=True):
            logger.warning("無法保存安裝器快取資訊")

    def clear_cache_file(self) -> OperationResult:
        """
        清除所有 Loader 快取檔案，包含版本快取與安裝器快取

        Returns:
            OperationResult: 清除快取的結果，包含成功與否的訊息
        """
        try:
            for spec in self._adapters.values():
                delete_within(self.cache_dir, Path(self._cache_path(spec.id)))
                delete_within(self.cache_dir, self.cache_dir / spec.cache_name)
                delete_within(self.cache_dir, self.version_cache_dir / spec.cache_name)

            if self.installer_cache_dir.exists():
                for jar in list_bounded_directory(self.installer_cache_dir):
                    if jar.is_file() and jar.suffix.lower() == ".jar":
                        delete_within(self.installer_cache_dir, jar)
            if self.cache_dir.exists():
                for jar in list_bounded_directory(self.cache_dir):
                    if jar.is_file() and jar.name.lower().endswith("-installer.jar"):
                        delete_within(self.cache_dir, jar)

            self._version_cache.clear()
            return OperationResult(True, "快取檔案已成功清除")
        except OSError as e:
            logger.exception(f"清除 Loader 快取檔案失敗: {e}")
            return OperationResult(False, f"清除 Loader 快取檔案失敗: {e}")

    def _cache_path(self, loader_id: str) -> str:
        cache_name = self._adapters[loader_id].cache_name
        if self.cache_dir != Path(RuntimePaths.get_cache_dir()):
            return str(self.cache_dir / cache_name)
        return str(self.version_cache_dir / cache_name)

    def _loader_cache_is_fresh(self) -> bool:
        if not all(Path(self._cache_path(loader_id)).exists() for loader_id in self._adapters):
            return False
        now = time.time()
        ttl = max(1, int(self.LOADER_CACHE_TTL_SECONDS))
        try:
            return all(now - Path(self._cache_path(loader_id)).stat().st_mtime <= ttl for loader_id in self._adapters)
        except OSError:
            return False

    def _quilt_installer_url(self) -> str:
        version = "0.15.1"
        return (
            "https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/"
            f"{version}/quilt-installer-{version}.jar"
        )

    def _fabric_installer_url(self) -> str:
        version = "1.1.2"
        return f"https://maven.fabricmc.net/net/fabricmc/fabric-installer/{version}/fabric-installer-{version}.jar"

    @staticmethod
    def _fail(progress_callback, message: str, debug: str = "") -> bool:
        if progress_callback:
            progress_callback(ProgressEvent("failed", message))
        if debug:
            logger.debug(debug)
        else:
            logger.warning(message)
        return False


__all__ = ["LoaderManager"]
