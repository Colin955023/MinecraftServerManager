"""
應用程式更新檢查器模組
提供 GitHub Release 版本檢查與自動下載安裝功能
Application Update Checker Module
Provides GitHub Release version checking and automatic download installation functionality
"""
# ====== 標準函式庫 ======
from pathlib import Path
import os
import re
import tempfile
import threading
import requests
import webbrowser
# ====== 專案內部模組 ======
from .ui_utils import UIUtils
from .http_utils import HTTPUtils

# GitHub API 基礎 URL
GITHUB_API = "https://api.github.com"

# ====== 版本處理工具 ======
# 標準化版本號格式
def _normalize_version(v: str) -> tuple:
    """
    將版本字串標準化為可比較的數字元組
    Normalize version string to comparable number tuple

    Args:
        v (str): 版本字串（如 "v1.2.3" 或 "1.2.3"）

    Returns:
        tuple: 標準化的版本數字元組
    """
    if not v:
        return (0,)
    v = v.strip()
    if v.startswith(("v", "V")):
        v = v[1:]
    parts = re.split(r"[.\-+]", v)
    nums = []
    for p in parts:
        if p.isdigit():
            nums.append(int(p))
        else:
            break
    return tuple(nums) if nums else (0,)

# ====== GitHub API 操作 ======
# 取得最新正式發布版本資訊（自動篩選）
def _get_latest_release(owner: str, repo: str) -> dict:
    """
    從 GitHub API 取得指定倉庫的所有發布版本，並自動篩選最新正式版
    Get latest release information for specified repository from GitHub API (auto select latest stable)

    Args:
        owner (str): GitHub 倉庫擁有者
        repo (str): GitHub 倉庫名稱

    Returns:
        dict: 最新正式發布版本資訊字典，失敗時返回空字典
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/releases"
    r = HTTPUtils.get_json(url, timeout=10, headers={"Accept": "application/vnd.github+json"})
    if r:
        releases = r
        # 篩選出所有正式版（非草稿、非預發布）
        stable_releases = [rel for rel in releases if not rel.get("draft") and not rel.get("prerelease")]
        if not stable_releases:
            return {}
        # 依 tag_name 解析排序，選出最新
        stable_releases.sort(key=lambda rel: _normalize_version(rel.get("tag_name", "")), reverse=True)
        return stable_releases[0]
    return {}

# ====== 安裝檔案處理 ======
# 選擇適當的安裝檔案
def _choose_installer_asset(release: dict) -> dict:
    """
    從發布版本中選擇適當的 Windows 安裝檔案
    Choose appropriate Windows installer file from release assets

    Args:
        release (dict): GitHub Release 資訊字典

    Returns:
        dict: 選中的安裝檔案資產資訊，找不到時返回空字典
    """
    assets = release.get("assets") or []
    for a in assets:
        name = (a.get("name") or "").lower()
        if "setup" in name and name.endswith(".exe"):
            return a
    for a in assets:
        name = (a.get("name") or "").lower()
        if name.endswith(".exe"):
            return a
    return {}

# 下載檔案到指定位置
def _download_file(url: str, dest: Path) -> None:
    """
    下載檔案到指定路徑，支援大檔案串流下載
    Download file to specified path with large file streaming support

    Args:
        url (str): 檔案下載 URL
        dest (Path): 目標儲存路徑

    Returns:
        None
    """
    with requests.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)

# 啟動安裝程式
def _launch_installer(installer_path: Path) -> None:
    """
    啟動 Windows 安裝程式
    Launch Windows installer

    Args:
        installer_path (Path): 安裝程式檔案路徑

    Returns:
        None
    """
    os.startfile(str(installer_path))

# ====== 主要更新檢查功能 ======
# 檢查並提示更新
def check_and_prompt_update(current_version: str, owner: str, repo: str, show_up_to_date_message: bool = True) -> None:
    """
    檢查是否有新版本並提示使用者更新，支援自動下載安裝
    Check for new version and prompt user to update with automatic download installation support

    Args:
        current_version (str): 當前應用程式版本號
        owner (str): GitHub 倉庫擁有者
        repo (str): GitHub 倉庫名稱
        show_up_to_date_message (bool): 是否在已是最新版本時顯示訊息

    Returns:
        None
    """

    def _work():

        try:
            latest = _get_latest_release(owner, repo)

            # 檢查是否有有效的最新版本（排除草稿和預發布版本）
            if not latest or latest.get("draft") or latest.get("prerelease"):
                if show_up_to_date_message:
                    UIUtils.show_info("檢查更新", "無法取得最新版本資訊，或沒有可用的正式發布版本。", topmost=True)
                return

            latest_tag = latest.get("tag_name") or ""
            current_normalized = _normalize_version(current_version)
            latest_normalized = _normalize_version(latest_tag)

            # 檢查版本比較結果
            if latest_normalized <= current_normalized:
                if show_up_to_date_message:
                    UIUtils.show_info("檢查更新", f"目前版本 {current_version} 已是最新版本，無須更新。", topmost=True)
                return

            # 發現新版本，提示使用者
            name = latest.get("name") or latest_tag
            body = latest.get("body") or "(無釋出說明)"
            html_url = latest.get("html_url")

            msg = f"發現新版本：{name}\n目前版本：{current_version}\n\n釋出說明：\n{body}\n\n是否下載並安裝？"
            if not UIUtils.ask_yes_no_cancel("更新可用", msg, show_cancel=False, topmost=True):
                if html_url and UIUtils.ask_yes_no_cancel(
                    "查看發行頁面", "是否前往 GitHub 發行頁面查看詳情？", show_cancel=False, topmost=True
                ):
                    webbrowser.open(html_url)
                return

            asset = _choose_installer_asset(latest)
            if not asset:
                UIUtils.show_info("無安裝檔", "找不到可用的安裝檔（.exe）。將開啟發行頁面，請手動下載。", topmost=True)
                if html_url:
                    webbrowser.open(html_url)
                return

            download_url = asset.get("browser_download_url")
            fd, temp_path = tempfile.mkstemp(prefix="msm_update_", suffix=".exe")
            os.close(fd)
            dest = Path(temp_path)
            UIUtils.show_info("下載中", "正在下載安裝檔，請稍候...", topmost=True)
            _download_file(download_url, dest)
            UIUtils.show_info("下載完成", "將啟動安裝程式進行更新，請依畫面指示操作。", topmost=True)
            _launch_installer(dest)
        except Exception as e:
            UIUtils.show_error("更新檢查失敗", f"無法完成更新檢查或下載：{e}", topmost=True)

    threading.Thread(target=_work, daemon=True).start()
