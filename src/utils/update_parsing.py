#!/usr/bin/env python3
"""更新資訊解析工具
集中處理版本字串、Release 資訊與更新資產選擇邏輯。
"""

from pathlib import Path
from typing import Any

from .http_utils import HTTPUtils
from .logger import get_logger

logger = get_logger().bind(component="UpdateParsing")


class UpdateParsing:
    """更新資訊解析與更新資源選擇邏輯。"""

    _GITHUB_API = "https://api.github.com"

    @staticmethod
    def parse_version(version_str: str) -> tuple[int, ...] | None:
        """解析版本字串為數字元組，例如 v1.6.6 -> (1, 6, 6)。"""
        try:
            if not isinstance(version_str, str) or not version_str.strip():
                logger.warning(f"無效的版本字串，version_str={version_str!r}")
                return None
            clean = version_str.strip().lstrip("vV")
            version_part = clean.split("-")[0].split("+")[0]
            parsed = tuple(int(x) for x in version_part.split(".") if x.isdigit())
            if not parsed:
                logger.warning(f"版本字串解析失敗，version_str={version_str!r}")
                return None
            return parsed
        except ValueError:
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
                if rel and not rel.get("draft") and (include_prerelease or not rel.get("prerelease")):
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
                return portable_asset, "portable"

            installer_asset = UpdateParsing.choose_installer_asset(release)
            if installer_asset:
                return installer_asset, "installer_fallback"
            return {}, "none"

        installer_asset = UpdateParsing.choose_installer_asset(release)
        if installer_asset:
            return installer_asset, "installer"
        return {}, "none"

    @staticmethod
    def parse_checksum_text(text: str, asset_name: str) -> tuple[str, str] | None:
        """從 release body 或 checksum 檔內容解析指定資產的 checksum。"""
        asset_base = Path(asset_name).name
        asset_base_lower = asset_base.lower()
        for line in (text or "").splitlines():
            line = line.strip()
            if not line:
                continue
            line_lower = line.lower()
            parts = line.split()
            for token in parts:
                if len(token) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in token) and asset_base_lower in line_lower:
                    return ("sha256", token.lower())
                if len(token) == 128 and all(ch in "0123456789abcdefABCDEF" for ch in token) and asset_base_lower in line_lower:
                    return ("sha512", token.lower())
        return None
