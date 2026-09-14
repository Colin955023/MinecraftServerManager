"""
在 Windows 上偵測與管理 Java 安裝的工具函式
本模組提供從 Windows 常見安裝路徑與環境變數中尋找 Java 安裝的功能
"""

from __future__ import annotations

import os
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from functools import lru_cache
from operator import itemgetter
from pathlib import Path
from typing import Any, ClassVar

from src.utils import (
    VERSION_ZERO,
    HTTPClient,
    RuntimePaths,
    SubprocessUtils,
    atomic_write_json,
    delete_within,
    get_logger,
    list_bounded_directory,
    parse_version_safe,
    read_json,
)

logger = get_logger().bind(component="JavaUtils")

_MC_VERSION_PATTERN = re.compile(
    r"^(?:\d+\.\d+(?:\.\d+)*|\d{2}w\d{2}[a-z]|\d+\.\d+(?:\.\d+)*-(?:pre|rc|snapshot)\d*)$",
    re.IGNORECASE,
)


class JavaUtils:
    """提供 Java 偵測、快取與安裝流程的工具集合"""

    COMMON_JAVA_PATHS: ClassVar[list[str]] = [
        str(Path(base) / subdirectory)
        for env_var, subdirectory in (
            ("ProgramFiles", "Java"),
            ("ProgramFiles(x86)", "Java"),
            ("ProgramFiles", "Microsoft"),
            ("ProgramW6432", "Microsoft"),
        )
        for base in (os.environ.get(env_var),)
        if base
    ]
    JAVA_EXECUTABLE_NAMES: ClassVar[frozenset[str]] = frozenset({"java", "java.exe", "javaw", "javaw.exe"})
    ENV_VARS: ClassVar[list[str]] = ["JAVA_HOME"]
    JAVA_CACHE_FILE_NAME: ClassVar[str] = "java_candidates_cache.json"
    JAVA_REQUIREMENTS_CACHE_FILE_NAME: ClassVar[str] = "mc_java_requirements_cache.json"
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
                try:
                    subdirectories = list_bounded_directory(base)
                except OSError:
                    continue
                for subdir in subdirectories:
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
        candidates.sort(key=itemgetter(1, 0), reverse=True)
        final_results = list(dict.fromkeys(candidates))
        final_results.sort(key=itemgetter(1))
        cache_path = JavaUtils._get_java_cache_path()
        if final_results:
            cached_items = [{"path": java_path_str, "major": major} for java_path_str, major in final_results]
            atomic_write_json(cache_path, {"candidates": cached_items}, skip_if_unchanged=True)
        else:
            with suppress(OSError):
                if cache_path.exists():
                    delete_within(cache_path.parent, cache_path)
        return final_results

    @staticmethod
    def refresh_java_candidates_cache() -> list[tuple[str, int]]:
        """
        重新掃描本地 Java 並更新 JSON 快取

        Returns:
            最新掃描到的 Java 候選清單
        """
        final_results = JavaUtils._scan_and_cache_local_java_candidates()
        with JavaUtils._java_cache_lock:
            JavaUtils._cached_java_candidates = list(final_results)
        return final_results

    @staticmethod
    def validate_java_candidates() -> list[tuple[str, int]]:
        """
        快速驗證快取的 Java 候選項目仍可執行並更新快取

        Returns:
            通過執行驗證的 Java 路徑與主要版本清單
        """
        verified_candidates: list[tuple[str, int]] = []
        for java_path, _major in JavaUtils.get_all_local_java_candidates():
            result = JavaUtils._resolve_java_candidate(Path(java_path))
            if result:
                verified_candidates.append(result)

        verified_candidates = list(dict.fromkeys(verified_candidates))
        verified_candidates.sort(key=itemgetter(1, 0))
        cache_path = JavaUtils._get_java_cache_path()
        if verified_candidates:
            cached_items = [{"path": path, "major": major} for path, major in verified_candidates]
            atomic_write_json(cache_path, {"candidates": cached_items}, skip_if_unchanged=True)
        else:
            with suppress(OSError):
                if cache_path.exists():
                    delete_within(cache_path.parent, cache_path)
        with JavaUtils._java_cache_lock:
            JavaUtils._cached_java_candidates = list(verified_candidates)
        return verified_candidates

    @staticmethod
    def _ensure_cache_exists(cache_path: Path) -> None:
        """確保快取檔案存在且非空，若不存在則嘗試下載 Mojang version manifest"""
        if cache_path.exists() and cache_path.stat().st_size > 0:
            return
        manifest_url = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
        try:
            data = HTTPClient.fetch_json(manifest_url, timeout=10)
            if data and isinstance(data, dict) and "versions" in data:
                atomic_write_json(cache_path, data["versions"])
                return
        except Exception as e:
            logger.debug("無法自動下載 Mojang manifest: %s", e)
        if not cache_path.exists() or cache_path.stat().st_size == 0:
            raise FileNotFoundError(f"找不到版本快取 {cache_path}")

    @staticmethod
    def _sort_requirements(requirements: dict[str, int]) -> dict[str, int]:
        """
        按照 Minecraft 版本由新到舊排序

        Args:
            requirements: 版本字串與 Java major 版本的映射字典

        Returns:
            由新到舊排序後的字典
        """
        sorted_keys = sorted(
            requirements.keys(),
            key=lambda v: (parse_version_safe(v, fallback=VERSION_ZERO), v),
            reverse=True,
        )
        return {k: requirements[k] for k in sorted_keys}

    @staticmethod
    def _is_valid_mc_version(mc_version: str, allowed_versions: set[str] | None = None) -> bool:
        if not isinstance(mc_version, str) or not mc_version.strip():
            return False
        cleaned = mc_version.strip()
        if allowed_versions:
            return cleaned in allowed_versions
        return bool(_MC_VERSION_PATTERN.match(cleaned))

    @staticmethod
    def _clean_requirements_cache(
        raw_data: Any,
        allowed_versions: set[str] | None = None,
    ) -> dict[str, int]:
        """
        過濾並清理 Java major 需求快取，只保留合法的 Minecraft 版本及其對應的 Java major 版本

        Args:
            raw_data: 原始快取字典或資料
            allowed_versions: 允許的合法 Minecraft 版本集合（選填）

        Returns:
            由新到舊排序的乾淨快取字典
        """
        if not isinstance(raw_data, dict):
            return {}
        cleaned: dict[str, int] = {}
        for k, v in raw_data.items():
            if isinstance(k, str) and JavaUtils._is_valid_mc_version(k, allowed_versions) and type(v) is int and v > 0:
                cleaned[k.strip()] = v
        return JavaUtils._sort_requirements(cleaned)

    @staticmethod
    def _load_requirements_cache(
        requirements_path: Path,
        allowed_versions: set[str] | None = None,
    ) -> dict[str, int]:
        """
        讀取 Java major 需求快取，若含有多餘或不合格項目則自動剔除並回寫磁碟

        Args:
            requirements_path: 快取檔案路徑
            allowed_versions: 允許的合法 Minecraft 版本集合（選填）

        Returns:
            清洗後且由新到舊排序的字典
        """
        raw_data = read_json(requirements_path)
        cleaned = JavaUtils._clean_requirements_cache(raw_data, allowed_versions)
        if isinstance(raw_data, dict) and (
            len(raw_data) != len(cleaned) or any(raw_data.get(k) != v for k, v in cleaned.items())
        ):
            atomic_write_json(requirements_path, cleaned)
        return cleaned

    @staticmethod
    def _fetch_version_java_major_from_url(url: str) -> int | None:
        """
        從指定 Minecraft 版本的 package JSON URL 解析其 Java major 版本

        Args:
            url: 版本 manifest 的 JSON 連結

        Returns:
            Java major 版本，解析失敗則回傳 None
        """
        try:
            ver_json = HTTPClient.fetch_json(url, timeout=10)
            if not ver_json or not isinstance(ver_json, dict):
                return None
            java_info = ver_json.get("javaVersion")
            if isinstance(java_info, dict) and "majorVersion" in java_info:
                with suppress(ValueError, TypeError):
                    return int(java_info["majorVersion"])
            java_info2 = ver_json.get("java_version")
            if isinstance(java_info2, dict) and "major" in java_info2:
                with suppress(ValueError, TypeError):
                    return int(java_info2["major"])
        except Exception as e:
            logger.debug("抓取版本 JSON 失敗: %s", e)
        return None

    @staticmethod
    def preload_all_java_requirements(force: bool = False) -> dict[str, int]:
        """
        初次啟動或快取缺失時平行抓取全版本之 Java major 版本並寫入快取

        Args:
            force: 是否強制重新抓取全版本，預設為 False

        Returns:
            由新到舊排序的 Java major 版本映射字典
        """
        requirements_path = RuntimePaths.get_version_cache_dir() / JavaUtils.JAVA_REQUIREMENTS_CACHE_FILE_NAME
        cache_path = RuntimePaths.get_version_cache_dir() / "mc_versions_cache.json"
        JavaUtils._ensure_cache_exists(cache_path)
        versions_data = read_json(cache_path)
        if isinstance(versions_data, dict):
            versions_data = [versions_data]
        elif not isinstance(versions_data, list):
            versions_data = []

        candidates = [
            v
            for v in versions_data
            if isinstance(v, dict)
            and v.get("id")
            and v.get("url")
            and (v.get("type") == "release" or not v.get("type"))
        ]
        if not candidates:
            candidates = [v for v in versions_data if isinstance(v, dict) and v.get("id") and v.get("url")]

        known_versions = {str(c["id"]) for c in candidates if isinstance(c, dict) and c.get("id")}
        cached_requirements = JavaUtils._load_requirements_cache(
            requirements_path,
            allowed_versions=known_versions if known_versions else None,
        )
        if not force and cached_requirements and all(c["id"] in cached_requirements for c in candidates):
            return cached_requirements

        results: dict[str, int] = dict(cached_requirements)
        to_fetch = [c for c in candidates if c["id"] not in results]
        if to_fetch:

            def _worker(entry: dict) -> tuple[str, int | None]:
                vid = str(entry["id"])
                url = str(entry["url"])
                major = JavaUtils._fetch_version_java_major_from_url(url)
                return vid, major

            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_entry = {executor.submit(_worker, entry): entry for entry in to_fetch}
                for future in as_completed(future_to_entry):
                    try:
                        vid, major = future.result()
                        if major and major > 0:
                            results[vid] = major
                    except Exception as exc:
                        logger.debug("平行抓取版本 Java major 失敗: %s", exc)

        cleaned_results = JavaUtils._clean_requirements_cache(
            results,
            allowed_versions=known_versions if known_versions else None,
        )
        if cleaned_results:
            atomic_write_json(requirements_path, cleaned_results)
        return cleaned_results

    @staticmethod
    @lru_cache(maxsize=256)
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

        requirements_path = RuntimePaths.get_version_cache_dir() / JavaUtils.JAVA_REQUIREMENTS_CACHE_FILE_NAME
        cache_path = RuntimePaths.get_version_cache_dir() / "mc_versions_cache.json"

        versions_data = read_json(cache_path) if cache_path.exists() else None
        valid_ids: set[str] | None = None
        if isinstance(versions_data, list):
            valid_ids = {str(v["id"]) for v in versions_data if isinstance(v, dict) and v.get("id")}
        elif isinstance(versions_data, dict) and versions_data.get("id"):
            valid_ids = {str(versions_data["id"])}

        cached_requirements = JavaUtils._load_requirements_cache(
            requirements_path,
            allowed_versions=valid_ids if valid_ids else None,
        )
        cached_major = cached_requirements.get(mc_version)
        if isinstance(cached_major, int) and cached_major > 0:
            return cached_major

        if not cached_requirements:
            fresh_requirements = JavaUtils.preload_all_java_requirements()
            if mc_version in fresh_requirements:
                return fresh_requirements[mc_version]
            cached_requirements = fresh_requirements

        JavaUtils._ensure_cache_exists(cache_path)
        data = read_json(cache_path)
        if isinstance(data, dict):
            data = [data]
        elif not isinstance(data, list):
            data = []

        matched_url = None
        for v in data:
            if isinstance(v, dict) and v.get("id") == mc_version and "url" in v:
                matched_url = v["url"]
                break

        if not matched_url:
            try:
                manifest_url = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
                manifest_data = HTTPClient.fetch_json(manifest_url, timeout=10)
                if manifest_data and isinstance(manifest_data, dict) and "versions" in manifest_data:
                    atomic_write_json(cache_path, manifest_data["versions"])
                    for v in manifest_data["versions"]:
                        if isinstance(v, dict) and v.get("id") == mc_version and "url" in v:
                            matched_url = v["url"]
                            break
            except Exception as exc:
                logger.debug("重新整理 Mojang manifest 失敗: %s", exc)

        if not matched_url:
            raise ValueError(f"找不到對應 mc_version: {mc_version}")

        major = JavaUtils._fetch_version_java_major_from_url(matched_url)
        if major and major > 0:
            allowed = (valid_ids | {mc_version}) if valid_ids else None
            updated = JavaUtils._clean_requirements_cache(
                {**cached_requirements, mc_version: major},
                allowed_versions=allowed,
            )
            atomic_write_json(requirements_path, updated)
            return major

        raise ValueError(f"找不到 majorVersion，url: {matched_url}")

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
    ) -> str | None:
        """
        為指定 Minecraft 版本選擇最合適的 javaw.exe 路徑

        Args:
            mc_version: Minecraft 版本字串
            required_major: 指定的 Java major 版本；未提供時會自動推導

        Returns:
            找到時回傳 javaw.exe 路徑，否則回傳 None
        """
        required_major = required_major if required_major else JavaUtils.get_required_java_major(mc_version)
        candidates = JavaUtils.get_all_local_java_candidates()
        for path, major in candidates:
            if major == required_major:
                return path
        return None


__all__ = ["JavaUtils"]
