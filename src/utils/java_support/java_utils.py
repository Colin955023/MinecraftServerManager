"""
在 Windows 上偵測與管理 Java 安裝的工具函式
本模組提供從 Windows 常見安裝路徑與環境變數中尋找 Java 安裝的功能
"""

from __future__ import annotations

import os
import re
import shutil
import threading
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import ClassVar

from src.utils import (
    HTTPClient,
    JavaDownloader,
    RuntimePaths,
    SubprocessUtils,
    atomic_write_json,
    get_logger,
    read_json,
    serialize_json,
)

logger = get_logger().bind(component="JavaUtils")


class JavaUtils:
    """提供 Java 偵測、快取與安裝流程的工具集合"""

    COMMON_JAVA_PATHS: ClassVar[list[str]] = [
        "C:\\\\Program Files\\\\Java",
        "C:\\\\Program Files (x86)\\\\Java",
        "C:\\\\Program Files\\\\Microsoft",
    ]
    JAVA_EXECUTABLE_NAMES: ClassVar[frozenset[str]] = frozenset({"java", "java.exe", "javaw", "javaw.exe"})
    ENV_VARS: ClassVar[list[str]] = ["JAVA_HOME"]
    JAVA_CACHE_FILE_NAME: ClassVar[str] = "java_candidates_cache.json"
    _java_cache_lock: ClassVar[threading.Lock] = threading.Lock()
    _cached_java_candidates: ClassVar[list[tuple[str, int]] | None] = None

    @staticmethod
    def get_java_version(java_path: str) -> int | None:
        """
        取得指定 javaw.exe 的主要版本號

        Args:
            java_path: javaw.exe 的完整路徑

        Returns:
            Java major 版本，找不到或解析失敗時回傳 None
        """
        try:
            target_path = Path(java_path)
            exec_path = str(target_path)
            if target_path.name.lower() == "javaw.exe":
                console_exe = target_path.with_name("java.exe")
                if console_exe.exists():
                    exec_path = str(console_exe)
            elif target_path.name.lower() == "javaw":
                console_bin = target_path.with_name("java")
                if console_bin.exists():
                    exec_path = str(console_bin)

            res = SubprocessUtils.run_checked(
                [exec_path, "-version"],
                stdin=SubprocessUtils.DEVNULL,
                stdout=SubprocessUtils.PIPE,
                text=True,
                stderr=SubprocessUtils.STDOUT,
                check=True,
                timeout=5,
            )
            out = res.stdout or ""
            m = re.search('version "(\\d+)\\.(\\d+)', out)
            if m:
                major = int(m.group(1))
                if major == 1:
                    return int(m.group(2))
                return major
            m = re.search('version "(\\d+)"', out)
            if m:
                return int(m.group(1))
        except Exception as e:
            logger.exception(f"取得 Java 版本失敗 {java_path}: {e}")
        return None

    @staticmethod
    def _get_java_cache_path() -> Path:
        return RuntimePaths.get_version_cache_dir() / JavaUtils.JAVA_CACHE_FILE_NAME

    @staticmethod
    def _load_java_candidates_from_cache() -> list[tuple[str, int]] | None:
        cache_path = JavaUtils._get_java_cache_path()
        cache_data = read_json(cache_path)
        if not isinstance(cache_data, dict):
            return None
        candidates: list[tuple[str, int]] = []
        cached_items = cache_data.get("candidates", [])
        if not isinstance(cached_items, list):
            return None
        for item in cached_items:
            if not isinstance(item, dict):
                continue
            candidate_path = item.get("path")
            candidate_major = item.get("major")
            if not isinstance(candidate_path, str) or not isinstance(candidate_major, int):
                continue
            javaw_exe = Path(str(candidate_path))
            if not javaw_exe.is_file():
                continue
            try:
                candidates.append((str(javaw_exe.resolve()), candidate_major))
            except OSError:
                continue
        if not candidates:
            return None
        return candidates

    @staticmethod
    def _resolve_java_candidate(javaw_exe: Path) -> tuple[str, int] | None:
        major = JavaUtils.get_java_version(str(javaw_exe))
        if not major:
            return None
        try:
            resolved_javaw_exe = javaw_exe.resolve()
            return str(resolved_javaw_exe), major
        except OSError:
            return str(javaw_exe), major

    @staticmethod
    def _scan_and_cache_local_java_candidates() -> list[tuple[str, int]]:
        search_paths = set()
        for base_str in JavaUtils.COMMON_JAVA_PATHS:
            base = Path(base_str)
            if base.exists():
                for subdir in base.iterdir():
                    if subdir.is_dir():
                        search_paths.add(str(subdir / "bin"))
        for var in JavaUtils.ENV_VARS:
            val = os.environ.get(var)
            if val:
                for p in val.split(";"):
                    java_bin = Path(p) / "bin"
                    search_paths.add(str(java_bin))
        candidates: list[tuple[str, int]] = []
        candidate_paths: set[Path] = set()
        javaw_which = shutil.which("javaw")
        if javaw_which:
            candidate_paths.add(Path(javaw_which))
        for p_str in search_paths:
            search_path_obj = Path(p_str).resolve()
            javaw_exe = search_path_obj / "javaw.exe"
            if javaw_exe.exists():
                candidate_paths.add(javaw_exe)
        if not candidate_paths:
            return candidates
        for javaw_exe in sorted(candidate_paths):
            result = JavaUtils._resolve_java_candidate(javaw_exe)
            if result:
                candidates.append(result)
        candidates.sort(key=lambda x: (x[1], x[0]), reverse=True)
        final_results = []
        seen = set()
        for c_path, c_major in candidates:
            if (c_path, c_major) not in seen:
                seen.add((c_path, c_major))
                final_results.append((c_path, c_major))
        final_results.sort(key=lambda x: x[1])
        cache_path = JavaUtils._get_java_cache_path()
        if final_results:
            cached_items: list[dict[str, object]] = []
            for java_path_str, major in final_results:
                cached_items.append({"path": java_path_str, "major": major})
            atomic_write_json(cache_path, {"candidates": cached_items}, skip_if_unchanged=True)
        else:
            with suppress(OSError):
                if cache_path.exists():
                    cache_path.unlink()
        return final_results

    @staticmethod
    def refresh_java_candidates_cache() -> list[tuple[str, int]]:
        """
        重新掃描本機 Java 並更新 JSON 快取

        Returns:
            最新掃描到的 Java 候選清單
        """
        final_results = JavaUtils._scan_and_cache_local_java_candidates()
        with JavaUtils._java_cache_lock:
            JavaUtils._cached_java_candidates = list(final_results)
        return final_results

    @staticmethod
    def _ensure_cache_exists(cache_path: Path) -> None:
        """確保快取檔案存在且非空，若不存在則嘗試下載 Mojang version manifest"""
        legacy_path = RuntimePaths.get_cache_dir() / "mc_versions_cache.json"
        if legacy_path.exists() and legacy_path != cache_path:
            if not cache_path.exists() and legacy_path.stat().st_size > 0:
                with suppress(Exception):
                    legacy_path.rename(cache_path)
            else:
                with suppress(Exception):
                    legacy_path.unlink(missing_ok=True)
        if cache_path.exists() and cache_path.stat().st_size > 0:
            return
        manifest_url = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
        try:
            data = HTTPClient.fetch_json(manifest_url, timeout=10)
            if data and isinstance(data, dict) and "versions" in data:
                atomic_write_json(cache_path, data["versions"])
                return
        except Exception as e:
            logger.debug(f"無法自動下載 Mojang manifest: {e}")
        if not cache_path.exists() or cache_path.stat().st_size == 0:
            raise FileNotFoundError(f"找不到版本快取 {cache_path}")

    @staticmethod
    def get_required_java_major(mc_version: str) -> int:
        """
        根據 Minecraft 版本決定所需 Java major 版本

        Args:
            mc_version: Minecraft 版本字串

        Returns:
            對應的 Java major 版本
        """
        if not isinstance(mc_version, str) or not mc_version:
            raise ValueError("mc_version 必須為非空字串")
        cache_path = RuntimePaths.get_version_cache_dir() / "mc_versions_cache.json"
        JavaUtils._ensure_cache_exists(cache_path)
        data = read_json(cache_path)
        if data is None:
            raise ValueError(f"無法解析 {cache_path} 內容")
        if isinstance(data, dict):
            data = [data]
        for v in data:
            if v.get("id") == mc_version and "url" in v:
                url = v["url"]
                ver_json = HTTPClient.fetch_json(url, timeout=10)
                if ver_json:
                    java_info = ver_json.get("javaVersion")
                    if java_info and "majorVersion" in java_info:
                        return int(java_info["majorVersion"])
                    java_info2 = ver_json.get("java_version")
                    if java_info2 and "major" in java_info2:
                        return int(java_info2["major"])
                    json_str = serialize_json(ver_json)
                    m = re.search('"major(?:Version)?"\\s*:\\s*(\\d+)', json_str)
                    if m:
                        return int(m.group(1))
                raise ValueError(f"找不到 majorVersion，url: {url}")
        raise ValueError(f"找不到對應 mc_version: {mc_version}")

    @staticmethod
    def get_all_local_java_candidates() -> list:
        """
        取得所有可用的 javaw.exe 路徑及其主要版本號列表

        Returns:
            javaw.exe 路徑與 major 版本的配對清單
        """
        with JavaUtils._java_cache_lock:
            if JavaUtils._cached_java_candidates:
                return list(JavaUtils._cached_java_candidates)

        cached_candidates = JavaUtils._load_java_candidates_from_cache()
        if cached_candidates:
            with JavaUtils._java_cache_lock:
                JavaUtils._cached_java_candidates = list(cached_candidates)
            return cached_candidates

        final_results = JavaUtils._scan_and_cache_local_java_candidates()
        if final_results:
            with JavaUtils._java_cache_lock:
                JavaUtils._cached_java_candidates = list(final_results)
        return final_results

    @staticmethod
    def get_best_java_path(
        mc_version: str,
        required_major: int | None = None,
        ask_download: bool = True,
        *,
        confirm_download: Callable[[str, str], bool] | None = None,
        notify: Callable[[str, str, str], None] | None = None,
    ) -> str | None:
        """
        為指定 Minecraft 版本選擇最合適的 javaw.exe 路徑

        Args:
            mc_version: Minecraft 版本字串
            required_major: 指定的 Java major 版本；未提供時會自動推導
            ask_download: 找不到符合版本時是否詢問自動安裝
            confirm_download: 詢問是否自動安裝的回呼函式
            notify: 通知安裝進度或結果的回呼函式

        Returns:
            找到時回傳 javaw.exe 路徑，否則回傳 None
        """
        required_major = required_major if required_major else JavaUtils.get_required_java_major(mc_version)
        candidates = JavaUtils.get_all_local_java_candidates()
        for path, major in candidates:
            if major == required_major:
                return path
        if ask_download and confirm_download is not None:
            vendor = "Oracle jre" if required_major == 8 else "Microsoft JDK"
            title = "Java 未找到"
            prompt = (
                f"未找到合適的 Java {required_major}，是否由程式自動安裝 {vendor}？\n\n"
                "選擇 [是] 會在背景使用 winget 安裝並自動同意相關授權條款；\n"
                "選擇 [否] 則不會安裝，由你自行下載並在程式中指定 Java 路徑"
            )
            res = confirm_download(title, prompt)
            if res:
                try:
                    JavaDownloader.install_java_with_winget(required_major)
                    JavaUtils.refresh_java_candidates_cache()
                    candidates = JavaUtils.get_all_local_java_candidates()
                    for path, major in candidates:
                        if major == required_major:
                            if notify is not None:
                                notify(
                                    f"Java {required_major} 安裝成功",
                                    f"Java {required_major} 已成功安裝並偵測到 javaw.exe",
                                    "info",
                                )
                            return path
                except Exception as e:
                    logger.exception(f"自動下載 Microsoft JDK {required_major} 失敗：{e}")
                    if notify is not None:
                        notify(
                            "Java 下載失敗",
                            f"自動下載 Microsoft JDK {required_major} 失敗：{e}\n請手動安裝或指定 Java 路徑",
                            "error",
                        )
            elif notify is not None:
                notify(
                    "請手動下載 Java",
                    f"請手動安裝或指定 Java 路徑\n建議安裝 Microsoft JDK、Adoptium、Azul、Oracle JDK {required_major} 等",
                    "info",
                )
        return None


__all__ = ["JavaUtils"]
