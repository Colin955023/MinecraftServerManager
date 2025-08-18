#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
建立伺服器頁面
負責建立新 Minecraft 伺服器的使用者介面
Create Server Page
Responsible for the user interface to create a new Minecraft server
"""
# ====== 標準函式庫 ======
from pathlib import Path
from tkinter import filedialog
from typing import Callable
import os
import threading
import psutil
import queue
import webbrowser
import time
import tkinter as tk
import traceback
import customtkinter as ctk
# ====== 專案內部模組 ======
from ..core.loader_manager import LoaderManager
from ..core.server_manager import ServerManager
from ..core.version_manager import MinecraftVersionManager
from ..models import ServerConfig
from ..utils import java_utils
from ..utils.font_manager import font_manager, get_font
from ..utils.log_utils import LogUtils
from ..utils.ui_utils import ProgressDialog, UIUtils
from .custom_dropdown import CustomDropdown

# ====== 主要 UI Frame 類別 ======
class CreateServerFrame(ctk.CTkFrame):
    """
    建立伺服器頁面
    Create Server Page
    """

    @staticmethod
    def get_system_memory_mb() -> int:
        """
        獲取系統記憶體容量 (MB)
        Get system memory capacity in MB
        """
        try:
            return psutil.virtual_memory().total // (1024**2)
        except Exception as e:
            LogUtils.debug(f"無法獲取系統記憶體資訊: {e}", "CreateServerFrame")
            UIUtils.show_error("錯誤", f"無法獲取系統記憶體資訊: {e}", topmost=True)
            return 0

    def update_memory_warning(self) -> None:
        """
        更新記憶體使用警告標籤
        Update memory usage warning label
        """
        try:
            max_memory_str = self.max_memory_var.get().strip()
            if not max_memory_str:
                self.memory_warning_label.configure(text="")
                return

            max_memory = int(max_memory_str)
            system_memory = self.get_system_memory_mb()
            half_system_memory = system_memory // 2

            if max_memory > system_memory:
                warning_text = f"⚠️ 警告：設定記憶體 ({max_memory}MB) 超過系統總記憶體 ({system_memory}MB)"
                self.memory_warning_label.configure(text=warning_text, text_color=("red", "red"))
            elif max_memory > half_system_memory:
                warning_text = f"⚠️ 警告：設定記憶體 ({max_memory}MB) 超過系統記憶體的一半 ({half_system_memory}MB)"
                self.memory_warning_label.configure(text=warning_text, text_color=("red", "red"))
            else:
                self.memory_warning_label.configure(text="")
        except ValueError:
            # 如果輸入不是數字，清除警告
            self.memory_warning_label.configure(text="")
        except Exception as e:
            LogUtils.debug(f"更新記憶體警告失敗: {e}", "CreateServerFrame")
            UIUtils.show_error("錯誤", f"更新記憶體警告失敗: {e}", self.winfo_toplevel())

    def create_java_path_field(self, parent, row) -> None:
        """
        建立 Java 路徑欄位（可手動輸入/瀏覽）
        Create Java path field (manual input/browse)

        Args:
            parent (ctk.CTkFrame): 父容器
            row (int): 行號
        """
        ctk.CTkLabel(parent, text="Java 執行檔路徑 (可選):", font=get_font(size=12, weight="bold")).grid(
            row=row, column=0, sticky="w", pady=5
        )

        self.java_path_var = tk.StringVar(value="")
        java_path_entry = ctk.CTkEntry(parent, textvariable=self.java_path_var, font=get_font(size=11), width=300)
        java_path_entry.grid(row=row, column=1, sticky="ew", padx=(15, 0), pady=5)

        def browse_java():
            path = filedialog.askopenfilename(
                title="選擇 javaw.exe", filetypes=[("Java 執行檔", "javaw.exe"), ("所有檔案", "*")]
            )
            if path:
                self.java_path_var.set(path)

        browse_btn = UIUtils.create_styled_button(parent, "瀏覽...", browse_java, "small")
        browse_btn.grid(row=row, column=2, padx=(8, 0), pady=5)

        # 自動偵測按鈕
        def auto_detect():
            # 取得目前 UI 選擇的 mc_version、loader_type、loader_version
            mc_version = self.mc_version_var.get() if hasattr(self, "mc_version_var") else None
            loader_type = self.loader_type_var.get() if hasattr(self, "loader_type_var") else None
            loader_version = self.loader_version_var.get() if hasattr(self, "loader_version_var") else None
            if not mc_version:
                UIUtils.show_warning("Java 偵測", "請先選擇 Minecraft 版本！", self.winfo_toplevel())
                return
            java_path = java_utils.get_best_java_path(mc_version, ask_download=True)
            if java_path:
                java_path_win = os.path.normpath(java_path)
                self.java_path_var.set(java_path_win)

        auto_btn = UIUtils.create_styled_button(parent, "自動偵測", auto_detect, "small")
        auto_btn.grid(row=row, column=3, padx=(8, 0), pady=5)

    # === 1. 初始化與 UI 建立 ===
    def __init__(
        self,
        parent,
        version_manager: MinecraftVersionManager,
        loader_manager: LoaderManager,
        callback: Callable,
        server_manager: ServerManager,
    ):
        super().__init__(parent)
        self.version_manager = version_manager
        self.loader_manager = loader_manager
        self.callback = callback
        self.server_manager = server_manager
        self.versions: list = []
        self.release_versions: list = []

        # 線程安全UI更新佇列
        self.ui_update_queue = queue.Queue()

        self.create_widgets()

        # 啟動UI更新檢查器
        self._start_ui_update_checker()

        # 建立元件後立即開始預載入版本資訊並顯示載入狀態
        self.preload_version_data()

    def _start_ui_update_checker(self) -> None:
        """
        啟動UI更新檢查器，定期檢查佇列中的更新任務
        Start the UI update checker to periodically check for update tasks in the queue.
        """
        self._check_ui_updates()

    def _check_ui_updates(self) -> None:
        """
        檢查UI更新佇列並執行更新任務
        Check the UI update queue and execute update tasks.
        """
        try:
            while True:
                try:
                    # 非阻塞式獲取任務
                    task = self.ui_update_queue.get_nowait()
                    # 執行UI更新任務
                    task()
                except queue.Empty:
                    break
        except Exception as e:
            LogUtils.error(f"UI更新檢查器錯誤: {e}")
            UIUtils.show_error("UI更新檢查器錯誤", f"無法檢查UI更新: {e}", self.winfo_toplevel())

        # 每100ms檢查一次佇列
        self.after(100, self._check_ui_updates)

    def _schedule_ui_update(self, task) -> None:
        """
        排程安全的UI更新
        Schedule UI update tasks in a thread-safe manner.
        """
        try:
            self.ui_update_queue.put(task)
        except Exception as e:
            LogUtils.error(f"排程UI更新失敗: {e}")
            UIUtils.show_error("排程UI更新失敗", f"無法排程UI更新任務: {e}", self.winfo_toplevel())

    def create_widgets(self) -> None:
        """
        建立介面元件
        Create the interface widgets.
        """
        main_container = ctk.CTkFrame(self, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=20, pady=15)

        title_label = ctk.CTkLabel(main_container, text="建立新伺服器", font=get_font(size=24, weight="bold"))
        title_label.pack(pady=(0, 15))

        # EULA 警告框架
        eula_frame = ctk.CTkFrame(main_container, fg_color=("#fffbe6", "#2d2a1f"))
        eula_frame.pack(pady=(0, 12), fill="x")
        eula_frame.grid_columnconfigure(1, weight=1)

        eula_icon = ctk.CTkLabel(eula_frame, text="⚠️", font=get_font(size=18, weight="bold"), text_color="#d97706")
        eula_icon.grid(row=0, column=0, rowspan=2, sticky="nsw", padx=(8, 4), pady=6)

        eula_link = ctk.CTkLabel(
            eula_frame,
            text="請務必閱讀並同意 Minecraft EULA 條款 (點我閱讀)\n點擊建立即表示你同意Minecraft條款，任何違法行為本軟體不負責任",
            font=ctk.CTkFont(
                family="Microsoft JhengHei",
                size=int(14 * font_manager.get_scale_factor()),
                weight="bold",
                underline=True,
            ),
            text_color="#b45309",
            cursor="hand2",
        )
        eula_link.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=6)
        eula_link.bind("<Button-1>", lambda e: webbrowser.open("https://aka.ms/MinecraftEULA"))

        # 內容容器
        content_container = ctk.CTkFrame(main_container, fg_color="transparent")
        content_container.pack(fill="x", expand=False, pady=(0, 8))

        # 建立表單
        self.create_form(content_container)

        # 建立按鈕
        self.create_buttons(main_container)

    def create_form(self, parent) -> None:
        """
        建立表單
        Create the form.
        """
        form_frame = ctk.CTkFrame(parent)
        form_frame.pack(fill="x", pady=(0, 15))

        content_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=20, pady=20)

        self.create_field(content_frame, 0, "伺服器名稱:", "我的伺服器", "server_name")
        self.create_java_path_field(content_frame, 1)
        # 建立模組載入器下拉選單並添加變更事件
        ctk.CTkLabel(content_frame, text="模組載入器:", font=get_font(size=12, weight="bold")).grid(
            row=2, column=0, sticky="w", pady=5
        )

        self.loader_type_var = tk.StringVar(value="Vanilla")
        self.loader_type_combo = CustomDropdown(
            content_frame,
            variable=self.loader_type_var,
            values=["Vanilla", "Fabric", "Forge"],
            command=lambda value: self.update_server_config_ui(),
            width=280,
            state="readonly",
        )
        self.loader_type_combo.grid(row=2, column=1, sticky="ew", padx=(15, 0), pady=5)

        # 添加變更事件處理器，當載入器類型改變時更新載入器版本選單
        self.loader_type_var.trace_add("write", lambda *args: self.update_server_config_ui())

        # 載入器版本下拉選單與 reload 按鈕
        loader_version_row = 3
        ctk.CTkLabel(content_frame, text="載入器版本:", font=get_font(size=12, weight="bold")).grid(
            row=loader_version_row, column=0, sticky="w", pady=5
        )

        # 載入器版本下拉選單容器
        loader_version_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        loader_version_frame.grid(row=loader_version_row, column=1, sticky="ew", padx=(15, 0), pady=5)

        self.loader_version_var = tk.StringVar(value="無")
        self.loader_version_combo = CustomDropdown(
            loader_version_frame, variable=self.loader_version_var, values=["無"], width=280, state="disabled"
        )
        self.loader_version_combo.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # 載入器 reload 按鈕
        loader_reload_btn = UIUtils.create_styled_button(
            loader_version_frame, text="⟳", command=self.reload_loader_versions, button_type="small"
        )
        loader_reload_btn.pack(side="left")

        version_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        version_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=10)

        ctk.CTkLabel(version_frame, text="Minecraft 版本:", font=get_font(size=12, weight="bold")).pack(anchor="w")
        # Minecraft 版本下拉選單與滑桿
        mc_version_frame = ctk.CTkFrame(version_frame, fg_color="transparent")
        mc_version_frame.pack(fill="x")

        # 版本下拉選單
        self.mc_version_var = tk.StringVar()
        self.mc_version_combo = CustomDropdown(
            mc_version_frame,
            variable=self.mc_version_var,
            values=["載入中..."],
            command=self.update_server_config_ui,
            width=200,
            state="readonly",
        )
        self.mc_version_combo.pack(side="left", fill="x", expand=True, padx=(0, 8))

        mc_reload_btn = UIUtils.create_styled_button(
            mc_version_frame, text="⟳", command=self.reload_mc_versions, button_type="small"
        )
        mc_reload_btn.pack(side="left")
        # 記憶體設定區域
        memory_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        memory_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=10)

        ctk.CTkLabel(memory_frame, text="記憶體設定 (MB):", font=get_font(size=12, weight="bold")).pack(anchor="w")

        memory_input_frame = ctk.CTkFrame(memory_frame, fg_color="transparent")
        memory_input_frame.pack(fill="x", pady=(5, 0))

        # 最小記憶體
        min_memory_frame = ctk.CTkFrame(memory_input_frame, fg_color="transparent")
        min_memory_frame.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkLabel(
            min_memory_frame, text="最小記憶體 (選填):", font=get_font(size=12), text_color=("gray60", "gray50")
        ).pack(anchor="w")

        self.min_memory_var = tk.StringVar(value="1024")
        self.min_memory_entry = ctk.CTkEntry(
            min_memory_frame, textvariable=self.min_memory_var, font=get_font(size=12), width=120
        )
        self.min_memory_entry.pack(fill="x", pady=(2, 0))

        # 最大記憶體
        max_memory_frame = ctk.CTkFrame(memory_input_frame, fg_color="transparent")
        max_memory_frame.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            max_memory_frame, text="最大記憶體 (必填):", font=get_font(size=12), text_color=("gray60", "gray50")
        ).pack(anchor="w")

        self.max_memory_var = tk.StringVar(value="2048")
        self.max_memory_entry = ctk.CTkEntry(
            max_memory_frame, textvariable=self.max_memory_var, font=get_font(size=12), width=120
        )
        self.max_memory_entry.pack(fill="x", pady=(2, 0))

        # 綁定記憶體輸入變更事件
        self.max_memory_var.trace_add("write", lambda *args: self.update_memory_warning())

        # 記憶體提示
        memory_tip = ctk.CTkLabel(
            memory_frame,
            text="建議：最大 2048MB (最低) | 4096MB (一般) | 8192MB (多人遊戲)",
            font=get_font(size=12),
            text_color=("gray50", "gray60"),
        )
        memory_tip.pack(anchor="w", pady=(5, 0))

        # 記憶體警告標籤
        self.memory_warning_label = ctk.CTkLabel(
            memory_frame, text="", font=get_font(size=11), text_color=("red", "red"), wraplength=400
        )
        self.memory_warning_label.pack(anchor="w", pady=(3, 0))
        content_frame.columnconfigure(1, weight=1)

    # === 載入狀態管理 ===
    def set_loading_state(self, combo, var=None, message="載入中...") -> None:
        """
        設定下拉選單的載入狀態
        Set the loading state for the dropdown menu.
        """
        combo.configure(values=[message])
        combo.set(message)
        if var:
            var.set(message)
        combo.configure(state="disabled")

    def set_error_state(self, combo, var=None, message="載入失敗") -> None:
        """
        設定下拉選單的錯誤狀態
        Set the error state for the dropdown menu.
        """
        combo.configure(values=[message])
        combo.set(message)
        if var:
            var.set(message)
        combo.configure(state="disabled")

    def set_no_versions_state(self, combo, var=None, message="無可用版本") -> None:
        """
        設定下拉選單的無版本狀態
        Set the no versions state for the dropdown menu.
        """
        combo.configure(values=[message])
        combo.set(message)
        if var:
            var.set(message)
        combo.configure(state="disabled")

    def preload_version_data(self) -> None:
        """
        預載入版本資訊並管理載入狀態
        preload version data and manage loading state
        """
        # 立即設定載入狀態
        self.set_loading_state(self.mc_version_combo, self.mc_version_var, "正在載入 MC 版本...")
        self.set_loading_state(self.loader_version_combo, self.loader_version_var, "等待 MC 版本選擇...")

        def preload_all_versions():
            try:
                # 載入 Minecraft 版本
                versions = self.version_manager.get_versions()

                # 在主執行緒中更新 MC 版本
                def update_mc_versions():
                    try:
                        self.update_versions(versions)
                        # MC 版本載入完成後，提示載入器版本已就緒
                        self.set_loading_state(
                            self.loader_version_combo, self.loader_version_var, "請先選擇載入器類型..."
                        )
                    except Exception:
                        self.set_error_state(self.mc_version_combo, self.mc_version_var, "MC 版本載入失敗")
                        self.set_error_state(self.loader_version_combo, self.loader_version_var, "載入器版本不可用")

                # 使用線程安全的UI更新機制
                self._schedule_ui_update(update_mc_versions)

                # 預載入 Fabric 和 Forge 版本資訊（背景處理）
                try:
                    self.loader_manager.preload_fabric_versions(parent=self.master)
                    self.loader_manager.preload_forge_versions(parent=self.master)
                except Exception as e:
                    LogUtils.info(f"預載入載入器版本失敗: {e}", "CreateServerFrame")

            except Exception as e:
                LogUtils.error(f"預載入版本資訊失敗: {e}", "CreateServerFrame")

                def show_error():
                    self.set_error_state(self.mc_version_combo, self.mc_version_var, "載入失敗")
                    self.set_error_state(self.loader_version_combo, self.loader_version_var, "載入失敗")

                # 使用線程安全的UI更新機制
                self._schedule_ui_update(show_error)

        # 在背景執行緒中執行預載入
        threading.Thread(target=preload_all_versions, daemon=True).start()

    def reload_mc_versions(self) -> None:
        """
        重新載入 Minecraft 版本（清除快取並從 API 取得最新），狀態顯示在下拉選單中
        reload Minecraft versions (clear cache and fetch latest from API), status displayed in dropdown
        """

        def do_reload():
            try:
                # 設定載入狀態
                self.set_loading_state(self.mc_version_combo)

                # 刪除快取檔案並重新獲取
                if os.path.exists(self.version_manager.cache_file):
                    os.remove(self.version_manager.cache_file)
                versions = self.version_manager.fetch_versions()

                # 更新版本列表並預設選擇最新版本
                self._schedule_ui_update(lambda: self.update_versions(versions))
                self.mc_version_combo.configure(state="readonly")

            except Exception as e:
                print(f"載入 MC 版本失敗: {e}")
                self._schedule_ui_update(lambda: self.set_error_state(self.mc_version_combo))

        threading.Thread(target=do_reload, daemon=True).start()

    def reload_loader_versions(self) -> None:
        """
        重新載入載入器版本（清除快取並從 API 取得最新），狀態顯示在下拉選單中
        reload loader versions (clear cache and fetch latest from API), status displayed in dropdown
        """
        loader_type = self.loader_type_var.get()
        mc_version = self.mc_version_var.get()
        if not loader_type or not mc_version or loader_type == "Vanilla":
            return

        def do_reload():
            try:
                # 設定載入狀態
                self.set_loading_state(self.loader_version_combo, self.loader_version_var)

                # 先清空 cache 再重新取得
                if loader_type.lower() == "fabric":
                    self.loader_manager.clear_fabric_cache(parent=self.master)
                    self.loader_manager.preload_fabric_versions()
                elif loader_type.lower() == "forge":
                    self.loader_manager.clear_forge_cache(parent=self.master)
                    self.loader_manager.preload_forge_versions()

                # 只從 cache 讀取
                if loader_type.lower() == "fabric":
                    versions = self.loader_manager.get_compatible_fabric_versions(mc_version)
                elif loader_type.lower() == "forge":
                    versions = self.loader_manager.get_compatible_forge_versions(mc_version)
                else:
                    versions = []

                # 更新 UI
                def update_ui():
                    try:
                        if (
                            not hasattr(self.loader_version_combo, "winfo_exists")
                            or not self.loader_version_combo.winfo_exists()
                        ):
                            return
                        if versions:
                            version_names = [v.version if hasattr(v, "version") else v for v in versions]
                            self.loader_version_combo.configure(values=version_names)
                            # 預設選擇最新版本（第一個）
                            if version_names:
                                self.loader_version_combo.set(version_names[0])
                                self.loader_version_var.set(version_names[0])  # 同時更新變數
                            # 重新啟用下拉選單
                            self.loader_version_combo.configure(state="readonly")
                        else:
                            self.set_no_versions_state(self.loader_version_combo, self.loader_version_var)
                    except Exception:
                        self.set_error_state(self.loader_version_combo, self.loader_version_var)

                self._schedule_ui_update(update_ui)
            except Exception:
                self._schedule_ui_update(
                    lambda: self.set_error_state(self.loader_version_combo, self.loader_version_var)
                )

        threading.Thread(target=do_reload, daemon=True).start()

    def create_field(self, parent, row, label_text, default_value, var_name) -> tuple:
        """
        建立文字輸入欄位
        Create a text input field.

        Args:
            parent: 父容器
            row: 行號
            label_text: 標籤文字
            default_value: 預設值
            var_name: 變數名稱
        """
        ctk.CTkLabel(parent, text=label_text, font=get_font(size=12, weight="bold")).grid(
            row=row, column=0, sticky="w", pady=5
        )

        var = tk.StringVar(value=default_value)
        setattr(self, f"{var_name}_var", var)

        entry = ctk.CTkEntry(parent, textvariable=var, font=get_font(size=12), width=300)
        entry.grid(row=row, column=1, sticky="ew", padx=(15, 0), pady=5)
        setattr(self, f"{var_name}_entry", entry)
        return var, entry

    def create_buttons(self, parent) -> None:
        """
        建立按鈕
        Create buttons.

        Args:
            parent: 父容器
        """
        # 按鈕容器
        button_container = ctk.CTkFrame(parent, fg_color="transparent")
        button_container.pack(fill="x", side="bottom")

        # 按鈕框架
        button_frame = ctk.CTkFrame(button_container, fg_color="transparent")
        button_frame.pack(anchor="e")

        # 使用統一的按鈕建立方法
        self.create_button = UIUtils.create_styled_button(
            button_frame, text="建立伺服器", command=self.create_server, button_type="primary", width=140, height=40
        )
        self.create_button.pack(side="left", padx=(0, 15))

        reset_button = UIUtils.create_styled_button(
            button_frame, text="重設表單", command=self.reset_form, button_type="secondary", width=120, height=40
        )
        reset_button.pack(side="left")

    def reset_form(self):
        """
        重設表單到預設值
        Reset the form to default values.
        """
        try:
            if hasattr(self, "release_versions") and self.release_versions:
                latest_version = self.release_versions[0].get("id", "未知版本")
                self.server_name_var.set(latest_version)
            else:
                self.server_name_var.set("我的伺服器")
            self.java_path_var.set("")  # 清空 Java 路徑
            self.loader_type_var.set("Vanilla")
            self.loader_version_var.set("無")
            self.loader_version_combo.configure(values=["無"])
            # CustomDropdown 在設定 "無" 時會自動處理狀態
            if hasattr(self, "mc_version_combo") and self.mc_version_combo.cget("values"):
                version_list = list(self.mc_version_combo.cget("values"))
                if version_list:
                    self.mc_version_var.set(version_list[0])
            self.update_version_list()
            self.min_memory_var.set("1024")
            self.max_memory_var.set("2048")
            UIUtils.show_info("重設完成", "表單已重設為預設值", self.winfo_toplevel())
        except Exception as e:
            UIUtils.show_error("重設失敗", f"重設表單時發生錯誤：\n{str(e)}", self.winfo_toplevel())

    # === 2. 伺服器版本/載入器相關 ===
    def update_versions(self, versions: list) -> None:
        """
        更新版本列表，並預設選擇最新版本
        Update the version list and default to the latest version.

        Args:
            versions: 版本列表
        """
        self.versions = versions
        self.release_versions = versions

        # 更新版本選項
        self.update_version_list()
        # 設定預設伺服器名稱為最新版本號
        if self.release_versions:
            latest_version = self.release_versions[0].get("id")
            # 只有在當前名稱是預設值時才更新
            if self.server_name_var.get() in ["我的伺服器", ""]:
                self.server_name_var.set(latest_version)

    def update_version_list(self) -> None:
        """
        更新版本列表顯示，並預設選擇最新版本
        只顯示穩定版且 server_url 不為 null 的版本
        Update the version list display and default to the latest version.
        Only show release versions with non-null server_url.
        """
        if not hasattr(self, "versions") or not self.versions:
            self.mc_version_combo.configure(values=["載入中..."])
            self.mc_version_var.set("載入中...")
            return

        # 只顯示穩定版且 server_url 不為 null 的版本
        display_versions = [v for v in self.release_versions if v.get("server_url") is not None]

        if not display_versions:
            self.mc_version_combo.configure(values=["無可用版本"], state="disabled")
            self.mc_version_var.set("無可用版本")
            return

        version_names = [v.get("id") for v in display_versions]

        self.mc_version_combo.configure(values=version_names, state="readonly")  # 啟用下拉選單

        # 從第一項下拉選單開始，而非最新版本
        if display_versions:
            first_version = display_versions[0].get("id")
            self.mc_version_var.set(first_version)

        self.update_server_config_ui()

    def update_server_config_ui(self, event=None) -> None:
        """
        根據載入器類型與 Minecraft 版本自動更新伺服器名稱與載入器版本選單
        Update server name and loader version combo based on loader type and Minecraft version.
        """
        mc_version = self.mc_version_var.get()
        loader_type = self.loader_type_var.get()
        name = self.server_name_var.get()
        auto_names = ["我的伺服器", "", f"Fabric {mc_version}", f"Forge {mc_version}", f"{mc_version}"]
        # 取得舊的 Minecraft 版本（用於自動更新伺服器名稱）
        old_version = getattr(self, "old_mc_version", None)
        # 記錄目前選擇的版本，供下次變更時使用
        self.old_mc_version = mc_version
        # 自動命名伺服器名稱
        if name in auto_names:
            if loader_type == "Vanilla":
                self.server_name_var.set(f"{mc_version}")
            elif loader_type == "Fabric":
                self.server_name_var.set(f"Fabric {mc_version}")
            elif loader_type == "Forge":
                self.server_name_var.set(f"Forge {mc_version}")
        # 若 server_name 包含 old_version，則自動替換為 mc_version
        elif old_version and (old_version in name):
            self.server_name_var.set(name.replace(old_version, mc_version))
        # 載入器版本選單狀態與載入
        if loader_type == "Vanilla":
            self.loader_version_combo.configure(values=["無"], state="disabled")
            self.loader_version_combo.set("無")
            self.loader_version_var.set("無")  # 同時更新變數
        else:
            # 確保 fabric/forge 切換時載入器版本選單變成可用狀態
            # 先設定為可用狀態，讓使用者看到載入中的訊息
            self.loader_version_combo.configure(state="normal")
            # 防止重複載入
            if not mc_version:
                return
            current_key = f"{loader_type}_{mc_version}"
            if hasattr(self, "_loading_key") and self._loading_key == current_key:
                return
            self._loading_key = current_key
            # 在背景執行緒中載入載入器版本
            threading.Thread(target=self.load_loader_versions, args=(loader_type, mc_version), daemon=True).start()

    def load_loader_versions(self, loader_type: str, mc_version: str) -> None:
        """
        載入載入器版本，並預設選擇最新版本（使用預載入的快取資料）
        Load loader versions based on the selected loader type and Minecraft version,
        defaulting to the latest version (using pre-loaded cached data).

        Args:
            loader_type: 載入器類型
            mc_version: Minecraft 版本
        """
        try:
            # 先設定載入狀態
            def set_loading():
                if self.loader_version_combo.winfo_exists():
                    self.set_loading_state(
                        self.loader_version_combo, self.loader_version_var, f"正在載入 {loader_type} 版本..."
                    )

            self._schedule_ui_update(set_loading)

            versions = []
            if loader_type.lower() == "fabric":
                # 直接從快取獲取版本，速度更快
                versions = self.loader_manager.get_compatible_fabric_versions(mc_version)
            elif loader_type.lower() == "forge":
                # 直接從快取獲取版本，速度更快
                versions = self.loader_manager.get_compatible_forge_versions(mc_version)

            # 更新 UI
            def update_ui():
                try:
                    if not self.loader_version_combo.winfo_exists():
                        return
                    # 僅當 loader_type 和 mc_version 沒被快速切換時才更新
                    current_type = self.loader_type_var.get()
                    current_version = self.mc_version_var.get()
                    if loader_type != current_type or mc_version != current_version:
                        # 已被快速切換，這次結果不套用
                        return

                    if versions:
                        version_names = [v.version for v in versions]
                        self.loader_version_combo.configure(values=version_names, state="normal")  # 明確設定為可用
                        # 預設選擇最新版本（第一個）
                        if version_names:
                            self.loader_version_combo.set(version_names[0])
                            self.loader_version_var.set(version_names[0])  # 同時更新變數
                    else:
                        self.set_no_versions_state(self.loader_version_combo, self.loader_version_var)

                    # 清除載入標記
                    if hasattr(self, "_loading_key"):
                        delattr(self, "_loading_key")
                except Exception as e:
                    LogUtils.error(f"更新載入器版本 UI 失敗: {e}", "CreateServerFrame")
                    if hasattr(self, "_loading_key"):
                        delattr(self, "_loading_key")

            self._schedule_ui_update(update_ui)
        except Exception as e:
            LogUtils.error(f"載入載入器版本失敗: {e}", "CreateServerFrame")

            def handle_error():
                try:
                    if self.loader_version_combo.winfo_exists():
                        self.set_error_state(self.loader_version_combo, self.loader_version_var)
                except Exception:
                    pass
                if hasattr(self, "_loading_key"):
                    delattr(self, "_loading_key")

            self._schedule_ui_update(handle_error)

    def validate_form(self) -> bool:
        """
        驗證表單
        Validate the form inputs, including server name duplication.
        """
        # 檢查伺服器名稱
        server_name = self.server_name_var.get().strip()
        if not server_name:
            UIUtils.show_error("錯誤", "請輸入伺服器名稱", self.winfo_toplevel())
            return False
        # 驗證名稱不可重複（對比 servers 目錄下所有資料夾名稱）
        servers_root = self.server_manager.servers_root
        if (servers_root / server_name).exists():
            UIUtils.show_error(
                "名稱重複", f"伺服器名稱 '{server_name}' 已存在於伺服器資料夾，請換一個名稱。", self.winfo_toplevel()
            )
            return False
        # 檢查名稱是否已存在於 config
        if self.server_manager.server_exists(server_name):
            if not UIUtils.ask_yes_no_cancel(
                "名稱衝突",
                f"伺服器名稱 '{server_name}' 已存在於設定。是否覆蓋?",
                self.winfo_toplevel(),
                show_cancel=False,
            ):
                return False
        # 檢查 Minecraft 版本
        if not self.mc_version_var.get():
            UIUtils.show_error("錯誤", "請選擇 Minecraft 版本", self.winfo_toplevel())
            return False
        # 檢查最大記憶體
        max_memory = self.max_memory_var.get().strip()
        if not max_memory:
            UIUtils.show_error("錯誤", "請輸入最大記憶體", self.winfo_toplevel())
            return False
        try:
            max_mem_int = int(max_memory)
            if max_mem_int < 1024:
                UIUtils.show_error("錯誤", "最大記憶體不能少於 1024MB", self.winfo_toplevel())
                return False
            # 檢查最大記憶體是否超過系統記憶體容量
            system_memory = self.get_system_memory_mb()
            if max_mem_int >= system_memory:
                UIUtils.show_error(
                    "記憶體超出限制",
                    f"最大記憶體 ({max_mem_int}MB) 不能等於或超過系統記憶體容量 ({system_memory}MB)\n"
                    f"已自動調整為 {system_memory - 1}MB",
                    self.winfo_toplevel(),
                )
                # 自動調整記憶體設定到 system_memory-1
                self.max_memory_var.set(str(system_memory - 1))
                return False
        except ValueError:
            UIUtils.show_error("錯誤", "最大記憶體必須是數字", self.winfo_toplevel())
            return False
        # 檢查最小記憶體（如果有設定）
        min_memory = self.min_memory_var.get().strip()
        if min_memory:
            try:
                min_mem_int = int(min_memory)
                if min_mem_int < 1024:
                    UIUtils.show_error("錯誤", "最小記憶體不能少於 1024MB", self.winfo_toplevel())
                    return False
                if min_mem_int >= max_mem_int:
                    UIUtils.show_error("錯誤", "最小記憶體必須小於最大記憶體", self.winfo_toplevel())
                    return False
            except ValueError:
                UIUtils.show_error("錯誤", "最小記憶體必須是數字", self.winfo_toplevel())
                return False
        return True

    # === 4. 伺服器建立主流程 ===
    def create_server(self):
        """
        建立伺服器
        Create the server.
        """
        if not self.validate_form():
            return
        # 準備配置
        min_memory = self.min_memory_var.get().strip()
        max_memory = self.max_memory_var.get().strip()
        # 自動命名伺服器名稱
        name = self.server_name_var.get().strip()
        loader_type = self.loader_type_var.get()
        mc_version = self.mc_version_var.get()
        if name in ["", "我的伺服器"]:
            if loader_type == "Vanilla":
                name = f"{mc_version}"
            elif loader_type == "Fabric":
                name = f"Fabric {mc_version}"
            elif loader_type == "Forge":
                name = f"Forge {mc_version}"
            self.server_name_var.set(name)
        config = ServerConfig(
            name=name,
            minecraft_version=mc_version,
            loader_type=loader_type,
            loader_version=self.loader_version_var.get() if loader_type != "Vanilla" else "",
            memory_max_mb=int(max_memory),
            memory_min_mb=int(min_memory) if min_memory else None,
            path="",  # 會在 ServerManager 中設定
            eula_accepted=True,  # 總是自動接受 EULA
        )
        # 在背景執行緒中建立伺服器
        threading.Thread(target=self.create_server_async, args=(config,), daemon=True).start()

    def create_server_async(self, config: ServerConfig) -> None:
        """
        非同步建立伺服器 - 只負責互動與下載，所有檔案/資料夾/屬性/啟動腳本交由 server_manager
        Asynchronous server creation - only responsible for UI interaction and download, all file/folder/properties/launch handled by server_manager.

        Args:
            config: 伺服器配置
        """
        parent_window = self.winfo_toplevel()  # 捕獲父視窗引用
        progress_dialog = None
        try:
            # 建立進度對話框
            def create_progress():
                nonlocal progress_dialog
                progress_dialog = ProgressDialog(parent_window, "正在建立伺服器")

            self._schedule_ui_update(create_progress)
            # 等待進度對話框建立
            while progress_dialog is None:
                time.sleep(0.1)
            # 步驟 1：建立伺服器目錄結構與初始化（含 server.properties）
            if not progress_dialog.update_progress(5, "建立伺服器目錄結構..."):
                return
            success = self.server_manager.create_server(config)
            if not success:
                LogUtils.debug(f"建立伺服器基礎結構失敗 config: {config}", "CreateServerFrame")
                progress_dialog.close()
                raise Exception("建立伺服器基礎結構失敗")
            # 檢查 config 欄位
            if not config.loader_type or config.loader_type == "unknown":
                progress_dialog.close()
                raise Exception(f"偵測失敗：loader_type 無法判斷，config={config}")
            if not config.minecraft_version or config.minecraft_version == "unknown":
                progress_dialog.close()
                raise Exception(f"偵測失敗：minecraft_version 無法判斷，config={config}")
            if config.loader_type.lower() in ["forge", "fabric"] and (
                not config.loader_version or config.loader_version == "unknown"
            ):
                progress_dialog.close()
                raise Exception(f"偵測失敗：loader_version 無法判斷，config={config}")
            server_path = Path(config.path)
            # 步驟 2：下載伺服器核心檔案與載入器（統一處理）
            if not progress_dialog.update_progress(15, "下載伺服器核心檔案..."):
                return
            try:
                self.download_server_files(config, progress_dialog, server_path)
                # 下載成功後重建啟動腳本，確保 server.jar 存在
                self.server_manager.create_launch_script(config)
            except Exception as e:
                LogUtils.debug(f"下載伺服器檔案失敗: {e}", "CreateServerFrame")
                UIUtils.show_error("錯誤", f"下載伺服器檔案失敗: {e}", self.winfo_toplevel())
                traceback.print_exc()
                raise
            # 完成
            if not progress_dialog.update_progress(100, "伺服器建立完成！"):
                return
            time.sleep(1)

            def on_success():
                progress_dialog.close()
                self.callback(config, server_path)

            self._schedule_ui_update(on_success)
        except Exception as error:
            LogUtils.debug(f"建立伺服器時發生錯誤: {error}", "CreateServerFrame")
            traceback.print_exc()

            def on_error(error=error):
                progress_dialog.close()
                UIUtils.show_error("建立失敗", f"建立伺服器時發生錯誤：\n{error}", parent_window)

            self._schedule_ui_update(on_error)

    def download_server_files(self, config: ServerConfig, progress_dialog: ProgressDialog, server_path: Path) -> None:
        """
        下載伺服器檔案（統一呼叫 loader_manager，支援進度回呼）
        Download server files (call loader_manager, support progress callback)

        Args:
            config: 伺服器配置
            progress_dialog: 進度對話框
            server_path: 伺服器路徑
        """
        loader_type = config.loader_type.lower()
        download_path = str(server_path / "server.jar")
        parent_window = self.winfo_toplevel()  # 捕獲父視窗引用

        def progress_callback(percent, status):
            progress_dialog.update_progress(percent, status)

        # 在背景執行緒呼叫 loader_manager 下載
        result = [None]
        cancel_flag = {"cancelled": False}

        def do_download():
            user_java_path = self.java_path_var.get().strip() or None

            # 檢查參數 - 分解複雜條件以提高可讀性
            if not self._validate_download_parameters(loader_type, config):
                UIUtils.show_error(
                    "下載流程參數異常",
                    f"loader_type={loader_type}\nmc={config.minecraft_version}\nloader_ver={config.loader_version}",
                    parent_window,
                )
                result[0] = False
                return
            ok = self.loader_manager.download_server_jar_with_progress(
                loader_type,
                config.minecraft_version,
                config.loader_version,
                download_path,
                progress_callback,
                cancel_flag,
                user_java_path,
                parent_window,
            )
            result[0] = ok

        t = threading.Thread(target=do_download)
        t.start()
        while t.is_alive():
            if progress_dialog.cancelled:
                cancel_flag["cancelled"] = True
                break
            time.sleep(0.1)
        if result[0] is False:
            msg = (
                "伺服器下載失敗，參數如下：\n"
                f"loader_type: {loader_type}\n"
                f"minecraft_version: {config.minecraft_version}\n"
                f"loader_version: {config.loader_version}\n"
                f"download_path: {download_path}\n"
                f"user_java_path: {getattr(self, 'java_path_var', None) and self.java_path_var.get()}\n"
            )
            UIUtils.show_error("下載失敗", msg, parent_window)
            LogUtils.debug(f"server_path: {server_path}\nconfig: {config}", "CreateServerFrame")
            raise Exception(msg)

    def _validate_download_parameters(self, loader_type: str, config) -> bool:
        """
        驗證下載參數是否有效

        參數:
            loader_type: 載入器類型（forge、fabric 等）
            config: 伺服器設定物件

        回傳:
            bool: 參數有效則回傳 True，否則回傳 False
        """
        # 基本參數驗證
        if not loader_type or loader_type == "unknown":
            return False

        if not config.minecraft_version or config.minecraft_version == "unknown":
            return False

        # 對於需要載入器版本的類型進行額外驗證
        requires_loader_version = loader_type in ["forge", "fabric"]
        if requires_loader_version:
            if not config.loader_version or config.loader_version == "unknown":
                return False

        return True
