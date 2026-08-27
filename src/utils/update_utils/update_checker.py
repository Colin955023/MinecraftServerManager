"""
應用程式更新檢查器模組
提供 GitHub Release 版本檢查與自動下載安裝功能
"""

from __future__ import annotations

import html
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

from PySide6 import QtWidgets

from src.utils import (
    HashUtils,
    HTTPClient,
    RuntimePaths,
    SubprocessUtils,
    UIUtils,
    UpdateParsing,
    atomic_write_text,
    get_logger,
    invoke_later,
    is_qobject_alive,
    run_on_ui_thread,
)

logger = get_logger().bind(component="UpdateChecker")


class UpdateChecker:
    """集中處理 GitHub Releases 更新檢查與安裝流程"""

    REPLACE_RETRY_LIMIT = 120

    @staticmethod
    def _apply_update(new_exe_path: Path, parent=None) -> bool:
        """套用更新：建立並執行用來覆寫當前執行檔的批次腳本"""
        try:
            current_exe = Path(sys.executable)
            if not current_exe.name.lower().endswith(".exe"):
                logger.error("目前環境非打包之執行檔，無法進行自我替換更新")
                return False

            resolved_path = new_exe_path.resolve(strict=True)
            if resolved_path.is_file():
                confirm = run_on_ui_thread(
                    lambda: UIUtils.ask_yes_no_cancel(
                        "套用更新",
                        "即將關閉程式並套用更新\n\n是否確定要執行？",
                        parent=parent,
                        show_cancel=False,
                    ),
                )
                if not confirm:
                    logger.info("使用者取消套用更新")
                    return False

                bat_script_path = resolved_path.with_suffix(".update.bat")
                bat_content = f"""@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "retries=0"
timeout /t 2 /nobreak >nul
:loop
move /Y "{resolved_path}" "{current_exe}" >nul 2>nul
if not errorlevel 1 goto success
set /a retries+=1 >nul
if %retries% GEQ {UpdateChecker.REPLACE_RETRY_LIMIT} goto failed
timeout /t 1 /nobreak >nul
goto loop
:success
start "" "{current_exe}"
del "%~f0"
exit /b 0
:failed
del /Q "{resolved_path}" >nul 2>nul
del "%~f0"
exit /b 1
"""
                if not atomic_write_text(bat_script_path, bat_content, encoding="utf-8", newline="\r\n"):
                    logger.error(f"無法原子建立更新腳本：{bat_script_path}")
                    return False

                process = SubprocessUtils.popen_detached([str(bat_script_path)])
                time.sleep(0.5)
                returncode = process.poll()
                if returncode is not None and returncode != 0:
                    logger.error(f"更新腳本啟動失敗，結束代碼：{returncode}")
                    return False

                logger.info(f"已啟動更新腳本（PID: {process.pid}）: {bat_script_path}")
                return True
            logger.error(f"新執行檔不存在或不是檔案：{resolved_path}")
        except Exception as e:
            logger.exception(f"套用更新失敗: {e}")
        return False

    @staticmethod
    def _exit(parent, delay_ms: int = 100) -> None:
        """關閉應用程式"""
        try:

            def _close():
                try:
                    if parent is not None and is_qobject_alive(parent):
                        parent.close()
                except Exception as e:
                    logger.exception(f"關閉視窗失敗: {e}")
                finally:
                    app = QtWidgets.QApplication.instance()
                    if app is not None:
                        app.quit()
                    else:
                        sys.exit(0)

            if parent is not None and is_qobject_alive(parent):
                invoke_later(max(0, int(delay_ms)), _close, parent=parent)
                return
        except Exception as e:
            logger.debug(f"安排視窗關閉時發生錯誤: {e}")
        sys.exit(0)

    @staticmethod
    def _clean_release_notes(body: str) -> str:
        """
        清理並篩選釋出說明，過濾開發者資訊與過長內容
        僅保留: 新增功能、修改、刪除、最佳化等使用者相關資訊
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
            if "new contributors" in l_lower or "full changelog" in l_lower:
                ignoring = True
                if "full changelog" in l_lower:
                    break
                continue
            if ignoring:
                if l_strip.startswith("#"):
                    ignoring = False
                else:
                    continue
            clean_line = re.sub("\\s+by\\s+@[\\w\\-]+", "", line)
            clean_line = re.sub("\\s+in\\s+https://\\S+", "", clean_line)
            if not clean_line.strip():
                continue
            kept_lines.append(clean_line)
        text = "\n".join(kept_lines)
        decoded = UpdateChecker._markdown_to_safe_text(text)
        final_lines = [x for x in decoded.splitlines() if x.strip()]
        if len(final_lines) > 15:
            final_lines = final_lines[:15]
            final_lines.append("... (完整內容請查看發行頁面)")
        return "\n".join(final_lines)

    @staticmethod
    def _markdown_to_safe_text(text: str) -> str:
        """將遠端 Markdown 轉為純文字，避免引入 HTML 渲染面"""
        if not text:
            return ""
        safe_text = re.sub(r"```[^\n]*\n?(.*?)```", r"\1", text, flags=re.DOTALL)
        safe_text = re.sub(r"`([^`]*)`", r"\1", safe_text)
        safe_text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", safe_text)
        safe_text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", safe_text)
        safe_text = re.sub(r"<[^>]+>", "", safe_text)
        safe_text = re.sub(r"^\s{0,3}#{1,6}\s*", "", safe_text, flags=re.MULTILINE)
        safe_text = re.sub(r"^\s{0,3}>\s?", "", safe_text, flags=re.MULTILINE)
        safe_text = re.sub(r"^\s*[-*+]\s+", "- ", safe_text, flags=re.MULTILINE)
        safe_text = re.sub(r"^\s*\d+[.)]\s+", "- ", safe_text, flags=re.MULTILINE)
        safe_text = re.sub(r"[*_~]{1,3}", "", safe_text)
        return html.unescape(safe_text)

    @staticmethod
    def check_and_prompt_update(
        current_version: str,
        owner: str,
        repo: str,
        show_up_to_date_message: bool = True,
        parent=None,
        *,
        work_scope,
    ) -> None:
        """
        檢查最新版本並在需要時提示使用者進行更新

        Args:
            current_version: 目前版本字串
            owner: GitHub repository owner
            repo: GitHub repository 名稱
            show_up_to_date_message: 是否在已是最新版本時顯示提示
            parent: 父視窗物件
            work_scope: 負責提交與追蹤更新工作的 UIWorkScope
        """

        def _work() -> None:
            temp_files_to_cleanup: list[Path] = []

            def _cleanup_temp_files(temp_files: list[Path]) -> None:
                """清理所有下載的暫存檔案"""
                for temp_path in temp_files:
                    try:
                        if temp_path.exists():
                            if temp_path.is_file():
                                temp_path.unlink(missing_ok=True)
                                logger.debug(f"已刪除暫存檔案: {temp_path}")
                            elif temp_path.is_dir():
                                shutil.rmtree(temp_path, ignore_errors=True)
                                logger.debug(f"已刪除暫存目錄: {temp_path}")
                    except Exception as e:
                        logger.debug(f"清理暫存檔案時發生錯誤 {temp_path}: {e}")

            def _handle_checksum_mismatch(asset_name: str, algorithm: str) -> None:
                """統一處理下載檔案雜湊驗證失敗"""
                algorithm_label = algorithm.upper()
                logger.error(f"[驗證失敗] {algorithm_label} 不符合！檔案: {asset_name}")
                run_on_ui_thread(
                    lambda: UIUtils.show_message(
                        "檔案雜湊驗證失敗",
                        f"下載的檔案 {algorithm_label} 驗證失敗！\n\n可能原因：\n• 下載過程中檔案損壞\n• 檔案被惡意竄改\n• 網路傳輸錯誤\n\n為了您的安全：\n- 已立即刪除下載的檔案\n- 更新已取消\n\n請稍後重試，或手動從 GitHub 下載",
                        parent=parent,
                        message_level="error",
                    ),
                )
                _cleanup_temp_files(temp_files_to_cleanup)

            try:
                logger.info(f"開始檢查更新... (目前版本: {current_version})")
                include_prerelease = not RuntimePaths.is_packaged()
                latest = UpdateParsing.get_latest_release(owner, repo, include_prerelease=include_prerelease)
                if not latest:
                    logger.info("無法從 GitHub 取得最新版本資訊")
                    if show_up_to_date_message:
                        run_on_ui_thread(
                            lambda: UIUtils.show_message(
                                "檢查更新",
                                "無法取得最新版本資訊，或沒有可用的正式發布版本",
                                parent=parent,
                                message_level="info",
                            ),
                        )
                    return
                latest_tag = latest.get("tag_name") or ""
                latest_ver = UpdateParsing.parse_version(latest_tag)
                current_ver = UpdateParsing.parse_version(current_version)
                if not latest_ver or not current_ver:
                    logger.warning("無法解析版本號，略過更新檢查")
                    return
                logger.info(f"版本檢查: 目前版本={current_ver}, 最新版本={latest_ver} ({latest_tag})")
                if latest_ver <= current_ver:
                    logger.info("目前已是最新版本")
                    if show_up_to_date_message:
                        run_on_ui_thread(
                            lambda: UIUtils.show_message(
                                "檢查更新",
                                f"目前版本 {current_version} 已是最新版本，無須更新。",
                                parent=parent,
                                message_level="info",
                            ),
                        )
                    return
                name = latest.get("name") or latest_tag
                logger.info(f"發現新版本: {name}")
                body = latest.get("body") or "(無釋出說明)"
                rendered = UpdateChecker._clean_release_notes(body)
                html_url = latest.get("html_url")
                msg = f"發現新版本：{name}\n目前版本：{current_version}\n\n釋出說明：\n{rendered}\n\n是否下載並安裝？"
                result = run_on_ui_thread(
                    lambda: UIUtils.ask_yes_no_cancel("更新可用", msg, parent=parent, show_cancel=False),
                )
                if not result:
                    return
                logger.info("使用者確認更新，準備下載...")
                asset, _ = UpdateParsing.select_update_asset(latest)
                if not asset:
                    invoke_later(
                        0,
                        lambda: UIUtils.show_message(
                            "無安裝檔",
                            "找不到可用的安裝檔（.exe）。將開啟發行頁面，請手動下載。",
                            parent=parent,
                            message_level="info",
                        ),
                        parent=parent,
                    )
                    if html_url:
                        UIUtils.open_external(html_url)
                    return
                download_url = asset.get("browser_download_url")
                if not download_url:
                    run_on_ui_thread(
                        lambda: UIUtils.show_message(
                            "無下載連結",
                            "選取的安裝檔缺少下載連結。將開啟發行頁面，請手動下載最新版本。",
                            parent=parent,
                            message_level="error",
                        ),
                    )
                    if html_url:
                        UIUtils.open_external(html_url)
                    return

                def _fetch_checksum_for_asset(release: dict) -> tuple[str, str] | None:
                    """
                    只從 GitHub release asset digest 取得 checksum

                    若 asset 未提供 digest，直接回傳 None
                    """
                    try:
                        asset_obj = release.get("_selected_asset") or {}
                        if asset_obj:
                            digest = UpdateParsing.parse_asset_digest(asset_obj)
                            if digest:
                                logger.info(
                                    f"[digest 查詢成功] 已從 GitHub asset digest 取得 checksum（{digest[0]}），無需額外下載"
                                )
                                return digest
                        logger.warning("[digest 查詢失敗] GitHub asset digest 不存在或無法解析，已拒絕使用未驗證檔案")
                        return None
                    except Exception as e:
                        logger.exception(f"[digest 查詢錯誤] 在查詢過程中發生未預期的錯誤: {e}")
                    return None

                def _verify_file_checksum(path: Path, algorithm: str, hex_checksum: str) -> bool:
                    checksum = HashUtils.compute_file_hash_sync(path, algorithm)
                    return checksum == hex_checksum.lower() if checksum else False

                logger.info("[安全檢查] 正在線上查詢安裝程式的 digest 驗證資訊...")
                try:
                    latest["_selected_asset"] = asset
                    chk = _fetch_checksum_for_asset(latest)
                    if not chk:
                        logger.error("[安全檢查失敗] 未找到可用 digest，拒絕下載未經驗證的檔案")
                        run_on_ui_thread(
                            lambda: UIUtils.show_message(
                                "缺少 digest 驗證資訊",
                                "無法從 GitHub Release 中取得此安裝程式的 SHA-256 digest 驗證資訊\n\n為了您的系統安全：\n- 將不會下載任何檔案\n- 更新已取消\n\n建議聯絡開發者確認 Release 是否包含 digest 資訊",
                                parent=parent,
                                message_level="error",
                            ),
                        )
                        _cleanup_temp_files(temp_files_to_cleanup)
                        return
                    alg, expected_checksum = chk
                    logger.info(f"[安全檢查通過] 已取得 digest 驗證資訊 ({alg}: {expected_checksum[:16]}...)")
                    logger.info("[開始下載] 確認有 digest 可驗證，現在開始安全下載安裝程式")
                except Exception:
                    logger.exception("[安全檢查錯誤] 在查詢 digest 時發生錯誤，為避免風險將中止更新")
                    run_on_ui_thread(
                        lambda: UIUtils.show_message(
                            "安全驗證錯誤",
                            "在線上查詢 digest 驗證資訊時發生錯誤\n\n為了您的系統安全：\n- 將不會下載任何檔案\n- 更新已取消",
                            parent=parent,
                            message_level="error",
                        ),
                    )
                    _cleanup_temp_files(temp_files_to_cleanup)
                    return
                logger.info("[下載階段] 開始下載安裝程式...")
                with tempfile.NamedTemporaryFile(delete=False, prefix="msm_update_", suffix=".exe") as tmp:
                    temp_path = tmp.name
                dest = Path(temp_path)
                temp_files_to_cleanup.append(dest)
                download_result = HTTPClient.download_file(download_url, str(dest))
                if download_result.success:
                    logger.info(f"[驗證階段] 正在計算並驗證下載檔案的 {alg.upper()}...")
                    logger.info(f"[驗證階段] 預期 {alg.upper()}: {expected_checksum}")
                    ok = _verify_file_checksum(dest, alg, expected_checksum)
                    if not ok:
                        _handle_checksum_mismatch(asset.get("name") or "unknown", alg)
                        return
                    logger.info(f"[驗證通過] {alg.upper()} 驗證成功：{asset.get('name')}")
                    installer_started = UpdateChecker._apply_update(dest, parent=parent)
                    if not installer_started:
                        logger.info("更新未套用，更新流程已取消")
                        _cleanup_temp_files(temp_files_to_cleanup)
                        run_on_ui_thread(
                            lambda: UIUtils.show_message(
                                "更新已取消",
                                "套用更新已取消，程式將繼續執行。請稍後重試或手動從 GitHub Releases 下載。",
                                parent=parent,
                                message_level="info",
                            ),
                        )
                        return
                    logger.info("更新腳本已啟動（獨立行程）")
                    if dest in temp_files_to_cleanup:
                        temp_files_to_cleanup.remove(dest)
                    _cleanup_temp_files(temp_files_to_cleanup)
                    run_on_ui_thread(
                        lambda: UIUtils.show_message(
                            "更新準備就緒",
                            "更新腳本已啟動\n\n程式即將自動關閉並在背景替換為新版本\n替換完成後將自動重新啟動",
                            parent=parent,
                            message_level="info",
                        ),
                    )
                    time.sleep(2)
                    logger.info("準備關閉當前程式以完成更新")
                else:
                    failure_message = download_result.message or "無法下載安裝程式"
                    logger.warning(f"[下載失敗] {failure_message}")
                    run_on_ui_thread(
                        lambda: UIUtils.show_message("下載失敗", failure_message, parent=parent, message_level="error"),
                    )
                    _cleanup_temp_files(temp_files_to_cleanup)
                    return
                UpdateChecker._exit(parent)
            except Exception as e:
                logger.exception(f"更新檢查失敗: {e}")
                error_msg = str(e)
                run_on_ui_thread(
                    lambda: UIUtils.show_message(
                        "更新檢查失敗", f"無法完成更新檢查或下載：{error_msg}", parent=parent, message_level="error"
                    ),
                )
                _cleanup_temp_files(temp_files_to_cleanup)

        work_scope.submit(_work, key="app_update_check", replace=True)


__all__ = ["UpdateChecker"]
