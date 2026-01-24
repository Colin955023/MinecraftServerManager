"""
應用程式更新檢查器模組
提供 GitHub Release 版本檢查與自動下載安裝功能
"""

# ====== 標準函式庫 ======
from pathlib import Path
from typing import Optional
import os
import re
import tempfile
import threading
import webbrowser

# ====== 第三方函式庫 ======
from packaging.version import Version, InvalidVersion

# ====== 專案內部模組 ======
from .http_utils import HTTPUtils
from .logger import get_logger
from .ui_utils import UIUtils

logger = get_logger().bind(component="UpdateChecker")

GITHUB_API = "https://api.github.com"


def _parse_version(version_str: str) -> Optional[Version]:
    """
    解析版本字串為 Version 物件
    Parse version string to Version object
    
    Args:
        version_str: 版本字串（可能包含 'v' 或 'V' 前綴）
    
    Returns:
        Version 物件，解析失敗時返回 None
    """
    try:
        # 移除前綴 'v' 或 'V'
        clean_version = version_str.strip().lstrip('vV')
        return Version(clean_version)
    except (InvalidVersion, Exception):
        return None


def _get_latest_release(owner: str, repo: str) -> dict:
    """從 GitHub API 取得最新正式發布版本資訊（排除 draft/prerelease）。"""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/releases"
    data = HTTPUtils.get_json(url, timeout=15)
    if not data:
        return {}

    # GitHub API 正常會回傳 list[release]
    if isinstance(data, dict):
        # 兼容：若 API 回傳錯誤物件
        return {}

    for rel in data:
        try:
            if rel and not rel.get("draft") and not rel.get("prerelease"):
                return rel
        except Exception as e:
            logger.debug(f"檢查 release 資料時發生錯誤: {e}")
            continue
    return {}


def _choose_installer_asset(release: dict) -> dict:
    """從 release assets 中挑選可用的 Windows 安裝檔（.exe）。"""
    assets = release.get("assets") or []
    exe_assets = []
    for a in assets:
        try:
            name = (a.get("name") or "").lower()
            if name.endswith(".exe") and a.get("browser_download_url"):
                exe_assets.append(a)
        except Exception as e:
            logger.debug(f"檢查 asset 資料時發生錯誤: {e}")
            continue
    if not exe_assets:
        return {}

    # 優先挑名字像 installer/setup 的
    for a in exe_assets:
        name = (a.get("name") or "").lower()
        if "setup" in name or "installer" in name:
            return a
    return exe_assets[0]


def _launch_installer(installer_path: Path) -> None:
    """啟動 Windows 安裝程式。"""
    os.startfile(str(installer_path))


def check_and_prompt_update(
    current_version: str,
    owner: str,
    repo: str,
    show_up_to_date_message: bool = True,
    parent=None,
) -> None:
    """檢查是否有新版本並提示使用者更新（背景執行以避免阻塞 UI）。

    注意：Tkinter/CustomTkinter 的 UI 操作應在主執行緒進行。
    若傳入 parent（通常是主視窗 root），本函式會把所有對話框呼叫排回主執行緒。
    """

    def _call_on_ui(func):
        """確保 UI 對話框在主執行緒執行，並等待其完成（保留既有流程語意）。"""
        try:
            if (
                parent is not None
                and hasattr(parent, "after")
                and hasattr(parent, "winfo_exists")
                and parent.winfo_exists()
            ):
                if threading.current_thread() is threading.main_thread():
                    return func()

                result = {"value": None, "exc": None}
                done = threading.Event()

                def _runner():
                    try:
                        result["value"] = func()
                    except Exception as e:
                        result["exc"] = e
                    finally:
                        done.set()

                parent.after(0, _runner)
                done.wait()
                if result["exc"] is not None:
                    raise result["exc"]
                return result["value"]
        except Exception as e:
            # 任何排程失敗都退回直接呼叫（最後備援）
            logger.debug(f"UI 排程執行失敗，回退至直接呼叫: {e}")
            pass
        return func()

    def _work() -> None:
        try:
            latest = _get_latest_release(owner, repo)
            if not latest:
                if show_up_to_date_message:
                    _call_on_ui(
                        lambda: UIUtils.show_info(
                            "檢查更新",
                            "無法取得最新版本資訊，或沒有可用的正式發布版本。",
                            parent=parent,
                            topmost=True,
                        )
                    )
                return

            latest_tag = latest.get("tag_name") or ""
            
            # 使用 packaging.version 進行版本比較
            latest_ver = _parse_version(latest_tag)
            current_ver = _parse_version(current_version)
            
            if not latest_ver or not current_ver:
                logger.warning("無法解析版本號，跳過更新檢查")
                return
            
            # 比較版本
            if latest_ver <= current_ver:
                if show_up_to_date_message:
                    _call_on_ui(
                        lambda: UIUtils.show_info(
                            "檢查更新",
                            f"目前版本 {current_version} 已是最新版本，無須更新。",
                            parent=parent,
                            topmost=True,
                        )
                    )
                return

            name = latest.get("name") or latest_tag
            body = latest.get("body") or "(無釋出說明)"
            html_url = latest.get("html_url")

            msg = f"發現新版本：{name}\n目前版本：{current_version}\n\n釋出說明：\n{body}\n\n是否下載並安裝？"
            if not _call_on_ui(
                lambda: UIUtils.ask_yes_no_cancel(
                    "更新可用",
                    msg,
                    parent=parent,
                    show_cancel=False,
                    topmost=True,
                )
            ):
                if html_url and _call_on_ui(
                    lambda: UIUtils.ask_yes_no_cancel(
                        "查看發行頁面",
                        "是否前往 GitHub 發行頁面查看詳情？",
                        parent=parent,
                        show_cancel=False,
                        topmost=True,
                    )
                ):
                    webbrowser.open(html_url)
                return

            asset = _choose_installer_asset(latest)
            if not asset:
                _call_on_ui(
                    lambda: UIUtils.show_info(
                        "無安裝檔",
                        "找不到可用的安裝檔（.exe）。將開啟發行頁面，請手動下載。",
                        parent=parent,
                        topmost=True,
                    )
                )
                if html_url:
                    webbrowser.open(html_url)
                return

            download_url = asset.get("browser_download_url")
            fd, temp_path = tempfile.mkstemp(prefix="msm_update_", suffix=".exe")
            os.close(fd)
            dest = Path(temp_path)

            _call_on_ui(
                lambda: UIUtils.show_info(
                    "下載中",
                    "正在下載安裝檔，請稍候...",
                    parent=parent,
                    topmost=True,
                )
            )
            if HTTPUtils.download_file(download_url, str(dest)):
                _call_on_ui(
                    lambda: UIUtils.show_info(
                        "下載完成",
                        "將啟動安裝程式進行更新，請依畫面指示操作。",
                        parent=parent,
                        topmost=True,
                    )
                )
                _launch_installer(dest)
            else:
                _call_on_ui(
                    lambda: UIUtils.show_error(
                        "下載失敗",
                        "無法下載安裝檔，請稍後再試。",
                        parent=parent,
                        topmost=True,
                    )
                )
        except Exception as e:
            logger.exception(f"更新檢查失敗: {e}")
            _call_on_ui(
                lambda: UIUtils.show_error(
                    "更新檢查失敗",
                    f"無法完成更新檢查或下載：{e}",
                    parent=parent,
                    topmost=True,
                )
            )

    threading.Thread(target=_work, daemon=True).start()
