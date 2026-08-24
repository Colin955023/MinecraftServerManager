"""執行已確認的 immutable Mod Review handoff"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from contextlib import suppress
from types import SimpleNamespace
from typing import Any

from PySide6.QtWidgets import QWidget

from src.core import ModManager
from src.models import ModStatus
from src.ui import (
    HostBound,
    ProgressDialog,
    ReviewExecutionHandoff,
    ReviewInstallStep,
    build_review_context_stamp,
    describe_context_mismatch,
)
from src.ui import mod_management_logger as logger
from src.utils import (
    ONLINE_INSTALL_NO_ACTIONABLE_MESSAGE,
    CancellationToken,
    UIUtils,
    UIWorkScope,
)


class ModManagementInstallExecutor(HostBound):
    """只負責下載、替換、進度、取消與結果回報"""

    mod_manager: Any
    mod_session: Any
    parent: Any
    ui_queue: Any
    scope: UIWorkScope
    local_mod_list_presenter: Any
    update_status_safe: Callable[..., Any]
    update_progress_safe: Callable[..., Any]
    _refresh_online_queue_button: Callable[..., Any]

    @staticmethod
    def _build_download_kwargs(
        progress_callback: Callable[[int, int], None] | None,
        expected_hash: str | None = None,
        *,
        provider: str | None = "modrinth",
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "progress_callback": progress_callback,
            "provider": str(provider or "modrinth").strip() or "modrinth",
        }
        if str(expected_hash or "").strip():
            kwargs["expected_hash"] = expected_hash
        if cancel_check is not None:
            kwargs["cancel_check"] = cancel_check
        return kwargs

    def _make_step_progress_callback(
        self,
        step_index: int,
        total_steps: int,
        step_label: str = "",
        progress_dialog: ProgressDialog | None = None,
        accept_effect: Callable[[], bool] | None = None,
    ):
        def callback(downloaded: int, total: int) -> None:
            if accept_effect is not None and not accept_effect():
                return
            fraction = downloaded / total if total > 0 else 0.0
            overall = (step_index + fraction) / max(1, total_steps)
            self.update_progress_safe(overall)
            if progress_dialog is not None:
                percent = overall * 100.0
                text = f"{step_label} ({step_index + 1}/{total_steps})"
                progress_dialog.update_progress(percent, text)

        return callback

    def _validate_review_handoff(self, handoff: ReviewExecutionHandoff, *, parent: Any) -> bool:
        manager = self.mod_manager
        current_server = self.mod_session.server
        if not manager or not current_server:
            UIUtils.show_message("無法執行 Review", "目前沒有有效的目標伺服器", parent, message_level="error")
            return False
        try:
            actual_stamp = build_review_context_stamp(current_server, manager.get_mod_list())
        except Exception as exc:
            logger.error("驗證 Review context 失敗: %s", exc)
            UIUtils.show_message(
                "無法驗證 Review",
                "無法重新讀取目標伺服器的 Mod 狀態，請重新建立 Review",
                parent,
                message_level="error",
            )
            return False
        mismatch = describe_context_mismatch(handoff.context_stamp, actual_stamp)
        if not mismatch:
            return True
        logger.info("拒絕過期 Review handoff: %s", mismatch)
        self.update_status_safe(f"Review 已失效：{mismatch}")
        UIUtils.show_message(
            "Review 已失效",
            f"{mismatch}，請關閉目前視窗並重新建立 Review 後再執行",
            parent,
            message_level="warning",
        )
        return False

    def _confirm_review_handoff(
        self,
        handoff: ReviewExecutionHandoff,
        *,
        parent: Any,
        action_label: str,
    ) -> bool:
        if handoff.confirmation_prompt:
            proceed = UIUtils.ask_yes_no_cancel(
                f"確認本次{action_label}內容",
                handoff.confirmation_prompt,
                parent=parent,
                show_cancel=False,
            )
            if proceed is not True:
                self.update_status_safe(f"已取消模組{action_label}執行")
                return False
        if handoff.source_confirmation_prompt:
            logger.warning("偵測到非官方下載來源，進入二次確認流程: action=%s", action_label)
            proceed = UIUtils.ask_yes_no_cancel(
                "非官方來源二次確認",
                handoff.source_confirmation_prompt,
                parent=parent,
                show_cancel=False,
            )
            if proceed is not True:
                self.update_status_safe(f"已取消非官方來源{action_label}")
                return False
        return True

    def _execute_install_step(
        self,
        manager: ModManager,
        step: ReviewInstallStep,
        *,
        step_index: int,
        total_steps: int,
        cancel_check: Callable[[], bool] | None,
        progress_dialog: ProgressDialog | None = None,
        accept_effect: Callable[[], bool] | None = None,
    ) -> bool:
        if accept_effect is not None and not accept_effect():
            return False
        if step.kind in {"dependency", "online_root"}:
            status_text = (
                f"正在安裝必要依賴：{step.project_name}"
                if step.kind == "dependency"
                else f"正在安裝模組：{step.project_name} ({step.version_name or '未知版本'})"
            )
            self.update_status_safe(status_text)
            if progress_dialog is not None:
                pct = (step_index / max(1, total_steps)) * 100.0
                self.ui_queue.put(
                    lambda p=pct, t=f"{status_text} ({step_index + 1}/{total_steps})": progress_dialog.update_progress(
                        p, t
                    )
                )
            installed_path = manager.install_remote_mod_file(
                download_url=step.download_url,
                filename=step.filename,
                **self._build_download_kwargs(
                    self._make_step_progress_callback(
                        step_index, total_steps, status_text, progress_dialog, accept_effect
                    ),
                    step.expected_hash or None,
                    provider=step.provider,
                    cancel_check=cancel_check,
                ),
            )
            return installed_path is not None
        status_text = f"正在更新模組：{step.project_name}"
        self.update_status_safe(status_text)
        if progress_dialog is not None:
            pct = (step_index / max(1, total_steps)) * 100.0
            progress_dialog.update_progress(pct, f"{status_text} ({step_index + 1}/{total_steps})")
        local_mod = SimpleNamespace(
            file_path=step.local_file_path,
            filename=step.local_file_path,
            status=ModStatus.DISABLED if step.local_status == "disabled" else ModStatus.ENABLED,
        )
        updated_path = manager.replace_local_mod_file(
            local_mod,
            step.download_url,
            step.filename,
            **self._build_download_kwargs(
                self._make_step_progress_callback(step_index, total_steps, status_text, progress_dialog, accept_effect),
                step.expected_hash or None,
                provider=step.provider,
                cancel_check=cancel_check,
            ),
        )
        return updated_path is not None

    def _execute_review_handoff_steps(
        self,
        manager: ModManager,
        handoff: ReviewExecutionHandoff,
        *,
        active_token: CancellationToken | None,
        progress_dialog: ProgressDialog | None,
        accept_effect: Callable[[], bool],
        action_label: str,
        on_step_completed: Callable[[ReviewInstallStep], None],
    ) -> bool:
        """以一致的 scope、取消與錯誤語意執行 Review handoff"""
        if not accept_effect() or not self._validate_review_handoff(handoff, parent=self.parent):
            return False
        cancel_check = active_token.is_cancelled if active_token else None
        total_steps = len(handoff.steps)
        for index, step in enumerate(handoff.steps):
            if not accept_effect():
                return False
            if active_token and active_token.is_cancelled():
                self.update_status_safe(f"{action_label}已取消")
                return False
            if not self._execute_install_step(
                manager,
                step,
                step_index=index,
                total_steps=total_steps,
                cancel_check=cancel_check,
                progress_dialog=progress_dialog,
                accept_effect=accept_effect,
            ):
                if not accept_effect():
                    return False
                if active_token and active_token.is_cancelled():
                    self.update_status_safe(f"{action_label}已取消")
                    return False
                raise RuntimeError(f"{step.project_name} {action_label}失敗")
            on_step_completed(step)
        return True

    def _install_pending_online_install_queue(
        self,
        dialog: Any,
        handoff: ReviewExecutionHandoff,
    ) -> None:
        manager = self.mod_manager
        if not manager:
            UIUtils.show_message("錯誤", "模組管理器未初始化", self.parent, message_level="error")
            return
        if handoff.mode != "online_install":
            raise ValueError("線上安裝 executor 收到非線上 Review handoff")
        if not handoff.root_count:
            UIUtils.show_message("無法安裝", ONLINE_INSTALL_NO_ACTIONABLE_MESSAGE, self.parent, message_level="warning")
            return
        if not self._validate_review_handoff(handoff, parent=self.parent):
            return
        if not self._confirm_review_handoff(handoff, parent=self.parent, action_label="安裝"):
            return
        if hasattr(dialog, "accept"):
            dialog.accept()
        elif hasattr(dialog, "close"):
            dialog.close()
        elif hasattr(dialog, "destroy"):
            dialog.destroy()

        self.update_status_safe("正在啟動安裝清單執行...")
        session = self.mod_session
        install_scope = session.begin_install()

        cancel_token_holder = CancellationToken()
        progress_dlg = None
        if isinstance(self.parent, QWidget):
            try:
                progress_dlg = ProgressDialog(self.parent, title="正在安裝模組", show_cancel=True)
                progress_dlg.rejected.connect(cancel_token_holder.cancel)
                progress_dlg.show()
            except Exception as exc:
                logger.debug(f"ProgressDialog 初始化略過: {exc}")

        def _close_progress() -> None:
            if progress_dlg is not None:
                with suppress(Exception):
                    progress_dlg.close()
                    progress_dlg.deleteLater()

        def install_task() -> None:
            active_token = cancel_token_holder
            succeeded_root_keys: set[str] = set()

            def accept_effect():
                return session.is_scope_current(install_scope)

            try:
                if not self._execute_review_handoff_steps(
                    manager,
                    handoff,
                    active_token=active_token,
                    progress_dialog=progress_dlg,
                    accept_effect=accept_effect,
                    action_label="安裝清單",
                    on_step_completed=lambda step: (
                        succeeded_root_keys.add(step.root_key) if step.kind == "online_root" else None
                    ),
                ):
                    self.ui_queue.put(_close_progress)
                    self.ui_queue.put(self.local_mod_list_presenter.load_local_mods)
                    return
                if not session.is_scope_current(install_scope):
                    self.ui_queue.put(_close_progress)
                    return
                session.remove_pending_review_keys(succeeded_root_keys)
                retained = session.pending_online_installs
                self._refresh_online_queue_button()
                self.update_progress_safe(1.0)
                self.update_status_safe(
                    f"已完成 {len(succeeded_root_keys)} 個模組安裝，必要依賴已補裝 {handoff.dependency_count} 個"
                )
                self.ui_queue.put(_close_progress)
                self.ui_queue.put(self.local_mod_list_presenter.load_local_mods)
                msg_body = (
                    f"已完成 {len(succeeded_root_keys)} 個模組安裝"
                    + (
                        f"\n必要依賴：已補裝 {handoff.dependency_count} 個"
                        + (
                            f"，已合併 {handoff.duplicate_dependency_count} 個重複項目，避免重複下載"
                            if handoff.duplicate_dependency_count
                            else ""
                        )
                        if handoff.dependency_count
                        else "\n必要依賴：本次無需額外補裝"
                    )
                    + (f"\n仍有 {len(retained)} 個項目保留在安裝清單中" if retained else "")
                    + handoff.skipped_text
                    + handoff.completion_notes
                )
                self.ui_queue.put(
                    lambda: UIUtils.show_message(
                        "安裝完成",
                        msg_body,
                        self.parent,
                        message_level="info",
                    )
                )
            except Exception as exc:
                if not accept_effect():
                    return
                self.ui_queue.put(_close_progress)
                self.ui_queue.put(self.local_mod_list_presenter.load_local_mods)
                logger.error("批次安裝線上模組失敗: %s\n%s", exc, traceback.format_exc())
                self.update_status_safe(f"批次安裝失敗: {exc}")
                self.ui_queue.put(
                    lambda msg=str(exc): UIUtils.show_message(
                        "安裝失敗",
                        f"無法完成安裝：{msg}",
                        self.parent,
                        message_level="error",
                    )
                )
            finally:
                self.ui_queue.put(_close_progress)
                if accept_effect():
                    self.update_progress_safe(0)

        self.scope.submit(install_task, key="online_install", critical=True)

    def _install_local_update_review_entries(
        self,
        dialog: Any,
        handoff: ReviewExecutionHandoff,
    ) -> None:
        manager = self.mod_manager
        if not manager:
            UIUtils.show_message("錯誤", "模組管理器未初始化", self.parent, message_level="error")
            return
        if handoff.mode != "local_update":
            raise ValueError("本地更新 executor 收到非本地 Review handoff")
        if not handoff.root_count:
            message = "目前沒有已啟用的可更新項目" if handoff.disabled_count else "目前沒有可直接更新的模組"
            UIUtils.show_message("沒有可更新項目", message, self.parent, message_level="warning")
            return
        if not self._validate_review_handoff(handoff, parent=self.parent):
            return
        if not self._confirm_review_handoff(handoff, parent=self.parent, action_label="更新"):
            return
        if hasattr(dialog, "accept"):
            dialog.accept()
        elif hasattr(dialog, "close"):
            dialog.close()
        elif hasattr(dialog, "destroy"):
            dialog.destroy()

        session = self.mod_session
        install_scope = session.begin_install()

        cancel_token_holder = CancellationToken()
        progress_dlg = None
        if isinstance(self.parent, QWidget):
            try:
                progress_dlg = ProgressDialog(self.parent, title="正在更新模組", show_cancel=True)
                progress_dlg.rejected.connect(cancel_token_holder.cancel)
                progress_dlg.show()
            except Exception as exc:
                logger.debug(f"ProgressDialog 初始化略過: {exc}")

        def _close_local_progress() -> None:
            if progress_dlg is not None:
                with suppress(Exception):
                    progress_dlg.close()
                    progress_dlg.deleteLater()

        def install_task() -> None:
            active_token = cancel_token_holder

            def accept_effect():
                return session.is_scope_current(install_scope)

            success_count = 0

            def record_completed_step(step: ReviewInstallStep) -> None:
                nonlocal success_count
                if step.kind == "local_root":
                    success_count += 1

            try:
                if not self._execute_review_handoff_steps(
                    manager,
                    handoff,
                    active_token=active_token,
                    progress_dialog=progress_dlg,
                    accept_effect=accept_effect,
                    action_label="模組更新",
                    on_step_completed=record_completed_step,
                ):
                    self.ui_queue.put(_close_local_progress)
                    self.ui_queue.put(self.local_mod_list_presenter.load_local_mods)
                    return
                if not session.is_scope_current(install_scope):
                    self.ui_queue.put(_close_local_progress)
                    return
                self.update_progress_safe(1.0)
                self.update_status_safe(f"已完成 {success_count} 個模組更新")
                self.ui_queue.put(_close_local_progress)
                self.ui_queue.put(self.local_mod_list_presenter.load_local_mods)
                msg_body = (
                    f"已完成 {success_count} 個模組更新"
                    + (f"\n已略過 {handoff.disabled_count} 個停用項目" if handoff.disabled_count else "")
                    + handoff.skipped_text
                    + handoff.completion_notes
                )
                self.ui_queue.put(
                    lambda: UIUtils.show_message(
                        "更新完成",
                        msg_body,
                        self.parent,
                        message_level="info",
                    )
                )
            except Exception as exc:
                if not accept_effect():
                    return
                self.ui_queue.put(_close_local_progress)
                self.ui_queue.put(self.local_mod_list_presenter.load_local_mods)
                logger.error("本地模組更新失敗: %s\n%s", exc, traceback.format_exc())
                self.update_status_safe(f"本地模組更新失敗: {exc}")
                self.ui_queue.put(
                    lambda msg=str(exc): UIUtils.show_message(
                        "更新失敗",
                        f"無法完成更新：{msg}",
                        self.parent,
                        message_level="error",
                    )
                )
            finally:
                self.ui_queue.put(_close_local_progress)
                if accept_effect():
                    self.update_progress_safe(0)

        self.scope.submit(install_task, key="local_update_install", critical=True)


__all__ = ["ModManagementInstallExecutor"]
