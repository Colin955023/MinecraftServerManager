"""模組管理頁面主框架。"""

from __future__ import annotations

import queue
import re
import tkinter
import tkinter.filedialog as filedialog
import tkinter.ttk as ttk
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import customtkinter as ctk

from ...core import AppException, MinecraftVersionManager, ModManager, ModStatus
from ...utils import (
    Colors,
    FontSize,
    PathUtils,
    Sizes,
    Spacing,
    UIUtils,
)
from ..custom_dropdown import CustomDropdown
from ..dialog_utils import DialogUtils
from ..font_manager import FontManager
from ..mod_search_service.models import LocalModUpdatePlan
from ..task_utils import TaskUtils
from .constants import logger
from .install_executor import ModManagementInstallExecutorMixin
from .local_mod_list_presenter import LocalModListPresenter
from .local_tree_virtualization_state import LocalTreeVirtualizationState
from .models import OnlineBrowseRequest, PendingOnlineInstall
from .online_browse_presenter import OnlineBrowsePresenter
from .online_mod_queue import ModManagementQueueMixin
from .review import ModManagementReviewMixin
from .tree_sync import ModManagementTreeSyncMixin


class ModManagementFrame(
    ModManagementQueueMixin, ModManagementReviewMixin, ModManagementInstallExecutorMixin, ModManagementTreeSyncMixin
):
    """模組管理主畫面，整合本地列表、線上搜尋、review 與安裝流程。"""

    def __init__(
        self,
        parent,
        server_manager,
        on_server_selected_callback: Callable | None = None,
        version_manager: MinecraftVersionManager = None,
    ):
        self.parent = parent
        self.server_manager = server_manager
        self.on_server_selected = on_server_selected_callback
        self.version_manager = version_manager
        self.current_server = None
        self.mod_manager: ModManager | None = None
        self.versions: list = []
        self.release_versions: list = []
        self.all_selected = False
        self.selected_mods: set[str] = set()
        self.VERSION_PATTERN = re.compile("-([\\dv.]+)(?:\\.jar(?:\\.disabled)?)?$")
        self.main_frame: ctk.CTkFrame | None = None
        self.notebook: ttk.Notebook | None = None
        self.local_tab: ctk.CTkFrame | None = None
        self.browse_tab: ctk.CTkFrame | None = None
        self.browse_tree: ttk.Treeview | None = None
        self.browse_filter_label: ctk.CTkLabel | None = None
        self.browse_results_label: ctk.CTkLabel | None = None
        self.local_tree: ttk.Treeview | None = None
        self.local_v_scrollbar: ttk.Scrollbar | None = None
        self.local_h_scrollbar: ttk.Scrollbar | None = None
        self.local_tree_state = LocalTreeVirtualizationState()
        self.local_tree_state.apply_to_frame(self)
        self.local_mod_list_presenter = LocalModListPresenter(self)
        self.online_browse_presenter = OnlineBrowsePresenter(self)
        self.local_mods: list[Any] = []
        self.online_mods: list[Any] = []
        self._online_refresh_job: str | None = None
        self._online_refresh_token = 0
        self._online_tree_render_locked = False
        self._online_rows_snapshot: dict[str, tuple[tuple[Any, ...], tuple[str, ...]]] = {}
        self._online_mod_by_row_key: dict[str, Any] = {}
        self._online_insert_batch_base = 60
        self._online_insert_batch_max = 180
        self._online_insert_batch_divisor = 8
        self._online_mod_index: dict[str, Any] = {}
        self._last_online_request: OnlineBrowseRequest | None = None
        self.pending_online_installs: list[PendingOnlineInstall] = []
        self._latest_local_update_plan = LocalModUpdatePlan()
        self.enhanced_mods_cache: dict[str, Any] = {}
        self._dependency_snapshot_migration_totals: dict[str, int] = {
            "checked": 0,
            "migrated": 0,
            "replayed": 0,
            "fallback_rebuild": 0,
        }
        self._last_mods_dir: str | None = None
        self._last_mods_dir_mtime: float | None = None
        self._status_update_job = None
        self._pending_status_message: str = ""
        self.ui_queue: queue.Queue = queue.Queue()
        self.create_widgets()
        host = self.main_frame if self.main_frame and self.main_frame.winfo_exists() else self.parent
        TaskUtils.start_ui_queue_pump(host, self.ui_queue)
        self.load_servers()

    def _get_local_mod_list_presenter(self) -> LocalModListPresenter:
        """取得本地列表 presenter；支援 __new__ 建立的測試物件。"""
        presenter = getattr(self, "local_mod_list_presenter", None)
        if presenter is None:
            presenter = LocalModListPresenter(self)
            self.local_mod_list_presenter = presenter
        return presenter

    def _get_online_browse_presenter(self) -> OnlineBrowsePresenter:
        """取得線上瀏覽 presenter；支援 __new__ 建立的測試物件。"""
        presenter = getattr(self, "online_browse_presenter", None)
        if presenter is None:
            presenter = OnlineBrowsePresenter(self)
            self.online_browse_presenter = presenter
        return presenter

    def update_status(self, message: str) -> None:
        """安全地更新狀態標籤，並合併連續的 idle 更新。

        Args:
            message: 要顯示的狀態文字。
        """
        self._pending_status_message = str(message)
        try:
            if hasattr(self, "status_label") and self.status_label and self.status_label.winfo_exists():
                if hasattr(self, "parent") and self.parent and self.parent.winfo_exists():
                    UIUtils.schedule_coalesced_idle(
                        self.parent, "_status_update_job", self._apply_status_label_update, owner=self
                    )
                else:
                    self._apply_status_label_update()
        except (AttributeError, RuntimeError) as e:
            logger.warning(f"更新狀態遇到暫時性問題: {e}")
        except AppException as e:
            logger.info(f"更新狀態被應用例外攔截: {e}")
            self.update_status_safe(str(e))
        except Exception:
            logger.error("更新狀態失敗: 未知錯誤\n" + traceback.format_exc())

    def _apply_status_label_update(self) -> None:
        """套用合併後的狀態文字。"""
        self._status_update_job = None
        if hasattr(self, "status_label") and self.status_label and self.status_label.winfo_exists():
            self.status_label.configure(text=self._pending_status_message)

    def update_status_safe(self, message: str) -> None:
        """將狀態更新排入 UI 佇列執行。

        Args:
            message: 要顯示的狀態文字。
        """
        self.ui_queue.put(lambda: self.update_status(message))

    def update_progress_safe(self, value: float) -> None:
        """將進度更新排入 UI 佇列執行。

        Args:
            value: 介於 0 到 1 的進度值。
        """

        def _update():
            if hasattr(self, "progress_var") and self.progress_var:
                try:
                    self.progress_var.set(value)
                except (AttributeError, RuntimeError) as e:
                    logger.warning(f"更新進度遇到暫時性問題: {e}")
                except AppException as e:
                    logger.info(f"更新進度被應用例外攔截: {e}")
                except Exception:
                    logger.error("更新進度失敗: 未知錯誤\n" + traceback.format_exc())

        self.ui_queue.put(_update)

    def _apply_local_toggle_success(
        self,
        *,
        tree: ttk.Treeview | None,
        item_id: str,
        mod_id: str,
        mod_obj: Any,
        new_status: ModStatus,
        new_filename: str,
        old_filename: str,
        old_file_path: str,
    ) -> None:
        """同步本地模組狀態切換成功後的記憶體與 Treeview 狀態。"""
        mod_obj.status = new_status
        mod_obj.filename = new_filename
        if old_file_path:
            try:
                mod_obj.file_path = str(Path(old_file_path).with_name(new_filename))
            except Exception:
                mod_obj.file_path = old_file_path.replace(old_filename, new_filename)
        try:
            mod_obj._cached_mtime = Path(mod_obj.file_path).stat().st_mtime
        except Exception:
            mod_obj._cached_mtime = None
        if (
            hasattr(self, "enhanced_mods_cache")
            and isinstance(self.enhanced_mods_cache, dict)
            and (old_filename in self.enhanced_mods_cache)
            and (new_filename not in self.enhanced_mods_cache)
        ):
            self.enhanced_mods_cache[new_filename] = self.enhanced_mods_cache[old_filename]
        if not tree or not tree.winfo_exists():
            return
        row_values = list(tree.item(item_id, "values") or [])
        if row_values:
            row_values[0] = "✅ 已啟用" if new_status == ModStatus.ENABLED else "❌ 已停用"
            mtime_val = getattr(mod_obj, "_cached_mtime", None)
            row_values[6] = datetime.fromtimestamp(mtime_val).strftime("%Y-%m-%d %H:%M") if mtime_val else "未知"
            parity_tag = self._extract_or_compute_parity_tag(tree, item_id)
            tree.item(item_id, values=tuple(row_values), tags=(mod_id, parity_tag))

    def create_widgets(self) -> None:
        """建立 UI 元件"""
        self.main_frame = ctk.CTkFrame(self.parent)
        self.create_header()
        self.create_server_selection()
        self.create_status_bar()
        self.create_notebook()

    def create_server_selection(self) -> None:
        """建立伺服器選擇區域"""
        server_frame = ctk.CTkFrame(self.main_frame)
        server_frame.pack(fill="x", padx=Spacing.XL, pady=(0, Spacing.SMALL_PLUS))
        inner_frame = ctk.CTkFrame(server_frame, fg_color="transparent")
        inner_frame.pack(fill="x", padx=Spacing.LARGE_MINUS, pady=Spacing.SMALL_PLUS)
        ctk.CTkLabel(
            inner_frame, text="📁 伺服器:", font=FontManager.get_font(size=FontSize.NORMAL_PLUS, weight="bold")
        ).pack(side="left")
        self.server_var = tkinter.StringVar()
        self.server_combo = CustomDropdown(
            inner_frame,
            variable=self.server_var,
            values=["載入中..."],
            command=self.on_server_changed,
            width=FontManager.get_dpi_scaled_size(200),
        )
        self.server_combo.pack(side="left", padx=(Spacing.SMALL_PLUS, 0))
        refresh_btn = ctk.CTkButton(
            inner_frame,
            text="🔄 重新整理",
            font=FontManager.get_font(size=FontSize.MEDIUM),
            command=self.load_servers,
            width=Sizes.BUTTON_WIDTH_SECONDARY,
            height=Sizes.INPUT_HEIGHT,
        )
        refresh_btn.pack(side="left", padx=(Spacing.SMALL_PLUS, 0))

    def create_header(self) -> None:
        """建立標題區域"""
        header_frame = ctk.CTkFrame(self.main_frame)
        header_frame.pack(fill="x", padx=Spacing.XL, pady=(Spacing.XL, Spacing.SMALL_PLUS))
        title_label = ctk.CTkLabel(
            header_frame, text="🧩 模組管理", font=FontManager.get_font(size=FontSize.HEADING_XLARGE, weight="bold")
        )
        title_label.pack(side="left", padx=Spacing.LARGE_MINUS, pady=Spacing.LARGE_MINUS)
        desc_label = ctk.CTkLabel(
            header_frame,
            text="參考 Prism Launcher 的模組管理流程",
            font=FontManager.get_font(size=FontSize.NORMAL_PLUS),
            text_color=Colors.TEXT_SECONDARY,
        )
        desc_label.pack(side="left", padx=(Spacing.LARGE_MINUS, Spacing.LARGE_MINUS), pady=Spacing.LARGE_MINUS)

    def create_local_mods_tab(self) -> None:
        """建立本地模組頁面"""
        if not self.notebook:
            return
        self.local_tab = ctk.CTkFrame(self.notebook)
        self.notebook.add(self.local_tab, text="📁 本地模組")
        self.create_local_toolbar()
        self.create_local_mod_list()

    def create_browse_mods_tab(self) -> None:
        """建立線上瀏覽頁面。"""
        if not self.notebook:
            return
        self.browse_tab = ctk.CTkFrame(self.notebook)
        self.notebook.add(self.browse_tab, text="🌐 瀏覽模組")
        self.create_browse_search()
        self.create_browse_mod_list()

    def create_browse_search(self) -> None:
        """建立線上搜尋區域。"""
        self._get_online_browse_presenter().create_browse_search()

    def create_browse_mod_list(self) -> None:
        """建立線上模組列表。"""
        self._get_online_browse_presenter().create_browse_mod_list()

    def create_notebook(self) -> None:
        """建立頁籤介面"""
        self.notebook = ttk.Notebook(self.main_frame)
        style = ttk.Style()
        style.configure("Tab", font=FontManager.get_font("Microsoft JhengHei", FontSize.LARGE, "bold"))
        self.notebook.pack(fill="both", expand=True, padx=Spacing.XL, pady=(0, Spacing.SMALL_PLUS))
        self.create_local_mods_tab()
        self.create_browse_mods_tab()
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

    def on_tab_changed(self, _event=None) -> None:
        """頁籤切換時同步目前頁面的資料狀態。

        Args:
            _event: 事件繫結傳入的事件物件，未使用。
        """
        try:
            if not self.notebook:
                return
            current_tab = self.notebook.index(self.notebook.select())
            if current_tab == 0:
                self.refresh_local_list()
            elif current_tab == 1:
                self._refresh_online_filter_hint()
                self._load_online_mods(show_warning=False)
        except Exception as e:
            logger.error(f"處理頁籤切換事件失敗: {e}\n{traceback.format_exc()}")

    def create_local_toolbar(self) -> None:
        """建立本地模組工具列"""
        self._get_local_mod_list_presenter().create_local_toolbar()

    def on_filter_changed(self, _value: str) -> None:
        """
        本地模組篩選條件變更時重新過濾列表。

        Args:
            _value: 下拉選單回傳的目前值。
        """
        self._get_local_mod_list_presenter().on_filter_changed(_value)

    def refresh_mod_list_force(self) -> None:
        """強制重新掃描本地模組並重繪列表"""
        self._get_local_mod_list_presenter().refresh_mod_list_force()

    def create_local_mod_list(self) -> None:
        """建立本地模組列表"""
        self._get_local_mod_list_presenter().create_local_mod_list()

    def export_mod_list_dialog(self) -> None:
        """支援格式選擇(txt/json/html)與直接存檔，檔名自動帶入伺服器名稱"""
        if not self.mod_manager or not self.current_server:
            UIUtils.show_error("錯誤", "請先選擇伺服器以匯出模組列表。", self.parent)
            return
        try:
            dialog = DialogUtils.create_toplevel_dialog(
                self.parent,
                "匯出模組列表",
                width=Sizes.DIALOG_LARGE_WIDTH,
                height=Sizes.DIALOG_LARGE_HEIGHT,
                min_width=Sizes.DIALOG_LARGE_WIDTH,
                min_height=Sizes.DIALOG_LARGE_HEIGHT,
                max_width=FontManager.get_dpi_scaled_size(1280),
                max_height=FontManager.get_dpi_scaled_size(960),
                delay_ms=250,
            )
            main_frame = ctk.CTkFrame(dialog)
            main_frame.pack(fill="both", expand=True, padx=Spacing.XL, pady=Spacing.XL)
            title_label = ctk.CTkLabel(
                main_frame, text="匯出模組列表", font=FontManager.get_font(size=FontSize.HEADING_XLARGE, weight="bold")
            )
            title_label.pack(pady=(Spacing.SMALL_PLUS, Spacing.XL))
            fmt_frame = ctk.CTkFrame(main_frame)
            fmt_frame.pack(fill="x", pady=(0, Spacing.LARGE_MINUS))
            fmt_inner = ctk.CTkFrame(fmt_frame, fg_color="transparent")
            fmt_inner.pack(fill="x", padx=Spacing.XL, pady=Spacing.LARGE_MINUS)
            ctk.CTkLabel(
                fmt_inner, text="選擇匯出格式:", font=FontManager.get_font(size=FontSize.HEADING_MEDIUM, weight="bold")
            ).pack(side="left", padx=(0, Spacing.LARGE_MINUS))
            fmt_var = tkinter.StringVar(value="text")
            text_radio = ctk.CTkRadioButton(
                fmt_inner, text="純文字", variable=fmt_var, value="text", font=FontManager.get_font(size=FontSize.LARGE)
            )
            text_radio.pack(side="left", padx=Spacing.TINY)
            json_radio = ctk.CTkRadioButton(
                fmt_inner, text="JSON", variable=fmt_var, value="json", font=FontManager.get_font(size=FontSize.LARGE)
            )
            json_radio.pack(side="left", padx=Spacing.TINY)
            html_radio = ctk.CTkRadioButton(
                fmt_inner, text="HTML", variable=fmt_var, value="html", font=FontManager.get_font(size=FontSize.LARGE)
            )
            html_radio.pack(side="left", padx=Spacing.TINY)
            preview_frame = ctk.CTkFrame(main_frame)
            preview_frame.pack(fill="both", expand=True, pady=(0, Spacing.LARGE_MINUS))
            preview_label = ctk.CTkLabel(
                preview_frame, text="預覽:", font=FontManager.get_font(size=FontSize.HEADING_MEDIUM, weight="bold")
            )
            preview_label.pack(anchor="w", padx=Spacing.LARGE_MINUS, pady=(Spacing.LARGE_MINUS, Spacing.TINY))
            text_widget = ctk.CTkTextbox(
                preview_frame,
                font=FontManager.get_font(size=FontSize.LARGE),
                height=Sizes.PREVIEW_TEXTBOX_HEIGHT,
                wrap="word",
            )
            text_widget.pack(fill="both", expand=True, padx=Spacing.LARGE_MINUS, pady=(0, Spacing.LARGE_MINUS))

            def update_preview(*_):
                manager = self.mod_manager
                if manager is None:
                    text_widget.delete("1.0", "end")
                    text_widget.insert("1.0", "模組管理器尚未初始化，無法匯出列表。")
                    return
                export_text = manager.export_mod_list(fmt_var.get())
                text_widget.delete("1.0", "end")
                text_widget.insert("1.0", export_text)

            fmt_var.trace_add("write", update_preview)
            update_preview()
            btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
            btn_frame.pack(pady=(0, Spacing.SMALL_PLUS))

            def do_save():
                manager = self.mod_manager
                if manager is None:
                    UIUtils.show_error("錯誤", "模組管理器未初始化", dialog)
                    return
                fmt = fmt_var.get()
                ext = {"text": "txt", "json": "json", "html": "html"}[fmt]
                server_name = getattr(self.current_server, "name", "server")
                default_name = f"{server_name}_模組列表.{ext}"
                file_path = filedialog.asksaveasfilename(
                    title="儲存模組列表",
                    defaultextension=f".{ext}",
                    filetypes=[("所有檔案", "*.*"), ("純文字", "*.txt"), ("JSON", "*.json"), ("HTML", "*.html")],
                    initialfile=default_name,
                )
                if file_path:
                    export_text = manager.export_mod_list(fmt)
                    PathUtils.write_text_file(Path(file_path), export_text)
                    try:
                        result = UIUtils.ask_yes_no_cancel(
                            "匯出成功",
                            f"已儲存: {file_path}\n\n是否要立即開啟匯出的檔案？",
                            parent=dialog,
                            show_cancel=False,
                        )
                        if result:
                            UIUtils.open_external(file_path)
                    except Exception as e:
                        logger.bind(component="").error(
                            f"開啟檔案失敗: {e}\n{traceback.format_exc()}", "ModManagementFrame"
                        )
                        UIUtils.show_error("開啟檔案失敗", f"無法開啟檔案: {e}", parent=dialog)

            save_btn = ctk.CTkButton(
                btn_frame,
                text="儲存到檔案",
                command=do_save,
                font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
                fg_color=Colors.BUTTON_PRIMARY,
                hover_color=Colors.BUTTON_PRIMARY_HOVER,
                width=FontManager.get_dpi_scaled_size(180),
                height=int(40 * FontManager.get_scale_factor()),
            )
            save_btn.pack(side="left", padx=(0, Spacing.SMALL_PLUS))
            close_btn = ctk.CTkButton(
                btn_frame,
                text="關閉",
                command=dialog.destroy,
                font=FontManager.get_font(size=FontSize.LARGE),
                fg_color=Colors.BUTTON_SECONDARY,
                hover_color=Colors.BUTTON_SECONDARY_HOVER,
                width=FontManager.get_dpi_scaled_size(150),
                height=int(40 * FontManager.get_scale_factor()),
            )
            close_btn.pack(side="left")
            dialog.bind("<Escape>", lambda _e: dialog.destroy())
            DialogUtils.schedule_toplevel_layout_refresh(
                dialog,
                min_width=Sizes.DIALOG_LARGE_WIDTH,
                min_height=Sizes.DIALOG_LARGE_HEIGHT,
                max_width=FontManager.get_dpi_scaled_size(1280),
                max_height=FontManager.get_dpi_scaled_size(960),
                parent=self.parent,
            )
        except Exception as e:
            logger.error(f"匯出對話框錯誤: {e}\n{traceback.format_exc()}")
            UIUtils.show_error("匯出對話框錯誤", str(e), self.parent)

    def create_status_bar(self) -> None:
        """建立狀態列"""
        status_frame = ctk.CTkFrame(self.main_frame, height=int(40 * FontManager.get_scale_factor()))
        status_frame.pack(side="bottom", fill="x", padx=Spacing.XL, pady=(0, Spacing.XL))
        status_frame.pack_propagate(False)
        self.status_label = ctk.CTkLabel(
            status_frame,
            text="請選擇伺服器開始管理模組",
            font=FontManager.get_font(size=FontSize.HEADING_MEDIUM),
            text_color=Colors.TEXT_SECONDARY,
        )
        self.status_label.pack(side="left", padx=Spacing.SMALL_PLUS, pady=int(6 * FontManager.get_scale_factor()))
        self.progress_var = tkinter.DoubleVar()
        self.progress_bar = ctk.CTkProgressBar(
            status_frame,
            variable=self.progress_var,
            width=FontManager.get_dpi_scaled_size(300),
            height=int(20 * FontManager.get_scale_factor()),
            progress_color=Colors.PROGRESS_ACCENT,
            fg_color=Colors.PROGRESS_TRACK,
        )
        self.progress_bar.pack(side="right", padx=Spacing.SMALL_PLUS, pady=int(6 * FontManager.get_scale_factor()))

    def load_servers(self) -> None:
        """載入伺服器列表"""
        try:
            servers = list(self.server_manager.servers.values())
            server_names = [server.name for server in servers]
            if not server_names:
                self.server_combo.configure(values=[""])
                self.server_var.set("")
                self.current_server = None
                self.mod_manager = None
                if hasattr(self, "local_mods"):
                    self.local_mods = []
                if hasattr(self, "refresh_local_list"):
                    self.refresh_local_list()
                self._refresh_online_filter_hint()
            else:
                self.server_combo.configure(values=server_names)
                if server_names:
                    self.server_var.set(server_names[0])
                self.on_server_changed()
        except Exception as e:
            logger.bind(component="").error(f"載入伺服器列表失敗: {e}\n{traceback.format_exc()}", "ModManagementFrame")
            UIUtils.show_error("錯誤", f"載入伺服器列表失敗: {e}", self.parent)

    def on_server_changed(self, _event=None) -> None:
        """切換目前伺服器時重新載入相關模組資料。

        Args:
            _event: 事件繫結傳入的事件物件，未使用。
        """
        server_name = self.server_var.get()
        if not server_name:
            return
        try:
            servers = list(self.server_manager.servers.values())
            selected_server = None
            for server in servers:
                if server.name == server_name:
                    selected_server = server
                    break
            if not selected_server:
                return
            self.current_server = selected_server
            self.mod_manager = ModManager(selected_server.path, selected_server)
            self._last_online_request = None
            self._refresh_online_filter_hint()
            self.load_local_mods()
            if self._is_browse_tab_active():
                self._load_online_mods(force=True, show_warning=False)
            if self.on_server_selected:
                self.on_server_selected(server_name)
        except Exception as e:
            logger.error(f"切換伺服器失敗: {e}\n{traceback.format_exc()}")
            UIUtils.show_error("錯誤", f"切換伺服器失敗: {e}", self.parent)

    def load_local_mods(self) -> None:
        """載入本地模組，並同步清空增強 cache，確保顯示一致，並顯示進度條"""
        self._get_local_mod_list_presenter().load_local_mods()

    def enhance_local_mods(self) -> None:
        """本地模組增強資訊，查詢完自動刷新列表（可選）"""
        self._get_local_mod_list_presenter().enhance_local_mods()

    def _set_bulk_controls_enabled(self, enabled: bool) -> None:
        """設定批量操作控制元件的啟用/停用狀態

        Args:
            enabled: True 表示啟用，False 表示停用
        """
        self._get_local_mod_list_presenter()._set_bulk_controls_enabled(enabled)

    def toggle_local_mod(self, _event=None) -> None:
        """切換目前選取本地模組的啟用/停用狀態。

        Args:
            _event: 事件繫結傳入的事件物件，未使用。
        """
        self._get_local_mod_list_presenter().toggle_local_mod(_event)

    def filter_local_mods(self, *_args) -> None:
        """篩選本地模組（debounce，避免連續重建 Treeview）。

        Args:
            *_args: 來自事件或 trace callback 的額外參數。
        """
        self._get_local_mod_list_presenter().filter_local_mods(*_args)

    def _run_debounced_local_filter_refresh(self) -> None:
        self._get_local_mod_list_presenter()._run_debounced_local_filter_refresh()

    def show_local_context_menu(self, event) -> None:
        """顯示本地模組右鍵選單。

        Args:
            event: 滑鼠右鍵事件。
        """
        if not self.local_tree:
            return
        tree = self.local_tree
        if not self._select_tree_item_for_context_menu(tree, event):
            return
        selection = tree.selection()
        if not selection:
            return
        menu = tkinter.Menu(self.parent, tearoff=0, font=FontManager.get_font("Microsoft JhengHei", FontSize.LARGE))
        menu.add_command(label="🔄 切換啟用狀態", command=self.toggle_local_mod)
        menu.add_separator()
        menu.add_command(label="📋 複製模組資訊", command=self.copy_mod_info)
        menu.add_command(label="📁 在檔案總管中顯示", command=self.show_in_explorer)
        menu.add_separator()
        menu.add_command(label="🗑️ 刪除模組", command=self.delete_local_mod)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def import_mod_file(self) -> None:
        """匯入模組檔案（委派 ModManager）"""
        if not self.current_server:
            UIUtils.show_warning("警告", "請先選擇伺服器", self.parent)
            return
        filetypes = [("JAR files", "*.jar"), ("All files", "*.*")]
        filename = filedialog.askopenfilename(filetypes=filetypes)
        if filename:
            if not self.mod_manager:
                UIUtils.show_error("錯誤", "模組管理器未初始化", self.parent)
                return
            result = self.mod_manager.import_local_mod_file_result(filename)
            if result.completed:
                UIUtils.show_info("成功", result.message or f"模組已匯入: {Path(filename).name}", self.parent)
                self.load_local_mods()
            else:
                UIUtils.show_error(result.title or "錯誤", result.message or "匯入模組失敗", self.parent)

    def open_mods_folder(self) -> None:
        """開啟模組資料夾"""
        if not self.current_server:
            UIUtils.show_warning("警告", "請先選擇伺服器", self.parent)
            return
        mods_dir = Path(self.current_server.path) / "mods"
        if mods_dir.exists():
            try:
                UIUtils.open_external(mods_dir)
            except Exception as e:
                logger.error(f"開啟模組資料夾失敗: {e}")
        else:
            UIUtils.show_warning("警告", "模組資料夾不存在", self.parent)

    def copy_mod_info(self) -> None:
        """複製模組資訊"""
        if not self.local_tree:
            return
        tree = self.local_tree
        selection = tree.selection()
        if not selection:
            return
        try:
            item = selection[0]
            values = self._get_tree_item_values(tree, item)
            if values and len(values) >= 4:
                info = f"模組名稱: {values[1]}\n版本: {values[2]}\n狀態: {values[0]}\n檔案: {(values[3] if len(values) > 3 else 'N/A')}"
                self.parent.clipboard_clear()
                self.parent.clipboard_append(info)
                if hasattr(self, "status_label") and self.status_label.winfo_exists():
                    self.update_status("模組資訊已複製到剪貼板")
        except Exception as e:
            logger.error(f"複製模組資訊失敗: {e}\n{traceback.format_exc()}")
            if hasattr(self, "status_label") and self.status_label.winfo_exists():
                self.status_label.configure(text=f"複製失敗: {e}")

    def show_in_explorer(self) -> None:
        """在檔案總管中顯示模組"""
        if not self.local_tree:
            return
        tree = self.local_tree
        selection = tree.selection()
        if not selection or not self.current_server:
            return
        try:
            item = selection[0]
            mod_filename = self._get_tree_item_mod_id(tree, item)
            if mod_filename:
                mods_dir = Path(self.current_server.path) / "mods"
                mod_file = None
                for ext in [".jar", ".jar.disabled"]:
                    potential_file = mods_dir / (mod_filename + ext)
                    if potential_file.exists():
                        mod_file = potential_file
                        break
                if mod_file and mod_file.exists():
                    try:
                        UIUtils.reveal_in_explorer(mod_file)
                    except Exception as e:
                        logger.error(f"無法打開檔案總管顯示檔案: {e}")
                    if hasattr(self, "status_label") and self.status_label.winfo_exists():
                        self.status_label.configure(text=f"已在檔案總管中顯示: {mod_file.name}")
                elif hasattr(self, "status_label") and self.status_label.winfo_exists():
                    self.status_label.configure(text="找不到要顯示的模組檔案")
            elif hasattr(self, "status_label") and self.status_label.winfo_exists():
                self.status_label.configure(text="無法識別模組檔案")
        except Exception as e:
            logger.error(f"開啟檔案總管失敗: {e}\n{traceback.format_exc()}")
            if hasattr(self, "status_label") and self.status_label.winfo_exists():
                self.status_label.configure(text=f"開啟檔案總管失敗: {e}")

    def delete_local_mod(self) -> None:
        """刪除目前選取的本地模組檔案（委派 ModManager）"""
        if not self.local_tree:
            return
        tree = self.local_tree
        selection = tree.selection()
        if not selection or not self.current_server:
            return
        selected_mods: list[tuple[str, str]] = []
        seen_mod_ids: set[str] = set()
        for item_id in selection:
            values = self._get_tree_item_values(tree, item_id)
            mod_id = self._get_tree_item_mod_id(tree, item_id)
            if not values or len(values) < 2 or not mod_id:
                continue
            mod_name = self._get_tree_item_mod_name(tree, item_id) or mod_id
            if mod_id in seen_mod_ids:
                continue
            seen_mod_ids.add(mod_id)
            selected_mods.append((mod_id, mod_name))
        if not selected_mods:
            return
        mod_count = len(selected_mods)
        mod_label = selected_mods[0][1] if mod_count == 1 else f"這 {mod_count} 個模組"
        confirm = UIUtils.ask_yes_no_cancel(
            "確認刪除", f"確定要刪除{mod_label}嗎？\n此操作無法復原。", parent=self.parent, show_cancel=False
        )
        if not confirm:
            return
        if not self.mod_manager:
            UIUtils.show_error("錯誤", "模組管理器未初始化", self.parent)
            return
        mod_name_by_id = dict(selected_mods)
        result = self.mod_manager.delete_local_mods_result([mod_id for mod_id, _mod_name in selected_mods])
        deleted_count = result.affected_count
        missing_names = [mod_name_by_id.get(mod_id, mod_id) for mod_id in result.missing_ids]
        if deleted_count > 0:
            self.load_local_mods()
            if hasattr(self, "status_label") and self.status_label.winfo_exists():
                self.status_label.configure(text=f"已刪除 {deleted_count} 個模組")
            if result.completed and len(selected_mods) == 1:
                UIUtils.show_info("成功", f"模組 '{selected_mods[0][1]}' 已刪除", self.parent)
            else:
                summary = result.message or f"已刪除 {deleted_count} 個模組"
                if missing_names:
                    summary += f"\n找不到檔案：{', '.join(missing_names)}"
                if result.partial:
                    UIUtils.show_warning(result.title or "部分成功", summary, self.parent)
                else:
                    UIUtils.show_info("成功", summary, self.parent)
        else:
            if hasattr(self, "status_label") and self.status_label.winfo_exists():
                self.status_label.configure(text=result.message or "刪除失敗")
            UIUtils.show_warning(result.title or "提示", result.message or "沒有成功刪除任何模組", self.parent)

    def get_frame(self) -> ctk.CTkFrame | None:
        """獲取主框架"""
        if hasattr(self, "main_frame") and self.main_frame:
            return self.main_frame
        logger.debug("主框架未初始化")
        return None

    def toggle_select_all(self) -> None:
        """切換全選/取消全選"""
        self._get_local_mod_list_presenter().toggle_select_all()

    def batch_toggle_selected(self) -> None:
        """批量切換選中模組的啟用/停用狀態"""
        self._get_local_mod_list_presenter().batch_toggle_selected()

    def update_selection_status(self) -> None:
        """更新選擇狀態顯示"""
        self._get_local_mod_list_presenter().update_selection_status()

    def on_tree_selection_changed(self, _event=None) -> None:
        """
        本地模組樹狀檢視選擇變更時同步狀態。

        Args:
            _event: 事件繫結傳入的事件物件，未使用。
        """
        self._get_local_mod_list_presenter().on_tree_selection_changed(_event)

    def pack(self, **kwargs) -> None:
        """將主框架以 pack 方式放入父容器。

        Args:
            kwargs: 傳給 pack 的版面配置參數。
        """
        if hasattr(self, "main_frame") and self.main_frame:
            self.main_frame.pack(**kwargs)
        else:
            logger.debug("主框架未初始化，無法打包", "ModManagementFrame")

    def grid(self, **kwargs) -> None:
        """將主框架以 grid 方式放入父容器。

        Args:
            kwargs: 傳給 grid 的版面配置參數。
        """
        if hasattr(self, "main_frame") and self.main_frame:
            self.main_frame.grid(**kwargs)
        else:
            logger.debug("主框架未初始化，無法佈局", "ModManagementFrame")


__all__ = ["ModManagementFrame"]
