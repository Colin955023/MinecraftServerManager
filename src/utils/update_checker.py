"""應用程式更新檢查器模組
提供 GitHub Release 版本檢查與自動下載安裝功能
"""

import html as _html
import re
import sys
import tempfile
import time
from pathlib import Path

import markdown as _markdown

from . import (
    HTTPUtils,
    PathUtils,
    RuntimePaths,
    SubprocessUtils,
    UIUtils,
    get_logger,
)

logger = get_logger().bind(component="UpdateChecker")


class UpdateChecker:
    _GITHUB_API = "https://api.github.com"

    @staticmethod
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

    @staticmethod
    def _get_latest_release(owner: str, repo: str) -> dict:
        url = f"{UpdateChecker._GITHUB_API}/repos/{owner}/{repo}/releases"
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

    @staticmethod
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

    @staticmethod
    def _launch_installer(installer_path: Path) -> None:
        """啟動安裝程式"""
        try:
            if installer_path.exists() and installer_path.is_file():
                SubprocessUtils.popen_checked([str(installer_path)])
                logger.info(f"已啟動安裝程式: {installer_path}")
            else:
                logger.error(f"安裝程式不存在或不是檔案：{installer_path}")
        except Exception as e:
            logger.exception(f"安裝程式啟動失敗: {e}")

    @staticmethod
    def _clean_release_notes(body: str) -> str:
        """清理並篩選釋出說明，過濾開發者資訊與過長內容

        僅保留: 新增功能、修改、刪除、優化等使用者相關資訊
        濾除: 開發者資訊 (contributors, full changelog 連結, PR 作者資訊)
        """
        if not body:
            return "(無釋出說明)"

        lines = body.splitlines()
        kept_lines = []
        ignoring = False

        for line in lines:
            l_strip = line.strip()
            l_lower = l_strip.lower()

            # 忽略 "New Contributors" 或 "Full Changelog" 區塊
            if "new contributors" in l_lower or "full changelog" in l_lower:
                ignoring = True
                if "full changelog" in l_lower:
                    break
                continue

            if ignoring:
                # 若遇到新的標題 (## ...) 且看起來像功能區塊，則停止忽略
                if l_strip.startswith("#"):
                    ignoring = False
                else:
                    continue

            # 移除 GitHub 自動生成的 PR 資訊: "by @user in https://..."
            clean_line = re.sub(r"\s+by\s+@[\w\-]+", "", line)
            clean_line = re.sub(r"\s+in\s+https://\S+", "", clean_line)

            if not clean_line.strip():
                continue

            kept_lines.append(clean_line)

        text = "\n".join(kept_lines)
        try:
            html = _markdown.markdown(text)
            text_only = re.sub(r"<[^<]+?>", "", html)
            decoded = _html.unescape(text_only)
        except Exception:
            decoded = text

        final_lines = [x for x in decoded.splitlines() if x.strip()]
        if len(final_lines) > 15:
            final_lines = final_lines[:15]
            final_lines.append("... (完整內容請查看發行頁面)")

        return "\n".join(final_lines)

    @staticmethod
    def check_and_prompt_update(
        current_version: str,
        owner: str,
        repo: str,
        show_up_to_date_message: bool = True,
        parent=None,
    ) -> None:
        def _work() -> None:
            try:
                logger.info(f"開始檢查更新... (目前版本: {current_version})")
                latest = UpdateChecker._get_latest_release(owner, repo)
                if not latest:
                    logger.info("無法從 GitHub 取得最新版本資訊")
                    if show_up_to_date_message:
                        UIUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_info(
                                "檢查更新",
                                "無法取得最新版本資訊，或沒有可用的正式發布版本。",
                                parent=parent,
                                topmost=True,
                            ),
                        )
                    return

                latest_tag = latest.get("tag_name") or ""

                latest_ver = UpdateChecker._parse_version(latest_tag)
                current_ver = UpdateChecker._parse_version(current_version)

                if not latest_ver or not current_ver:
                    logger.warning("無法解析版本號，跳過更新檢查")
                    return

                logger.info(f"版本檢查: 目前版本={current_ver}, 最新版本={latest_ver} ({latest_tag})")

                # 比較版本
                if latest_ver <= current_ver:
                    logger.info("目前已是最新版本")
                    if show_up_to_date_message:
                        UIUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_info(
                                "檢查更新",
                                f"目前版本 {current_version} 已是最新版本，無須更新。",
                                parent=parent,
                                topmost=True,
                            ),
                        )
                    return

                name = latest.get("name") or latest_tag
                logger.info(f"發現新版本: {name}")
                body = latest.get("body") or "(無釋出說明)"

                # 使用清理後的釋出說明
                rendered = UpdateChecker._clean_release_notes(body)

                html_url = latest.get("html_url")

                msg = f"發現新版本：{name}\n目前版本：{current_version}\n\n釋出說明：\n{rendered}\n\n是否下載並安裝？"
                if not UIUtils.call_on_ui(
                    parent,
                    lambda: UIUtils.ask_yes_no_cancel(
                        "更新可用",
                        msg,
                        parent=parent,
                        show_cancel=False,
                        topmost=True,
                    ),
                ):
                    if html_url and UIUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.ask_yes_no_cancel(
                            "查看發行頁面",
                            "是否前往 GitHub 發行頁面查看詳情？",
                            parent=parent,
                            show_cancel=False,
                            topmost=True,
                        ),
                    ):
                        UIUtils.open_external(html_url)
                    return

                logger.info("使用者確認更新，準備下載...")

                # 若為可攜式，優先尋找 portable zip asset
                asset = None
                if RuntimePaths.is_portable_mode():
                    assets = latest.get("assets") or []
                    for a in assets:
                        try:
                            name_l = (a.get("name") or "").lower()
                            if name_l.endswith(".zip") and "portable" in name_l:
                                asset = a
                                break
                        except Exception as e:
                            logger.debug(f"檢查可攜式資源時發生錯誤，跳過此資源: {e}")
                            continue

                # 若尚未選到，使用原有的 exe 選擇邏輯
                if not asset:
                    asset = UpdateChecker._choose_installer_asset(latest)

                if not asset:
                    UIUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.show_info(
                            "無安裝檔",
                            "找不到可用的安裝檔（.exe 或 portable.zip）。將開啟發行頁面，請手動下載。",
                            parent=parent,
                            topmost=True,
                        ),
                    )
                    if html_url:
                        UIUtils.open_external(html_url)
                    return

                download_url = asset.get("browser_download_url")

                # Helper: 嘗試從 release 的 assets 或 body 解析出對應 asset 的 checksum
                def _parse_checksum_text(text: str, asset_name: str) -> tuple[str, str] | None:
                    asset_base = Path(asset_name).name
                    for line in (text or "").splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split()
                        for token in parts:
                            if re.fullmatch(r"[0-9a-fA-F]{64}", token) and asset_base in line:
                                return ("sha256", token.lower())
                            if re.fullmatch(r"[0-9a-fA-F]{128}", token) and asset_base in line:
                                return ("sha512", token.lower())
                    return None

                def _fetch_checksum_for_asset(release: dict, asset_name: str) -> tuple[str, str] | None:
                    try:
                        assets = release.get("assets") or []
                        for a in assets:
                            try:
                                an = (a.get("name") or "").lower()
                                if an.endswith((".sha256", ".sha256sum", ".sha512", ".sha512sum")):
                                    with tempfile.NamedTemporaryFile(
                                        delete=False, prefix="msm_chk_", suffix=".txt"
                                    ) as tf:
                                        tfpath = tf.name
                                    if HTTPUtils.download_file(a.get("browser_download_url"), tfpath):
                                        txt = Path(tfpath).read_text(encoding="utf-8", errors="ignore")
                                        c = _parse_checksum_text(txt, asset_name)
                                        if c:
                                            return c
                            except Exception as e:
                                logger.debug(f"檢查 checksum 檔案時發生錯誤，嘗試下一個: {e}")
                                continue
                        # fallback: try release body
                        body = release.get("body") or ""
                        c = _parse_checksum_text(body, asset_name)
                        if c:
                            return c
                    except Exception:
                        logger.debug("取得 checksum 時發生錯誤")
                    return None

                def _verify_file_checksum(path: Path, algorithm: str, hex_checksum: str) -> bool:
                    checksum = PathUtils.calculate_checksum(path, algorithm)
                    return checksum == hex_checksum.lower() if checksum else False

                # 如果是可攜式更新（asset 為 portable zip），採用 ZIP 解壓套用流程
                if RuntimePaths.is_portable_mode() and download_url and str(download_url).lower().endswith(".zip"):
                    if not UIUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.ask_yes_no_cancel(
                            "可攜式更新可用",
                            f"發現可攜式更新：{name}\n是否下載並套用？\n（會備份整個應用程式與 .config/.log，確保可恢復）",
                            parent=parent,
                            show_cancel=False,
                            topmost=True,
                        ),
                    ):
                        return

                    logger.info("使用者確認更新，開始更新流程")
                    close_delay_seconds = 3

                    # 下載 zip
                    with tempfile.NamedTemporaryFile(delete=False, prefix="msm_portable_", suffix=".zip") as tmpf:
                        tmp_zip_path = tmpf.name
                    if not HTTPUtils.download_file(download_url, tmp_zip_path):
                        UIUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error("下載失敗", "無法下載可攜式更新。", parent=parent, topmost=True),
                        )
                        return

                    # 嘗試取得並驗證 checksum（若有提供）
                    try:
                        chk = _fetch_checksum_for_asset(latest, asset.get("name") or "")
                        if chk:
                            alg, hexsum = chk
                            ok = _verify_file_checksum(Path(tmp_zip_path), alg, hexsum)
                            if not ok:
                                logger.error(f"可攜式更新檔 checksum 驗證失敗: {asset.get('name')} ({alg})")
                                try:
                                    Path(tmp_zip_path).unlink(missing_ok=True)
                                except Exception as e:
                                    logger.error(f"刪除暫存檔案失敗: {e}")
                                UIUtils.call_on_ui(
                                    parent,
                                    lambda: UIUtils.show_error(
                                        "驗證失敗",
                                        "可攜式更新檔的 checksum 驗證失敗，已取消下載以避免損壞。",
                                        parent=parent,
                                        topmost=True,
                                    ),
                                )
                                return
                            logger.info(f"可攜式更新檔 checksum 驗證通過: {asset.get('name')} ({alg})")
                        else:
                            logger.debug("未找到可用的 checksum，將略過驗證")
                    except Exception:
                        logger.exception("在 checksum 驗證流程發生錯誤，將中止更新以避免風險")
                        UIUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error(
                                "驗證錯誤",
                                "在驗證更新檔時發生錯誤，停止更新以避免風險。",
                                parent=parent,
                                topmost=True,
                            ),
                        )
                        return

                    # 解壓到暫存資料夾
                    extracted_dir = Path(tempfile.mkdtemp(prefix="msm_portable_extracted_"))
                    try:
                        PathUtils.safe_extract_zip(Path(tmp_zip_path), extracted_dir)
                    except Exception as e:
                        logger.exception(f"解壓更新檔失敗: {e}")
                        UIUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error(
                                "解壓失敗", "無法解壓下載的更新檔。", parent=parent, topmost=True
                            ),
                        )
                        return

                    # 備份整個原始目錄與 .config/.log
                    base = RuntimePaths._get_portable_base_dir()
                    cfg = base / ".config"
                    lg = base / ".log"

                    # 通知使用者準備關閉程式進行更新
                    UIUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.show_info(
                            "更新中",
                            "正在應用更新，程式將在 3 秒後關閉...",
                            parent=parent,
                            topmost=True,
                        ),
                    )

                    logger.info("通知使用者程式將關閉進行更新")

                    backup_root = Path(tempfile.mkdtemp(prefix="msm_portable_backup_"))
                    logger.info(f"開始備份原始目錄與配置: {backup_root}")

                    try:
                        # 備份整個原始目錄（不包括 .config/.log/.portable）
                        backup_dir = backup_root / "original"
                        PathUtils.copy_dir(
                            base,
                            backup_dir,
                            ignore_patterns=[".config", ".log", ".portable"],
                        )

                        # 單獨備份 .config 與 .log
                        if cfg.exists():
                            PathUtils.copy_dir(cfg, backup_root / ".config")
                            logger.info("已備份 .config")
                        if lg.exists():
                            PathUtils.copy_dir(lg, backup_root / ".log")
                            logger.info("已備份 .log")
                    except Exception as e:
                        error_msg = str(e)
                        logger.exception(f"備份失敗: {error_msg}")
                        UIUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error(
                                "備份失敗",
                                f"無法備份現有配置，停止更新以確保安全。\n{error_msg}",
                                parent=parent,
                                topmost=True,
                            ),
                        )
                        return

                    # 建立套用更新的批次檔，等待主程式退出後執行更新
                    apply_bat = Path(tempfile.gettempdir()) / f"msm_apply_update_{int(time.time())}.bat"
                    src = str(extracted_dir).replace("/", "\\")
                    dst = str(base).replace("/", "\\")
                    backup_path = str(backup_root).replace("/", "\\")

                    # 檢查解壓後的結構：如果第一層只有 MinecraftServerManager 資料夾，則進入它
                    extracted_items = list(extracted_dir.iterdir())
                    if (
                        len(extracted_items) == 1
                        and extracted_items[0].is_dir()
                        and extracted_items[0].name == "MinecraftServerManager"
                    ):
                        src = str(extracted_items[0]).replace("/", "\\")
                        logger.info(f"檢測到嵌套資料夾，調整源路徑為: {src}")

                    bat = (
                        "@echo off\n"
                        "chcp 65001 >nul\n"
                        "setlocal enabledelayedexpansion\n"
                        "REM 等待主程式完全退出（檢查20次，每次等待1秒）\n"
                        'set "count=0"\n'
                        ":wait_loop\n"
                        'tasklist /FI "IMAGENAME eq MinecraftServerManager.exe" 2>nul | find /I "MinecraftServerManager.exe" >nul\n'
                        "if %ERRORLEVEL%==0 (\n"
                        "    if !count! lss 20 (\n"
                        "        set /a count=!count!+1\n"
                        "        timeout /t 1 /nobreak >nul\n"
                        "        goto wait_loop\n"
                        "    )\n"
                        ")\n"
                        "REM 給予額外的時間確保所有檔案都解鎖\n"
                        "timeout /t 3 /nobreak >nul\n"
                        f"REM 刪除整個原始目錄（含重試邏輯）\n"
                        f'set "retry_count=0"\n'
                        f":delete_retry\n"
                        f'for /d %%I in ("{dst}\\*") do (\n'
                        f'    rmdir /s /q "%%I" 2>nul\n'
                        f")\n"
                        f'for %%I in ("{dst}\\*") do (\n'
                        f'    del /q "%%I" 2>nul\n'
                        f")\n"
                        f"timeout /t 1 /nobreak >nul\n"
                        f"REM 複製新版本檔案（使用 PowerShell 以獲得更好的錯誤處理）\n"
                        f'powershell -Command "try {{ Copy-Item -Path \\"{src}\\*\\" -Destination \\"{dst}\\" -Recurse -Force -ErrorAction Stop }} catch {{ exit 1 }}"\n'
                        f"if %ERRORLEVEL% neq 0 (\n"
                        f"    echo 複製失敗，嘗試使用 xcopy...\n"
                        f'    xcopy "{src}\\*" "{dst}\\" /E /Y /I /R\n'
                        f")\n"
                        f"REM 恢復備份的 .config 與 .log\n"
                        f'if exist "{backup_path}\\.config" (\n'
                        f'    xcopy "{backup_path}\\.config\\*" "{dst}\\.config\\" /E /Y /I /R 2>nul\n'
                        f")\n"
                        f'if exist "{backup_path}\\.log" (\n'
                        f'    xcopy "{backup_path}\\.log\\*" "{dst}\\.log\\" /E /Y /I /R 2>nul\n'
                        f")\n"
                        f"REM 恢復或建立 .portable 標記\n"
                        f'if not exist "{dst}\\.portable" (\n'
                        f'    echo. > "{dst}\\.portable"\n'
                        f'    attrib +h "{dst}\\.portable" 2>nul\n'
                        f")\n"
                        f"REM 啟動新版本\n"
                        f"timeout /t 2 /nobreak >nul\n"
                        f'start "" "{dst}\\MinecraftServerManager.exe"\n'
                        f"REM 刪除備份（更新成功後）\n"
                        f"timeout /t 5 /nobreak >nul\n"
                        f'rmdir /s /q "{backup_path}" 2>nul\n'
                        "endlocal\n"
                        "exit /b 0\n"
                    )
                    try:
                        apply_bat.write_text(bat, encoding="utf-8")
                    except Exception:
                        logger.exception("寫入批次檔失敗")
                        UIUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error("錯誤", "無法建立套用更新的腳本。", parent=parent, topmost=True),
                        )
                        return

                    try:
                        cmd_exe = PathUtils.find_executable("cmd.exe") or "C:\\Windows\\System32\\cmd.exe"
                        # 安全修復：使用 SubprocessUtils.popen_checked 替代 subprocess.Popen
                        SubprocessUtils.popen_checked([cmd_exe, "/c", "start", "", str(apply_bat)])
                    except Exception:
                        logger.exception("啟動套用批次檔失敗")
                    logger.info("更新批次已啟動，準備關閉程式以進行更新")

                    def _exit_current_app() -> None:
                        try:
                            if parent is not None and hasattr(parent, "after") and hasattr(parent, "winfo_exists"):

                                def _close():
                                    try:
                                        if parent.winfo_exists():
                                            parent.quit()
                                            parent.destroy()
                                    except Exception as e:
                                        logger.exception(f"關閉視窗失敗: {e}")
                                    finally:
                                        sys.exit(0)

                                parent.after(100, _close)
                                return
                        except Exception as e:
                            logger.debug(f"安排視窗關閉時發生錯誤: {e}")

                        sys.exit(0)

                    # 可攜式更新：不要啟動內建重啟流程，直接退出，交由批次檔等待並重啟
                    time.sleep(close_delay_seconds)
                    _exit_current_app()
                    return

                # 非可攜式或找不到 portable zip，沿用原有 installer.exe 流程
                with tempfile.NamedTemporaryFile(delete=False, prefix="msm_update_", suffix=".exe") as tmp:
                    temp_path = tmp.name
                dest = Path(temp_path)

                UIUtils.call_on_ui(
                    parent,
                    lambda: UIUtils.show_info(
                        "下載中",
                        "正在下載安裝檔，請稍候...",
                        parent=parent,
                        topmost=True,
                    ),
                )
                if HTTPUtils.download_file(download_url, str(dest)):
                    # 下載完成後嘗試驗證 checksum（若有提供）
                    try:
                        chk = _fetch_checksum_for_asset(latest, asset.get("name") or "")
                        if chk:
                            alg, hexsum = chk
                            ok = _verify_file_checksum(dest, alg, hexsum)
                            if not ok:
                                logger.error(f"安裝程式 checksum 驗證失敗: {asset.get('name')} ({alg})")
                                try:
                                    dest.unlink(missing_ok=True)
                                except Exception as e:
                                    logger.error(f"刪除暫存檔案失敗: {e}")
                                UIUtils.call_on_ui(
                                    parent,
                                    lambda: UIUtils.show_error(
                                        "驗證失敗",
                                        "安裝程式的 checksum 驗證失敗，已取消下載以避免損壞系統。",
                                        parent=parent,
                                        topmost=True,
                                    ),
                                )
                                return
                            logger.info(f"安裝程式 checksum 驗證通過: {asset.get('name')} ({alg})")
                        else:
                            logger.debug("未找到安裝程式 checksum，將略過驗證")
                    except Exception as e:
                        logger.exception(f"在安裝程式 checksum 驗證流程發生錯誤，將中止更新以避免風險: {e}")
                        UIUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error(
                                "驗證錯誤",
                                "在驗證安裝程式時發生錯誤，停止更新以避免風險。",
                                parent=parent,
                                topmost=True,
                            ),
                        )
                        return

                    UIUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.show_info(
                            "下載完成",
                            "將啟動安裝程式進行更新。\n程式將在 3 秒後關閉，請依安裝程式指示操作。",
                            parent=parent,
                            topmost=True,
                        ),
                    )

                    # 啟動安裝程式
                    UpdateChecker._launch_installer(dest)
                    logger.info("安裝程式已啟動，準備關閉當前程式")

                    # 關閉當前程式以避免檔案佔用導致安裝/解除安裝卡住
                    def _exit_for_installer() -> None:
                        try:
                            if parent is not None and hasattr(parent, "after") and hasattr(parent, "winfo_exists"):

                                def _close():
                                    try:
                                        if parent.winfo_exists():
                                            parent.quit()
                                            parent.destroy()
                                    except Exception as e:
                                        logger.exception(f"關閉視窗失敗: {e}")
                                    finally:
                                        sys.exit(0)

                                parent.after(100, _close)
                                return
                        except Exception as e:
                            logger.debug(f"安排視窗關閉時發生錯誤: {e}")
                        sys.exit(0)

                    time.sleep(3)
                    _exit_for_installer()
                else:
                    UIUtils.call_on_ui(
                        parent,
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
                UIUtils.call_on_ui(
                    parent,
                    lambda: UIUtils.show_error(
                        "更新檢查失敗",
                        f"無法完成更新檢查或下載：{error_msg}",
                        parent=parent,
                        topmost=True,
                    ),
                )

        UIUtils.run_async(_work)
