"""應用程式更新檢查器模組
提供 GitHub Release 版本檢查與自動下載安裝功能
"""

import html as _html
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, TypeVar

from packaging.version import Version

from .. import HTTPUtils, PathUtils, RuntimePaths, SubprocessUtils, UpdateParsing, get_logger
from ..runtime_utils.background_task import run_in_background
from ..ui_support.qt_runtime import invoke_later, is_qobject_alive

logger = get_logger().bind(component="UpdateChecker")
_UpdateResultT = TypeVar("_UpdateResultT")


class UpdateCheckerInteraction(Protocol):
    """更新流程需要的 UI 與排程互動介面。"""

    def run_async(self, work: Callable[[], None]) -> None:
        """在背景執行更新檢查工作。"""

    def call_on_ui(self, parent: Any, callback: Callable[[], _UpdateResultT]) -> _UpdateResultT:
        """在 UI 執行緒執行 callback 並回傳結果。

        Args:
            parent: 排程用 UI parent。
            callback: 要執行的函式。

        Returns:
            callback 的回傳值。
        """

    def schedule_debounce(
        self, widget: Any, job_attr: str, delay_ms: int, callback: Callable[[], Any], *, owner: Any | None = None
    ) -> Any:
        """安排延遲 UI 工作。

        Args:
            widget: 排程所在 widget。
            job_attr: 儲存 job id 的屬性名稱。
            delay_ms: 延遲毫秒數。
            callback: 到期後執行的函式。
            owner: 可選的 job holder。

        Returns:
            底層排程器回傳值。
        """

    def ask_yes_no_cancel(self, title: str, message: str, **kwargs: Any) -> bool | None:
        """詢問使用者是否同意更新流程。

        Args:
            title: 對話框標題。
            message: 對話框訊息。
            **kwargs: UI adapter 選項。

        Returns:
            使用者選擇；取消或無法判斷時回傳 None。
        """

    def show_info(self, title: str, message: str, **kwargs: Any) -> None:
        """顯示資訊訊息。

        Args:
            title: 訊息標題。
            message: 訊息內容。
            **kwargs: UI adapter 選項。
        """

    def show_error(self, title: str, message: str, **kwargs: Any) -> None:
        """顯示錯誤訊息。

        Args:
            title: 訊息標題。
            message: 訊息內容。
            **kwargs: UI adapter 選項。
        """

    def open_external(self, target: str) -> None:
        """開啟外部連結或路徑。

        Args:
            target: URL 或檔案路徑。
        """


class _DirectUpdateCheckerInteraction:
    """沒有 UI adapter 時使用的安全後備互動實作。"""

    def run_async(self, work: Callable[[], None]) -> None:
        run_in_background(work)

    def call_on_ui(self, parent: Any, callback: Callable[[], _UpdateResultT]) -> _UpdateResultT:
        _ = parent
        return callback()

    def schedule_debounce(
        self, widget: Any, job_attr: str, delay_ms: int, callback: Callable[[], Any], *, owner: Any | None = None
    ) -> Any:
        _ = (job_attr, owner)
        if widget is not None and hasattr(widget, "schedule"):
            try:
                alive = False
                if hasattr(widget, "is_alive") and callable(widget.is_alive):
                    alive = bool(widget.is_alive())
                else:
                    alive = is_qobject_alive(widget)
                if alive:
                    return widget.schedule(max(0, int(delay_ms)), callback)
            except Exception:
                logger.debug("使用 widget.schedule 安排工作失敗，將回退到 QTimer", exc_info=True)
        parent = widget if is_qobject_alive(widget) else None
        return invoke_later(max(0, int(delay_ms)), callback, parent=parent)

    def ask_yes_no_cancel(self, title: str, message: str, **kwargs: Any) -> bool | None:
        _ = (message, kwargs)
        logger.info(f"略過需要 UI 確認的更新動作：{title}")
        return False

    def show_info(self, title: str, message: str, **kwargs: Any) -> None:
        _ = kwargs
        logger.info(f"{title}: {message}")

    def show_error(self, title: str, message: str, **kwargs: Any) -> None:
        _ = kwargs
        logger.error(f"{title}: {message}")

    def open_external(self, target: str) -> None:
        logger.info(f"略過開啟外部連結：{target}")


