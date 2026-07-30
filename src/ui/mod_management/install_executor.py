"""安裝與更新執行器。"""

from __future__ import annotations

import contextlib
import traceback
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ...core import (
    ModManager,
    analyze_mod_version_compatibility,
    build_required_dependency_install_plan,
    resolve_modrinth_project_names,
)
from ...models import LocalUpdateReviewEntry, PendingInstallReviewEntry, PendingOnlineInstall
from ...utils import (
    LOCAL_UPDATE_SKIPPED_BLOCKED_TEMPLATE,
    LOCAL_UPDATE_SKIPPED_RETRYABLE_TEMPLATE,
    LOCAL_UPDATE_SKIPPED_UNKNOWN_TEMPLATE,
    ONLINE_INSTALL_NO_ACTIONABLE_MESSAGE,
    CancellationToken,
    TaskUtils,
    UIUtils,
    extract_primary_file_hash,
)
from ...utils.ui_support import qt_widgets as qt
from .constants import SUPPORTED_ONLINE_MOD_LOADERS, logger
from .online_mod_queue import ModManagementRuntimeBase


class ModManagementInstallExecutorMixin(ModManagementRuntimeBase):
    """負責執行線上安裝、本地更新與依賴下載的共用流程。"""

    def _get_supported_online_loader(self) -> tuple[str | None, str | None]:
        """回傳目前伺服器可用於線上模組功能的 loader；若不支援則附帶提示訊息。"""
        if not self.current_server:
            return (None, "請先選擇伺服器後再使用線上模組功能")
        raw_loader = str(getattr(self.current_server, "loader_type", "") or "").strip()
        normalized_loader = raw_loader.lower()
        if normalized_loader not in SUPPORTED_ONLINE_MOD_LOADERS:
            loader_display = raw_loader or "未設定"
            return (
                None,
                f"線上模組功能目前僅支援 Fabric / Forge / Quilt / NeoForge，當前伺服器載入器為：{loader_display}",
            )
        return (normalized_loader, None)

    def _refresh_online_queue_button(self) -> None:
        """更新安裝清單按鈕文字。"""
        try:
            logger.debug("刷新安裝清單按鈕: pending_count=%d", len(getattr(self, "pending_online_installs", [])))
        except Exception:
            logger.debug("刷新安裝清單按鈕: 無法取得 pending_online_installs 長度")
        if hasattr(self, "online_queue_button") and self.online_queue_button:
            self.online_queue_button.configure(
                text=f"🧺 安裝清單 ({len(getattr(self, 'pending_online_installs', []))})"
            )

    @staticmethod
    def _build_pending_install_key(project_id: str, version_id: str) -> str:
        return f"{str(project_id or '').strip()}::{str(version_id or '').strip()}"

    @staticmethod
    def _build_dependency_install_key(dependency_item: Any) -> tuple[str, str, str, str]:
        return (
            str(getattr(dependency_item, "project_id", "") or "").strip(),
            str(getattr(dependency_item, "version_id", "") or "").strip(),
            str(getattr(dependency_item, "download_url", "") or "").strip(),
            str(getattr(dependency_item, "filename", "") or "").strip(),
        )

    @staticmethod
    def _resolve_expected_download_hash(version: Any | None) -> str:
        return (
            extract_primary_file_hash(version)
            or extract_primary_file_hash(version, "sha256")
            or extract_primary_file_hash(version, "sha1")
        )

    @staticmethod
    def _build_download_kwargs(
        progress_callback: Callable[[int, int], None] | None,
        expected_hash: str | None = None,
        *,
        provider: str | None = "modrinth",
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        download_kwargs: dict[str, Any] = {"progress_callback": progress_callback}
        if str(expected_hash or "").strip():
            download_kwargs["expected_hash"] = expected_hash
        download_kwargs["provider"] = str(provider or "modrinth").strip() or "modrinth"
        if cancel_check is not None:
            download_kwargs["cancel_check"] = cancel_check
        return download_kwargs

    def _install_dependency_item(
        self,
        manager: ModManager,
        dependency_item: Any,
        *,
        current_step: int,
        total_steps: int,
        status_message: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path | None:
        self.update_status_safe(f"{status_message}：{dependency_item.project_name}")
        expected_hash = str(getattr(dependency_item, "expected_hash", "") or "").strip() or None
        return manager.install_remote_mod_file(
            download_url=dependency_item.download_url,
            filename=dependency_item.filename,
            **self._build_download_kwargs(
                self._make_step_progress_callback(current_step, total_steps),
                expected_hash,
                provider=str(getattr(dependency_item, "provider", "modrinth") or "modrinth"),
                cancel_check=cancel_check,
            ),
        )

    def _collect_unique_dependency_install_keys(
        self, review_entries: list[Any]
    ) -> tuple[set[tuple[str, str, str, str]], int]:
        unique_keys: set[tuple[str, str, str, str]] = set()
        duplicate_count = 0
        for review_entry in review_entries:
            for dependency_item in self._get_enabled_dependency_install_items(
                getattr(review_entry, "dependency_plan", None)
            ):
                dependency_key = self._build_dependency_install_key(dependency_item)
                if dependency_key in unique_keys:
                    duplicate_count += 1
                    continue
                unique_keys.add(dependency_key)
        return (unique_keys, duplicate_count)

    def _get_current_installed_mods(self) -> list[Any]:
        manager = self.mod_manager
        if not manager:
            return list(self.local_mods)
        try:
            return manager.get_mod_list()
        except Exception as e:
            logger.error(f"讀取本地模組列表失敗: {e}")
            return list(self.local_mods)

    @staticmethod
    def _build_installed_mod_simulation_item(
        project_id: str, project_name: str, filename: str, version_name: str
    ) -> Any:
        normalized_name = str(project_name or project_id or filename or "未知模組").strip() or "未知模組"
        normalized_filename = str(filename or normalized_name).strip() or normalized_name
        return SimpleNamespace(
            platform_id=str(project_id or "").strip(),
            id=normalized_name,
            name=normalized_name,
            filename=normalized_filename,
            version=str(version_name or "").strip(),
        )

    def _add_pending_online_install(self, pending: PendingOnlineInstall) -> bool:
        """
        加入待安裝清單，若同版本已存在則覆蓋。

        Returns:
            若成功加入則回傳 True；若因伺服器端不支援而被阻擋則回傳 False。
        """
        blocking_reason = self._build_server_install_blocking_reason(getattr(pending, "server_side", ""))
        if blocking_reason:
            logger.info("拒絕加入安裝清單: %s", blocking_reason)
            UIUtils.show_warning("無法加入安裝清單", blocking_reason, self.parent)
            return False
        pending_key = self._build_pending_install_key(pending.project_id, getattr(pending.version, "version_id", ""))
        logger.debug("準備加入安裝清單: key=%s project=%s", pending_key, getattr(pending, "project_name", ""))
        remaining_items = [
            item
            for item in getattr(self, "pending_online_installs", [])
            if self._build_pending_install_key(item.project_id, getattr(item.version, "version_id", "")) != pending_key
        ]
        remaining_items.append(pending)
        # 更新記憶體清單，並盡量原地修改，避免外部已持有的列表參照失效
        if hasattr(self, "pending_online_installs") and isinstance(self.pending_online_installs, list):
            self.pending_online_installs[:] = remaining_items
        else:
            self.pending_online_installs = list(remaining_items)
        logger.debug(
            "已更新記憶體 pending_online_installs: new_count=%d", len(getattr(self, "pending_online_installs", []))
        )
        try:
            if hasattr(self, "ui_queue") and self.ui_queue is not None:
                self.ui_queue.put(self._refresh_online_queue_button)
            else:
                self._refresh_online_queue_button()
        except Exception:
            # 在極少數情況下直接嘗試也可以保底
            with contextlib.suppress(Exception):
                self._refresh_online_queue_button()
        # 使用 thread-safe 的狀態更新接口；在測試或極早期初始化時回退成同步更新
        status_message = (
            f"已加入安裝清單：{pending.project_name} ({getattr(pending.version, 'display_name', '未知版本')})"
        )
        if hasattr(self, "ui_queue") and getattr(self, "ui_queue", None) is not None:
            self.update_status_safe(status_message)
        else:
            self.update_status(status_message)
        return True

    def _prepare_online_install_review_entries(self) -> list[PendingInstallReviewEntry]:
        """以目前本地模組狀態重新驗證待安裝清單。"""
        minecraft_version, loader_type, loader_version = self._get_current_modrinth_context()
        simulated_installed_mods = list(self._get_current_installed_mods())
        review_entries: list[PendingInstallReviewEntry] = []
        for pending in self.pending_online_installs:
            dependency_project_ids = {
                str(dependency.get("project_id", "") or "").strip()
                for dependency in getattr(pending.version, "dependencies", []) or []
                if isinstance(dependency, dict) and str(dependency.get("project_id", "") or "").strip()
            }
            dependency_names = resolve_modrinth_project_names(dependency_project_ids)
            report = analyze_mod_version_compatibility(
                pending.version,
                project_id=pending.project_id,
                project_name=pending.project_name,
                minecraft_version=minecraft_version,
                loader=loader_type,
                loader_version=loader_version,
                installed_mods=simulated_installed_mods,
                dependency_names=dependency_names,
            )
            dependency_plan = build_required_dependency_install_plan(
                pending.version,
                minecraft_version=minecraft_version,
                loader=loader_type,
                loader_version=loader_version,
                installed_mods=simulated_installed_mods,
                root_project_id=pending.project_id,
                root_project_name=pending.project_name,
            )
            server_side_blocking_reason = self._build_server_install_blocking_reason(
                getattr(pending, "server_side", "")
            )
            server_side_warning_message = self._build_server_install_warning_line(getattr(pending, "server_side", ""))
            blocking_reasons = [
                *list(getattr(report, "hard_errors", []) or []),
                *list(getattr(dependency_plan, "unresolved_required", []) or []),
            ]
            if server_side_blocking_reason:
                blocking_reasons.append(server_side_blocking_reason)
            warning_messages = list(getattr(report, "warnings", []) or [])
            if server_side_warning_message:
                warning_messages.append(server_side_warning_message)
            review_entry = PendingInstallReviewEntry(
                pending=pending,
                report=report,
                dependency_plan=dependency_plan,
                blocking_reasons=blocking_reasons,
                warning_messages=warning_messages,
                enabled=not blocking_reasons,
                provider=str(getattr(pending.version, "provider", "modrinth") or "modrinth"),
                version_type=str(getattr(pending.version, "version_type", "") or ""),
                date_published=str(getattr(pending.version, "date_published", "") or ""),
                changelog=str(getattr(pending.version, "changelog", "") or ""),
            )
            review_entry.warning_messages = self._dedupe_review_messages(
                [
                    *warning_messages,
                    *self._collect_non_official_source_warning_messages(review_entry, enabled_only=True),
                ]
            )
            review_entries.append(review_entry)
            if review_entry.actionable:
                self._append_enabled_dependency_simulations(simulated_installed_mods, dependency_plan)
                primary_file = getattr(pending.version, "primary_file", None) or {}
                self._append_simulated_installed_mod(
                    simulated_installed_mods,
                    self._build_installed_mod_simulation_item(
                        pending.project_id,
                        pending.project_name,
                        str(primary_file.get("filename", "") or pending.project_name),
                        str(
                            getattr(pending.version, "version_number", "")
                            or getattr(pending.version, "display_name", "")
                        ),
                    ),
                )
        return review_entries

    def _install_online_version(
        self,
        mod: Any,
        versions: list[Any],
        version_tree: qt.Treeview,
        dialog,
        version_reports: list[Any] | None = None,
    ) -> None:
        """將選取版本加入待安裝清單。"""
        selection = version_tree.selection()
        if not selection:
            UIUtils.show_warning("警告", "請先選擇要安裝的版本", dialog)
            return
        selected_index = int(selection[0])
        version = versions[selected_index]
        report = None
        if version_reports and selected_index < len(version_reports):
            report = version_reports[selected_index]
        if report is not None and (not getattr(report, "compatible", True)):
            UIUtils.show_error("版本不相容", self._format_online_version_report(version, report), dialog)
            return
        file_info = getattr(version, "primary_file", None)
        if not file_info:
            UIUtils.show_error("錯誤", "此版本沒有可下載的 JAR 檔案", dialog)
            return
        download_url = str(file_info.get("url", "") or "")
        filename = str(file_info.get("filename", "") or "")
        if not download_url or not filename:
            UIUtils.show_error("錯誤", "無法取得下載連結或檔名", dialog)
            return
        if self._add_pending_online_install(
            PendingOnlineInstall(
                project_id=str(getattr(mod, "project_id", "") or "").strip(),
                project_name=str(getattr(mod, "name", "未知模組") or "未知模組").strip(),
                version=version,
                report=report,
                homepage_url=str(getattr(mod, "homepage_url", "") or "").strip(),
                source_url=str(getattr(mod, "url", "") or "").strip(),
                server_side=str(getattr(mod, "server_side", "") or "").strip(),
                client_side=str(getattr(mod, "client_side", "") or "").strip(),
            )
        ):
            dialog.destroy()

    def _remove_selected_pending_online_installs(
        self, queue_tree, dialog, review_root_keys: set[str] | None = None
    ) -> None:
        """從待安裝清單移除選取的根項目。"""
        if review_root_keys:
            selected_root_keys = self._collect_selected_root_keys_from(queue_tree, review_root_keys)
        else:
            selected_root_keys = self._collect_selected_root_keys(queue_tree)
        if not selected_root_keys:
            UIUtils.show_warning("提示", "請先選擇要移除的模組項目", dialog)
            return
        before_count = len(self.pending_online_installs)
        retained_items = [
            item
            for item in self.pending_online_installs
            if self._build_pending_install_key(item.project_id, getattr(item.version, "version_id", ""))
            not in selected_root_keys
        ]
        if isinstance(self.pending_online_installs, list):
            self.pending_online_installs[:] = retained_items
        else:
            self.pending_online_installs = retained_items
        removed_count = before_count - len(retained_items)
        if removed_count <= 0:
            UIUtils.show_warning("提示", "目前選取項目不可移除，請選擇模組根項目後再試一次", dialog)
            return
        logger.info("安裝清單移除選取項目: removed=%d remaining=%d", removed_count, len(self.pending_online_installs))
        self._refresh_online_queue_button()
        dialog.destroy()
        if self.pending_online_installs:
            self.show_online_install_queue()

    def _clear_pending_online_installs(self, dialog) -> None:
        """清空待安裝清單。"""
        if isinstance(getattr(self, "pending_online_installs", None), list):
            self.pending_online_installs.clear()
        else:
            self.pending_online_installs = []
        self._refresh_online_queue_button()
        dialog.destroy()

    def _install_pending_online_install_queue(
        self, dialog, review_entries: list[PendingInstallReviewEntry] | None = None
    ) -> None:
        """執行待安裝清單中的所有可安裝項目。"""
        manager = self.mod_manager
        if not manager:
            UIUtils.show_error("錯誤", "模組管理器未初始化", self.parent)
            return
        effective_review_entries = (
            review_entries if review_entries is not None else self._prepare_online_install_review_entries()
        )
        if review_entries is not None:
            logger.debug("安裝清單使用當前 review 快照執行，略過同步重建")
        actionable_entries = [entry for entry in effective_review_entries if entry.actionable]
        logger.info(
            "安裝清單執行請求: total=%d actionable=%d blocked=%d",
            len(effective_review_entries),
            len(actionable_entries),
            self._count_blocked_entries(effective_review_entries),
        )
        if not actionable_entries:
            UIUtils.show_warning("無法安裝", ONLINE_INSTALL_NO_ACTIONABLE_MESSAGE, dialog)
            return
        execution_prompt = self._build_execution_prompt(effective_review_entries, mode="online")
        if execution_prompt:
            proceed = UIUtils.ask_yes_no_cancel("確認本次安裝內容", execution_prompt, parent=dialog, show_cancel=False)
            if proceed is not True:
                self.update_status_safe("已取消安裝清單執行")
                return
        if not self._confirm_non_official_download_sources(
            actionable_entries,
            action_label="安裝",
            parent=dialog,
        ):
            self.update_status_safe("已取消非官方來源安裝")
            return
        self.update_status_safe("正在啟動安裝清單執行...")
        dialog.destroy()
        online_group_counts = self._count_review_groups_by_mode(effective_review_entries, mode="online")
        online_skipped_parts: list[str] = []
        if online_group_counts.get("disabled", 0):
            online_skipped_parts.append(f"已停用 {online_group_counts['disabled']} 項")
        if online_group_counts.get("blocked", 0):
            online_skipped_parts.append(f"需先處理 {online_group_counts['blocked']} 項")
        online_skipped_text = "\n略過項目：\n- " + "\n- ".join(online_skipped_parts) if online_skipped_parts else ""
        unique_dependency_keys, duplicate_dependency_count = self._collect_unique_dependency_install_keys(
            actionable_entries
        )
        dependency_install_count = len(unique_dependency_keys)
        completion_notes = self._format_completion_notes(
            [
                *[
                    message
                    for entry in actionable_entries
                    for message in list(getattr(entry, "warning_messages", []) or [])
                ],
                *[
                    message
                    for entry in actionable_entries
                    for message in list(getattr(getattr(entry, "report", None), "notes", []) or [])
                ],
                *[
                    message
                    for entry in actionable_entries
                    for message in list(getattr(getattr(entry, "dependency_plan", None), "notes", []) or [])
                ],
            ]
        )

        def install_task(cancel_token: CancellationToken | None = None) -> None:
            succeeded_keys: set[str] = set()
            processed_dependency_keys: set[tuple[str, str, str, str]] = set()
            total_steps = dependency_install_count + len(actionable_entries)
            current_step = 0
            cancel_check = cancel_token.is_cancelled if cancel_token else None
            try:
                if cancel_token and cancel_token.is_cancelled():
                    self.update_status_safe("安裝清單已取消")
                    return
                logger.info(
                    "安裝清單背景執行開始: actionable=%d dependency_unique=%d dependency_duplicated=%d total_steps=%d",
                    len(actionable_entries),
                    dependency_install_count,
                    duplicate_dependency_count,
                    total_steps,
                )
                for review_entry in actionable_entries:
                    if cancel_token and cancel_token.is_cancelled():
                        self.update_status_safe("安裝清單已取消")
                        return
                    pending = review_entry.pending
                    for dependency_item in self._get_enabled_dependency_install_items(review_entry.dependency_plan):
                        dependency_key = self._build_dependency_install_key(dependency_item)
                        if dependency_key in processed_dependency_keys:
                            logger.info(
                                "略過重複必要依賴下載: %s (%s)",
                                dependency_item.project_name,
                                dependency_item.version_name,
                            )
                            continue
                        processed_dependency_keys.add(dependency_key)
                        if cancel_token and cancel_token.is_cancelled():
                            self.update_status_safe("安裝清單已取消")
                            return
                        installed_dependency = self._install_dependency_item(
                            manager,
                            dependency_item,
                            current_step=current_step,
                            total_steps=total_steps,
                            status_message="正在安裝必要依賴",
                            cancel_check=cancel_check,
                        )
                        if installed_dependency is None:
                            if cancel_token and cancel_token.is_cancelled():
                                self.update_status_safe("安裝清單已取消")
                                return
                            raise RuntimeError(f"必要依賴安裝失敗：{dependency_item.project_name}")
                        current_step += 1
                    primary_file = getattr(pending.version, "primary_file", None) or {}
                    filename = str(primary_file.get("filename", "") or "").strip()
                    download_url = str(primary_file.get("url", "") or "").strip()
                    expected_hash = self._resolve_expected_download_hash(pending.version)
                    self.update_status_safe(
                        f"正在安裝模組：{pending.project_name} ({getattr(pending.version, 'display_name', '未知版本')})"
                    )
                    installed_path = manager.install_remote_mod_file(
                        download_url=download_url,
                        filename=filename,
                        **self._build_download_kwargs(
                            self._make_step_progress_callback(current_step, total_steps),
                            expected_hash or None,
                            provider=review_entry.provider,
                            cancel_check=cancel_check,
                        ),
                    )
                    if installed_path is None:
                        if cancel_token and cancel_token.is_cancelled():
                            self.update_status_safe("安裝清單已取消")
                            return
                        raise RuntimeError(f"模組安裝失敗：{pending.project_name}")
                    current_step += 1
                    succeeded_keys.add(
                        self._build_pending_install_key(pending.project_id, getattr(pending.version, "version_id", ""))
                    )
                retained_items = [
                    item
                    for item in self.pending_online_installs
                    if self._build_pending_install_key(item.project_id, getattr(item.version, "version_id", ""))
                    not in succeeded_keys
                ]
                if isinstance(self.pending_online_installs, list):
                    self.pending_online_installs[:] = retained_items
                else:
                    self.pending_online_installs = retained_items
                self._refresh_online_queue_button()
                self.update_progress_safe(1.0)
                self.update_status_safe(
                    f"已完成 {len(succeeded_keys)} 個模組安裝，必要依賴已補裝 {dependency_install_count} 個"
                    + (f"，並合併 {duplicate_dependency_count} 個重複項目" if duplicate_dependency_count else "")
                )
                self.ui_queue.put(self.load_local_mods)
                self.ui_queue.put(
                    lambda: UIUtils.show_info(
                        "安裝完成",
                        f"已完成 {len(succeeded_keys)} 個模組安裝。"
                        + (
                            f"\n必要依賴：已補裝 {dependency_install_count} 個。"
                            + (
                                f"已合併 {duplicate_dependency_count} 個重複項目，避免重複下載。"
                                if duplicate_dependency_count
                                else ""
                            )
                            if dependency_install_count
                            else "\n必要依賴：本次無需額外補裝。"
                        )
                        + (
                            f"\n仍有 {len(self.pending_online_installs)} 個項目保留在安裝清單中。"
                            if self.pending_online_installs
                            else ""
                        )
                        + online_skipped_text
                        + completion_notes,
                        self.parent,
                    )
                )
            except Exception as e:
                logger.error(f"批次安裝線上模組失敗: {e}\n{traceback.format_exc()}")
                self.update_status_safe(f"批次安裝失敗: {e}")
                self.ui_queue.put(
                    lambda msg=str(e): UIUtils.show_error("安裝失敗", f"無法完成安裝：{msg}", self.parent)
                )
            finally:
                self.update_progress_safe(0)

        cancel_token = CancellationToken()
        TaskUtils.run_async(install_task, cancel_token=cancel_token)

    def _install_local_update_review_entries(self, dialog, review_entries: list[LocalUpdateReviewEntry]) -> None:
        """安裝本地模組更新。"""
        manager = self.mod_manager
        if not manager:
            UIUtils.show_error("錯誤", "模組管理器未初始化", self.parent)
            return
        actionable_entries = [entry for entry in review_entries if entry.actionable]
        disabled_entries = [entry for entry in review_entries if entry.runnable and (not entry.enabled)]
        if not actionable_entries:
            message = "目前沒有可直接更新的模組。"
            if disabled_entries:
                message = "目前沒有已啟用的可更新項目，請先啟用要執行的更新項目。"
            UIUtils.show_warning("沒有可更新項目", message, dialog)
            return
        execution_prompt = self._build_execution_prompt(review_entries, mode="local")
        if execution_prompt:
            proceed = UIUtils.ask_yes_no_cancel("確認本次更新內容", execution_prompt, parent=dialog, show_cancel=False)
            if proceed is not True:
                self.update_status_safe("已取消模組更新執行")
                return
        if not self._confirm_non_official_download_sources(
            actionable_entries,
            action_label="更新",
            parent=dialog,
        ):
            self.update_status_safe("已取消非官方來源更新")
            return
        dialog.destroy()
        skipped_counts = self._count_review_groups_by_mode(review_entries, mode="local")
        skipped_group_parts: list[str] = []
        if skipped_counts["retryable"]:
            skipped_group_parts.append(
                LOCAL_UPDATE_SKIPPED_RETRYABLE_TEMPLATE.format(count=skipped_counts["retryable"])
            )
        if skipped_counts["unknown"]:
            skipped_group_parts.append(LOCAL_UPDATE_SKIPPED_UNKNOWN_TEMPLATE.format(count=skipped_counts["unknown"]))
        if skipped_counts["blocked"]:
            skipped_group_parts.append(LOCAL_UPDATE_SKIPPED_BLOCKED_TEMPLATE.format(count=skipped_counts["blocked"]))
        skipped_group_text = "\n略過項目：\n- " + "\n- ".join(skipped_group_parts) if skipped_group_parts else ""
        completion_notes = self._format_completion_notes(
            [
                *[
                    message
                    for entry in actionable_entries
                    for message in list(getattr(entry, "warning_messages", []) or [])
                ],
                *[
                    message
                    for entry in actionable_entries
                    for message in list(getattr(getattr(entry.candidate, "report", None), "warnings", []) or [])
                ],
                *[
                    message
                    for entry in actionable_entries
                    for message in list(getattr(entry.candidate, "notes", []) or [])
                ],
                *[
                    message
                    for entry in actionable_entries
                    for message in list(getattr(getattr(entry, "dependency_plan", None), "notes", []) or [])
                ],
            ]
        )

        def install_task(cancel_token: CancellationToken | None = None) -> None:
            total_steps = sum(
                len(self._get_enabled_dependency_install_items(entry.dependency_plan)) + 1
                for entry in actionable_entries
            )
            current_step = 0
            success_count = 0
            cancel_check = cancel_token.is_cancelled if cancel_token else None
            try:
                for review_entry in actionable_entries:
                    if cancel_token and cancel_token.is_cancelled():
                        self.update_status_safe("模組更新已取消")
                        return
                    candidate = review_entry.candidate
                    for dependency_item in self._get_enabled_dependency_install_items(review_entry.dependency_plan):
                        installed_dependency = self._install_dependency_item(
                            manager,
                            dependency_item,
                            current_step=current_step,
                            total_steps=total_steps,
                            status_message="正在更新所需依賴",
                            cancel_check=cancel_check,
                        )
                        if installed_dependency is None:
                            if cancel_token and cancel_token.is_cancelled():
                                self.update_status_safe("模組更新已取消")
                                return
                            raise RuntimeError(f"依賴安裝失敗：{dependency_item.project_name}")
                        current_step += 1
                    self.update_status_safe(f"正在更新模組：{candidate.project_name}")
                    expected_hash = self._resolve_expected_download_hash(candidate.target_version)
                    updated_path = manager.replace_local_mod_file(
                        candidate.local_mod,
                        candidate.download_url,
                        candidate.target_filename,
                        **self._build_download_kwargs(
                            self._make_step_progress_callback(current_step, total_steps),
                            expected_hash or None,
                            provider=review_entry.provider,
                            cancel_check=cancel_check,
                        ),
                    )
                    if updated_path is None:
                        if cancel_token and cancel_token.is_cancelled():
                            self.update_status_safe("模組更新已取消")
                            return
                        raise RuntimeError(f"模組更新失敗：{candidate.project_name}")
                    current_step += 1
                    success_count += 1
                self.update_progress_safe(1.0)
                self.update_status_safe(f"已完成 {success_count} 個模組更新")
                self.ui_queue.put(self.load_local_mods)
                self.ui_queue.put(
                    lambda: UIUtils.show_info(
                        "更新完成",
                        f"已完成 {success_count} 個模組更新。"
                        + (f"\n已略過 {len(disabled_entries)} 個停用項目。" if disabled_entries else "")
                        + skipped_group_text
                        + completion_notes,
                        self.parent,
                    )
                )
            except Exception as e:
                logger.error(f"本地模組更新失敗: {e}\n{traceback.format_exc()}")
                self.update_status_safe(f"本地模組更新失敗: {e}")
                self.ui_queue.put(
                    lambda msg=str(e): UIUtils.show_error("更新失敗", f"無法完成更新：{msg}", self.parent)
                )
            finally:
                self.update_progress_safe(0)

        cancel_token = CancellationToken()
        TaskUtils.run_async(install_task, cancel_token=cancel_token)


__all__ = ["ModManagementInstallExecutorMixin"]
