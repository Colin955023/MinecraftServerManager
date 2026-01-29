"""應用程式更新檢查器模組
提供 GitHub Release 版本檢查與自動下載安裝功能
"""

import os
import re
import subprocess
import tempfile
import threading
import webbrowser
from pathlib import Path
from typing import Any

from . import HTTPUtils, UIUtils, get_logger

logger = get_logger().bind(component="UpdateChecker")

GITHUB_API = "https://api.github.com"


def _parse_version(version_str: str) -> tuple[int, ...] | None:
    """解析版本字串為數字元組（使用簡單的標準方法）
    Parse version string to tuple of integers
    
    Args:
        version_str: 版本字串（可能包含 'v' 或 'V' 前綴）
        
    Returns:
        版本數字元組，解析失敗時返回 None
        
    Examples:
        "v1.2.3" -> (1, 2, 3)
        "1.2.3-beta" -> (1, 2, 3)
    """
    try:
        # 移除 v/V 前綴，取數字部分
        clean = version_str.strip().lstrip("vV")
        # 只取數字和點號部分（忽略 -beta 等後綴）
        version_part = clean.split("-")[0].split("+")[0]
        return tuple(int(x) for x in version_part.split(".") if x.isdigit())
    except (ValueError, AttributeError):
        return None


def _get_latest_release(owner: str, repo: str) -> dict:
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
    try:
        os.startfile(str(installer_path))
    except (AttributeError, OSError) as e:
        try:
            subprocess.Popen([str(installer_path)], shell=False)
        except Exception:
            logger.exception(f"安裝程式啟動失敗: {e}")


def check_and_prompt_update(
    current_version: str,
    owner: str,
    repo: str,
    show_up_to_date_message: bool = True,
    parent=None,
) -> None:
    def _call_on_ui(func):
        try:
            if (
                parent is not None
                and hasattr(parent, "after")
                and hasattr(parent, "winfo_exists")
                and parent.winfo_exists()
            ):
                if threading.current_thread() is threading.main_thread():
                    return func()

                result: dict[str, Any] = {"value": None, "exc": None}
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
                if isinstance(result["exc"], Exception):
                    raise result["exc"]
                return result["value"]
        except Exception as e:
            logger.debug(f"UI 排程執行失敗，回退至直接呼叫: {e}")
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
                        ),
                    )
                return

            latest_tag = latest.get("tag_name") or ""

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
                        ),
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
                ),
            ):
                if html_url and _call_on_ui(
                    lambda: UIUtils.ask_yes_no_cancel(
                        "查看發行頁面",
                        "是否前往 GitHub 發行頁面查看詳情？",
                        parent=parent,
                        show_cancel=False,
                        topmost=True,
                    ),
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
                    ),
                )
                if html_url:
                    webbrowser.open(html_url)
                return

            download_url = asset.get("browser_download_url")
            with tempfile.NamedTemporaryFile(delete=False, prefix="msm_update_", suffix=".exe") as tmp:
                temp_path = tmp.name
            dest = Path(temp_path)

            _call_on_ui(
                lambda: UIUtils.show_info(
                    "下載中",
                    "正在下載安裝檔，請稍候...",
                    parent=parent,
                    topmost=True,
                ),
            )
            if HTTPUtils.download_file(download_url, str(dest)):
                _call_on_ui(
                    lambda: UIUtils.show_info(
                        "下載完成",
                        "將啟動安裝程式進行更新，請依畫面指示操作。",
                        parent=parent,
                        topmost=True,
                    ),
                )
                _launch_installer(dest)
            else:
                _call_on_ui(
                    lambda: UIUtils.show_error(
                        "下載失敗",
                        "無法下載安裝檔，請稍後再試。",
                        parent=parent,
                        topmost=True,
                    ),
                )
        except Exception as e:
            logger.exception(f"更新檢查失敗: {e}")
            error_msg = str(e)
            _call_on_ui(
                lambda: UIUtils.show_error(
                    "更新檢查失敗",
                    f"無法完成更新檢查或下載：{error_msg}",
                    parent=parent,
                    topmost=True,
                ),
            )

    threading.Thread(target=_work, daemon=True).start()