class UpdateChecker:
    """集中處理 GitHub Releases 更新檢查與安裝流程。"""

    @staticmethod
    def _parse_version(version_str: str | None) -> Version | None:
        """解析版本字串為 PEP 440 Version 物件。"""
        return UpdateParsing.parse_version(version_str)

    @staticmethod
    def _get_latest_release(owner: str, repo: str, include_prerelease: bool = False) -> dict | None:
        return UpdateParsing.get_latest_release(owner, repo, include_prerelease=include_prerelease)

    @staticmethod
    def _is_development_environment() -> bool:
        """僅在開發環境允許偵測 prerelease。"""
        return not RuntimePaths.is_packaged()

    @staticmethod
    def _choose_installer_asset(release: dict) -> dict:
        return UpdateParsing.choose_installer_asset(release)

    @staticmethod
    def _select_update_asset(release: dict) -> tuple[dict, str]:
        return UpdateParsing.select_update_asset(release)

    @staticmethod
    def _build_installer_launch_args(installer_path: Path) -> list[str]:
        args = [str(installer_path)]
        if RuntimePaths.is_portable_mode():
            args.extend(["/MSMPortable=1", f"/DIR={RuntimePaths.get_portable_base_dir()}"])
        else:
            args.append("/MSMPortable=0")
        return args

    @staticmethod
    def _launch_installer(
        installer_path: Path, parent=None, interaction: UpdateCheckerInteraction | None = None
    ) -> bool:
        """啟動安裝程式

        Args:
            installer_path: 安裝程式檔案路徑
            parent: 父視窗物件，用於在主執行緒顯示 UI 對話框
            interaction: 更新流程互動介面。

        Returns:
            成功啟動安裝程式時回傳 True，取消或啟動失敗時回傳 False。
        """
        installer_interaction: UpdateCheckerInteraction = interaction or _DirectUpdateCheckerInteraction()
        try:
            try:
                temp_dir = Path(tempfile.gettempdir()).resolve(strict=True)
                resolved_path = installer_path.resolve(strict=True)
            except FileNotFoundError as e:
                logger.error(f"安裝程式路徑解析失敗：{installer_path}，錯誤：{e}")
                return False
            except Exception as e:
                logger.error(f"解析安裝程式路徑時發生未預期錯誤：{installer_path}，錯誤：{e}")
                return False
            if not PathUtils.is_path_within(temp_dir, resolved_path, strict=True):
                logger.error(f"安裝程式路徑不在允許的暫存目錄中：{resolved_path}")
                return False
            if resolved_path.is_file():
                confirm = installer_interaction.call_on_ui(
                    parent,
                    lambda: installer_interaction.ask_yes_no_cancel(
                        "執行安裝程式",
                        f"即將執行安裝程式：\n{resolved_path}\n\n是否確定要執行？",
                        parent=parent,
                        show_cancel=False,
                        topmost=True,
                    ),
                )
                if not confirm:
                    logger.info(f"使用者取消執行安裝程式：{resolved_path}")
                    return False
                process = SubprocessUtils.popen_detached(UpdateChecker._build_installer_launch_args(resolved_path))
                time.sleep(0.5)
                returncode = process.poll()
                if returncode is not None and returncode != 0:
                    logger.error(f"安裝程式啟動失敗，退出碼：{returncode}")
                    return False
                if returncode is not None:
                    logger.debug(f"安裝程式進程已退出（可能啟動了子進程），退出碼：{returncode}")
                logger.info(f"已啟動安裝程式（PID: {process.pid}）: {resolved_path}")
                return True
            logger.error(f"安裝程式不存在或不是檔案：{resolved_path}")
        except Exception as e:
            logger.exception(f"安裝程式啟動失敗: {e}")
        return False

    @staticmethod
    def _graceful_exit(parent, delay_ms: int = 100, interaction: UpdateCheckerInteraction | None = None) -> None:
        """優雅地關閉應用程式

        Args:
            parent: 父視窗物件
            delay_ms: 延遲關閉的毫秒數
            interaction: 更新流程互動介面。
        """
        exit_interaction: UpdateCheckerInteraction = interaction or _DirectUpdateCheckerInteraction()
        try:
            if parent is not None and hasattr(parent, "schedule") and hasattr(parent, "is_alive") and parent.is_alive():

                def _close():
                    try:
                        if parent.is_alive():
                            parent.quit()
                            parent.destroy()
                    except Exception as e:
                        logger.exception(f"關閉視窗失敗: {e}")
                    finally:
                        sys.exit(0)

                exit_interaction.schedule_debounce(
                    parent, "_update_graceful_exit_job", max(0, int(delay_ms)), _close, owner=parent
                )
                return
        except Exception as e:
            logger.debug(f"安排視窗關閉時發生錯誤: {e}")
        sys.exit(0)

    @staticmethod
    def _clean_release_notes(body: str) -> str:
        """
        清理並篩選釋出說明，過濾開發者資訊與過長內容
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
        """將遠端 Markdown 轉為純文字，避免引入 HTML 渲染面。"""
        if not text:
            return ""
        safe_text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        safe_text = re.sub(r"`([^`]*)`", r"\1", safe_text)
        safe_text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", safe_text)
        safe_text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", safe_text)
        safe_text = re.sub(r"<[^>]+>", "", safe_text)
        safe_text = re.sub(r"^\s{0,3}#{1,6}\s*", "", safe_text, flags=re.MULTILINE)
        safe_text = re.sub(r"^\s{0,3}>\s?", "", safe_text, flags=re.MULTILINE)
        safe_text = re.sub(r"^\s*[-*+]\s+", "- ", safe_text, flags=re.MULTILINE)
        safe_text = re.sub(r"^\s*\d+[.)]\s+", "- ", safe_text, flags=re.MULTILINE)
        safe_text = re.sub(r"[*_~]{1,3}", "", safe_text)
        return _html.unescape(safe_text)

    @staticmethod
    def check_and_prompt_update(
        current_version: str,
        owner: str,
        repo: str,
        show_up_to_date_message: bool = True,
        parent=None,
        interaction: UpdateCheckerInteraction | None = None,
    ) -> None:
        """檢查最新版本並在需要時提示使用者進行更新。

        Args:
            current_version: 目前版本字串。
            owner: GitHub repository owner。
            repo: GitHub repository 名稱。
            show_up_to_date_message: 是否在已是最新版本時顯示提示。
            parent: 父視窗物件。
            interaction: UI 層注入的互動介面；未提供時只記錄訊息並略過需要確認的動作。
        """
        update_interaction: UpdateCheckerInteraction = interaction or _DirectUpdateCheckerInteraction()

        class TaskUtils:
            """將舊呼叫點轉接到注入的更新互動介面。"""

            @staticmethod
            def call_on_ui(parent_obj: Any, callback: Callable[[], _UpdateResultT]) -> _UpdateResultT:
                return update_interaction.call_on_ui(parent_obj, callback)

            @staticmethod
            def run_async(work: Callable[[], None]) -> None:
                update_interaction.run_async(work)

        class UIUtils:
            """將舊 UI 呼叫點轉接到注入的更新互動介面。"""

            @staticmethod
            def schedule_debounce(
                widget: Any,
                job_attr: str,
                delay_ms: int,
                callback: Callable[[], Any],
                *,
                owner: Any | None = None,
            ) -> Any:
                return update_interaction.schedule_debounce(widget, job_attr, delay_ms, callback, owner=owner)

            @staticmethod
            def ask_yes_no_cancel(title: str, message: str, **kwargs: Any) -> bool | None:
                return update_interaction.ask_yes_no_cancel(title, message, **kwargs)

            @staticmethod
            def show_info(title: str, message: str, **kwargs: Any) -> None:
                update_interaction.show_info(title, message, **kwargs)

            @staticmethod
            def show_error(title: str, message: str, **kwargs: Any) -> None:
                update_interaction.show_error(title, message, **kwargs)

            @staticmethod
            def open_external(target: str) -> None:
                update_interaction.open_external(target)

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
                """統一處理下載檔案雜湊驗證失敗。"""
                algorithm_label = algorithm.upper()
                logger.error(f"[驗證失敗] {algorithm_label} 不符合！檔案: {asset_name}")
                TaskUtils.call_on_ui(
                    parent,
                    lambda: UIUtils.show_error(
                        "檔案雜湊驗證失敗",
                        f"下載的檔案 {algorithm_label} 驗證失敗！\n\n可能原因：\n• 下載過程中檔案損壞\n• 檔案被惡意篡改\n• 網路傳輸錯誤\n\n為了您的安全：\n- 已立即刪除下載的檔案\n- 更新已取消\n\n請稍後重試，或手動從 GitHub 下載。",
                        parent=parent,
                        topmost=True,
                    ),
                )
                _cleanup_temp_files(temp_files_to_cleanup)

            try:
                logger.info(f"開始檢查更新... (目前版本: {current_version})")
                include_prerelease = UpdateChecker._is_development_environment()
                latest = UpdateChecker._get_latest_release(owner, repo, include_prerelease=include_prerelease)
                if not latest:
                    logger.info("無法從 GitHub 取得最新版本資訊")
                    if show_up_to_date_message:
                        TaskUtils.call_on_ui(
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
                if latest_ver <= current_ver:
                    logger.info("目前已是最新版本")
                    if show_up_to_date_message:
                        TaskUtils.call_on_ui(
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
                rendered = UpdateChecker._clean_release_notes(body)
                html_url = latest.get("html_url")
                msg = f"發現新版本：{name}\n目前版本：{current_version}\n\n釋出說明：\n{rendered}\n\n是否下載並安裝？"
                result = TaskUtils.call_on_ui(
                    parent,
                    lambda: UIUtils.ask_yes_no_cancel("更新可用", msg, parent=parent, show_cancel=False, topmost=True),
                )
                if not result:
                    return
                logger.info("使用者確認更新，準備下載...")
                asset, _ = UpdateChecker._select_update_asset(latest)
                if not asset:
                    TaskUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.show_info(
                            "無安裝檔",
                            "找不到可用的安裝檔（.exe）。將開啟發行頁面，請手動下載。",
                            parent=parent,
                            topmost=True,
                        ),
                    )
                    if html_url:
                        UIUtils.open_external(html_url)
                    return
                download_url = asset.get("browser_download_url")
                if not download_url:
                    TaskUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.show_error(
                            "無下載連結",
                            "選取的安裝檔缺少下載連結。將開啟發行頁面，請手動下載最新版本。",
                            parent=parent,
                            topmost=True,
                        ),
                    )
                    if html_url:
                        UIUtils.open_external(html_url)
                    return

                def _parse_asset_digest(asset_dict: dict) -> tuple[str, str] | None:
                    return UpdateParsing.parse_asset_digest(asset_dict)

                def _fetch_checksum_for_asset(release: dict) -> tuple[str, str] | None:
                    """
                    只從 GitHub release asset digest 取得 checksum。

                    若 asset 未提供 digest，直接回傳 None。
                    """
                    try:
                        asset_obj = release.get("_selected_asset") or {}
                        if asset_obj:
                            digest = _parse_asset_digest(asset_obj)
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
                    checksum = PathUtils.calculate_checksum(path, algorithm)
                    return checksum == hex_checksum.lower() if checksum else False

                logger.info("[安全檢查] 正在線上查詢安裝程式的 digest 驗證資訊...")
                try:
                    latest["_selected_asset"] = asset
                    chk = _fetch_checksum_for_asset(latest)
                    if not chk:
                        logger.error("[安全檢查失敗] 未找到可用 digest，拒絕下載未經驗證的檔案")
                        TaskUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error(
                                "缺少 digest 驗證資訊",
                                "無法從 GitHub Release 中取得此安裝程式的 SHA-256 digest 驗證資訊。\n\n為了您的系統安全：\n- 將不會下載任何檔案\n- 更新已取消\n\n建議聯絡開發者確認 Release 是否包含 digest 資訊。",
                                parent=parent,
                                topmost=True,
                            ),
                        )
                        _cleanup_temp_files(temp_files_to_cleanup)
                        return
                    alg, expected_checksum = chk
                    logger.info(f"[安全檢查通過] 已取得 digest 驗證資訊 ({alg}: {expected_checksum[:16]}...)")
                    logger.info("[開始下載] 確認有 digest 可驗證，現在開始安全下載安裝程式")
                except Exception:
                    logger.exception("[安全檢查錯誤] 在查詢 digest 時發生錯誤，為避免風險將中止更新")
                    TaskUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.show_error(
                            "安全驗證錯誤",
                            "在線上查詢 digest 驗證資訊時發生錯誤。\n\n為了您的系統安全：\n- 將不會下載任何檔案\n- 更新已取消",
                            parent=parent,
                            topmost=True,
                        ),
                    )
                    _cleanup_temp_files(temp_files_to_cleanup)
                    return
                logger.info("[下載階段] 開始下載安裝程式...")
                with tempfile.NamedTemporaryFile(delete=False, prefix="msm_update_", suffix=".exe") as tmp:
                    temp_path = tmp.name
                dest = Path(temp_path)
                temp_files_to_cleanup.append(dest)
                download_failure_reason = ""

                def _capture_download_failure(message: str) -> None:
                    nonlocal download_failure_reason
                    download_failure_reason = message

                if HTTPUtils.download_file(
                    download_url,
                    str(dest),
                    failure_message_callback=_capture_download_failure,
                ):
                    logger.info(f"[驗證階段] 正在計算並驗證下載檔案的 {alg.upper()}...")
                    logger.info(f"[驗證階段] 預期 {alg.upper()}: {expected_checksum}")
                    ok = _verify_file_checksum(dest, alg, expected_checksum)
                    if not ok:
                        _handle_checksum_mismatch(asset.get("name") or "unknown", alg)
                        return
                    logger.info(f"[驗證通過] {alg.upper()} 驗證成功：{asset.get('name')}")
                    installer_started = UpdateChecker._launch_installer(
                        dest, parent=parent, interaction=update_interaction
                    )
                    if not installer_started:
                        logger.info("安裝程式未啟動，更新流程已取消")
                        _cleanup_temp_files(temp_files_to_cleanup)
                        TaskUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_info(
                                "更新已取消",
                                "安裝程式未啟動，程式將繼續執行。請稍後重試或手動從 GitHub Releases 下載。",
                                parent=parent,
                                topmost=True,
                            ),
                        )
                        return
                    logger.info("安裝程式已啟動（獨立進程）")
                    if dest in temp_files_to_cleanup:
                        temp_files_to_cleanup.remove(dest)
                    _cleanup_temp_files(temp_files_to_cleanup)
                    TaskUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.show_info(
                            "更新準備就緒",
                            "安裝程式已啟動。\n\n程式將在關閉此訊息後結束。\n請依安裝程式指示完成更新。",
                            parent=parent,
                            topmost=True,
                        ),
                    )
                    time.sleep(2)
                    logger.info("準備關閉當前程式以完成更新")
                else:
                    failure_message = download_failure_reason or "無法下載安裝程式。"
                    logger.warning(f"[下載失敗] {failure_message}")
                    TaskUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.show_error(
                            "下載失敗",
                            failure_message,
                            parent=parent,
                            topmost=True,
                        ),
                    )
                    _cleanup_temp_files(temp_files_to_cleanup)
                    return
                UpdateChecker._graceful_exit(parent, interaction=update_interaction)
            except Exception as e:
                logger.exception(f"更新檢查失敗: {e}")
                error_msg = str(e)
                TaskUtils.call_on_ui(
                    parent,
                    lambda: UIUtils.show_error(
                        "更新檢查失敗", f"無法完成更新檢查或下載：{error_msg}", parent=parent, topmost=True
                    ),
                )
                _cleanup_temp_files(temp_files_to_cleanup)

        TaskUtils.run_async(_work)
