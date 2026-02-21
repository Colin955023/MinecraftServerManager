"""更新資訊解析工具
集中處理版本字串、Release 資訊與更新資產選擇邏輯。
"""

from functools import lru_cache
from typing import Any, ClassVar
from packaging.version import InvalidVersion, Version
from . import HTTPUtils, get_logger

logger = get_logger().bind(component="UpdateParsing")


class UpdateParsing:
    """更新資訊解析與更新資源選擇邏輯。"""

    _GITHUB_API = "https://api.github.com"
    _HEX_CHARS: ClassVar[frozenset[str]] = frozenset("0123456789abcdefABCDEF")

    @staticmethod
    @lru_cache(maxsize=256)
    def parse_version(version_str: str | None) -> Version | None:
        """解析版本字串為 PEP 440 Version 物件。"""
        try:
            if not isinstance(version_str, str) or not version_str.strip():
                logger.warning(f"無效的版本字串，version_str={version_str!r}")
                return None
            clean = version_str.strip().lstrip("vV")
            return Version(clean)
        except InvalidVersion:
            logger.warning(f"版本字串解析失敗，version_str={version_str!r}")
            return None

    @staticmethod
    def get_latest_release(owner: str, repo: str, include_prerelease: bool = False) -> dict[str, Any] | None:
        """取得最新 release（預設忽略 prerelease），失敗時回傳 None。"""
        url = f"{UpdateParsing._GITHUB_API}/repos/{owner}/{repo}/releases"
        data = HTTPUtils.get_json(url, timeout=15)
        if not data or isinstance(data, dict):
            return None
        for rel in data:
            try:
                if rel and (not rel.get("draft")) and (include_prerelease or not rel.get("prerelease")):
                    return rel
            except Exception as e:
                logger.debug(f"檢查 release 資料時發生錯誤: {e}")
                continue
        return None

    @staticmethod
    def choose_installer_asset(release: dict[str, Any]) -> dict[str, Any]:
        """挑選 installer.exe 更新檔。"""
        assets = release.get("assets") or []
        exe_assets = []
        for asset in assets:
            try:
                name = (asset.get("name") or "").lower()
                if name.endswith(".exe") and asset.get("browser_download_url"):
                    exe_assets.append(asset)
            except Exception as e:
                logger.debug(f"檢查 asset 資料時發生錯誤: {e}")
                continue
        if not exe_assets:
            return {}
        for asset in exe_assets:
            name = (asset.get("name") or "").lower()
            if "setup" in name or "installer" in name:
                return asset
        return exe_assets[0]

    @staticmethod
    def choose_portable_asset(release: dict[str, Any]) -> dict[str, Any]:
        """挑選 portable.zip 更新檔。"""
        assets = release.get("assets") or []
        for asset in assets:
            try:
                name_l = (asset.get("name") or "").lower()
                if name_l.endswith(".zip") and "portable" in name_l and asset.get("browser_download_url"):
                    return asset
            except Exception as e:
                logger.debug(f"檢查可攜式資源時發生錯誤，跳過此資源: {e}")
                continue
        return {}

    @staticmethod
    def select_update_asset(release: dict[str, Any], portable_mode: bool) -> tuple[dict[str, Any], str]:
        """根據執行模式挑選更新資產，並回傳選擇策略。

        Returns:
            (asset, mode)
            mode:
              - portable: portable 模式且找到 portable zip
              - installer: installer 模式，使用 installer exe
              - installer_fallback: portable 模式找不到 zip，回退 installer exe
              - none: 找不到可用更新資源
        """
        if portable_mode:
            portable_asset = UpdateParsing.choose_portable_asset(release)
            if portable_asset:
                return (portable_asset, "portable")
            installer_asset = UpdateParsing.choose_installer_asset(release)
            if installer_asset:
                return (installer_asset, "installer_fallback")
            return ({}, "none")
        installer_asset = UpdateParsing.choose_installer_asset(release)
        if installer_asset:
            return (installer_asset, "installer")
        return ({}, "none")

    @staticmethod
    def _is_hex_hash(token: str, expected_length: int) -> bool:
        """檢查 token 是否為指定長度的十六進位雜湊字串。"""
        if len(token) != expected_length:
            return False
        return all(ch in UpdateParsing._HEX_CHARS for ch in token)

    @staticmethod
    def parse_asset_digest(asset: dict[str, Any]) -> tuple[str, str] | None:
        """從 GitHub release asset 的 digest 欄位解析 checksum。"""
        digest = (asset.get("digest") or "").strip()
        if not digest:
            return None
        algorithm, separator, checksum = digest.partition(":")
        if not separator:
            return None
        algorithm = algorithm.strip().lower()
        checksum = checksum.strip().lower()
        if algorithm == "sha256" and UpdateParsing._is_hex_hash(checksum, 64):
            return (algorithm, checksum)
        if algorithm == "sha512" and UpdateParsing._is_hex_hash(checksum, 128):
            return (algorithm, checksum)
        return None
