"""
更新資訊解析工具
集中處理版本字串、Release 資訊與更新資產選擇邏輯
"""

from functools import lru_cache
from typing import Any, ClassVar

from packaging.version import Version

from .. import HTTPUtils, get_logger
from ..core_utils.version_utils import parse_version_safe

logger = get_logger().bind(component="UpdateParsing")


class UpdateParsing:
    """更新資訊解析與更新資源選擇邏輯"""

    _GITHUB_API = "https://api.github.com"
    _HEX_CHARS: ClassVar[frozenset[str]] = frozenset("0123456789abcdefABCDEF")

    @staticmethod
    @lru_cache(maxsize=256)
    def parse_version(version_str: str | None) -> Version | None:
        """
        解析版本字串為 PEP 440 Version 物件

        Args:
            version_str: 原始版本字串

        Returns:
            解析後的 `Version`，失敗時回傳 None
        """
        if not isinstance(version_str, str) or not version_str.strip():
            logger.warning(f"無效的版本字串，version_str={version_str!r}")
            return None
        result = parse_version_safe(version_str)
        if result is None:
            logger.warning(f"版本字串解析失敗，version_str={version_str!r}")
        return result

    @staticmethod
    def get_latest_release(owner: str, repo: str, include_prerelease: bool = False) -> dict[str, Any] | None:
        """
        取得最新 release（預設忽略 prerelease），失敗時回傳 None

        Args:
            owner: GitHub repository owner
            repo: GitHub repository 名稱
            include_prerelease: 是否包含 prerelease

        Returns:
            最新 release 資料，找不到時回傳 None
        """
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
        """
        挑選 installer.exe 更新檔

        Args:
            release: GitHub release 資料

        Returns:
            選中的 installer 資源，找不到時回傳空字典
        """
        assets = release.get("assets") or []
        installer_assets = []
        for asset in assets:
            try:
                name = (asset.get("name") or "").lower()
                if (
                    name.endswith(".exe")
                    and "minecraftservermanager" in name
                    and "setup" not in name
                    and "installer" not in name
                    and asset.get("browser_download_url")
                ):
                    installer_assets.append(asset)
            except Exception as e:
                logger.debug(f"檢查 asset 資料時發生錯誤: {e}")
                continue
        if not installer_assets:
            return {}
        return installer_assets[0]

    @staticmethod
    def select_update_asset(release: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """
        挑選更新資產，並回傳選擇策略

        Args:
            release: GitHub release 資料

        Returns:
            (asset, mode)
            mode:
              - installer: 使用 installer exe
              - none: 找不到可用更新資源
        """
        installer_asset = UpdateParsing.choose_installer_asset(release)
        if installer_asset:
            return (installer_asset, "installer")
        return ({}, "none")

    @staticmethod
    def _is_hex_hash(token: str, expected_length: int) -> bool:
        """檢查 token 是否為指定長度的十六進位雜湊字串"""
        if len(token) != expected_length:
            return False
        return all(ch in UpdateParsing._HEX_CHARS for ch in token)

    @staticmethod
    def parse_asset_digest(asset: dict[str, Any]) -> tuple[str, str] | None:
        """
        從 GitHub release asset 的 digest 欄位解析 checksum

        Args:
            asset: GitHub release asset 資料

        Returns:
            `(algorithm, checksum)`，無法解析時回傳 None
        """
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
        return None
