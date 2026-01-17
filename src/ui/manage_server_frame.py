#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
管理伺服器頁面
負責管理現有 Minecraft 伺服器的使用者介面
"""
# ====== 標準函式庫 ======
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Callable, Optional
import os
import shutil
import subprocess
import tkinter as tk
import traceback
import glob
import queue
import threading
import customtkinter as ctk
# ====== 專案內部模組 ======
from ..core import ServerConfig, ServerManager
from ..utils import MemoryUtils, ServerDetectionUtils, ServerOperations, get_font
from ..utils import LogUtils, UIUtils
from . import ServerMonitorWindow, ServerPropertiesDialog

class ManageServerFrame(ctk.CTkFrame):
    """
    管理伺服器頁面
    Manage Server Page
    負責管理現有 Minecraft 伺服器的使用者介面
    (Responsible for the user interface to manage existing Minecraft servers)
    """
    def __init__(
        self,
        parent,
        server_manager: ServerManager,
        callback: Callable,
        on_navigate_callback: Callable = None,
        set_servers_root=None,
    ):
        super().__init__(parent)

        self.server_manager = server_manager
        self.callback = callback
        self.on_navigate_callback = on_navigate_callback  # 添加導航回調
        self.set_servers_root = set_servers_root  # 明確傳入 main_window 的 set_servers_root
        self.selected_server: Optional[str] = None
        
        # 元件初始化旗標與關鍵屬性（避免在 UI 尚未建立時被 background refresh 觸發）
        self._widgets_created = False
        self.server_tree = None
        self.action_buttons = {}

        # 初始化 UI 更新佇列 Initialize UI update queue
        self.ui_queue = queue.Queue()

        # 先建立 UI 元件（建立 server_tree 等），再啟動 queue pump
        self.create_widgets()
        UIUtils.start_ui_queue_pump(self, self.ui_queue)

        self._post_action_immediate_job = None
        self._post_action_delayed_job = None
        self._delayed_refresh_job = None

    def _schedule_post_action_updates(self, immediate_delay_ms: int, delayed_delay_ms: int) -> None:
        for attr_name in ("_post_action_immediate_job", "_post_action_delayed_job"):
            job_id = getattr(self, attr_name, None)
            if job_id:
                try:
                    self.after_cancel(job_id)
                except Exception as e:
                    LogUtils.error_exc(f"取消排程失敗 {attr_name}={job_id}: {e}", "ManageServerFrame", e)
                setattr(self, attr_name, None)

        self._post_action_immediate_job = self.after(immediate_delay_ms, self._immediate_update)
        self._post_action_delayed_job = self.after(delayed_delay_ms, self._delayed_update)

    def _schedule_refresh(self, delay_ms: int) -> None:
        job_id = getattr(self, "_delayed_refresh_job", None)
        if job_id:
            try:
                self.after_cancel(job_id)
            except Exception as e:
                LogUtils.error_exc(f"取消刷新排程失敗 job={job_id}: {e}", "ManageServerFrame", e)
        self._delayed_refresh_job = self.after(delay_ms, self.refresh_servers)

    def create_widgets(self) -> None:
        """
        建立介面元件
        Create UI components
        """
        if getattr(self, "_widgets_created", False):
            return
        self._widgets_created = True

        # 主容器
        main_container = ctk.CTkFrame(self, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=20, pady=20)

        # 標題
        title_label = ctk.CTkLabel(main_container, text="⚙️ 管理伺服器", font=get_font(size=24, weight="bold"))
        title_label.pack(pady=(0, 20))

        # 上方控制區
        self.create_controls(main_container)

        # 伺服器列表
        self.create_server_list(main_container)

        # 下方操作區
        self.create_actions(main_container)

    def create_controls(self, parent) -> None:
        """
        建立控制區
        Create control area

        Args:
            parent: 父容器
        """
        control_frame = ctk.CTkFrame(parent)
        control_frame.pack(fill="x", pady=(0, 20))

        # 標題
        control_title = ctk.CTkLabel(control_frame, text="偵測設定", font=get_font(size=14, weight="bold"))
        control_title.pack(anchor="w", pady=(15, 10), padx=(15, 0))

        # 偵測路徑
        path_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        path_frame.pack(fill="x", padx=15, pady=(0, 10))

        ctk.CTkLabel(path_frame, text="偵測路徑:", font=get_font(size=12)).pack(side="left")

        self.detect_path_var = tk.StringVar(value=str(self.server_manager.servers_root))
        self.detect_path_entry = ctk.CTkEntry(path_frame, textvariable=self.detect_path_var, font=get_font(size=11))
        self.detect_path_entry.pack(side="left", fill="x", expand=True, padx=(10, 0))

        browse_button = UIUtils.create_styled_button(
            path_frame,
            text="瀏覽",
            command=self.browse_path,
            button_type="small",
        )
        browse_button.pack(side="left", padx=(5, 0))

        # 按鈕區域
        button_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        button_frame.pack(pady=(0, 15))

        # 偵測按鈕
        detect_button = UIUtils.create_styled_button(
            button_frame,
            text="🔍 偵測現有伺服器",
            command=lambda: self.detect_servers(show_message=True),
            button_type="secondary",
        )
        detect_button.pack(side="left", padx=5)

        # 手動新增按鈕
        add_button = UIUtils.create_styled_button(
            button_frame,
            text="➕ 手動新增",
            command=self.add_server,
            button_type="secondary",
        )
        add_button.pack(side="left", padx=5)

        # 重新整理按鈕
        refresh_button = UIUtils.create_styled_button(
            button_frame,
            text="🔄 重新整理",
            command=lambda: self.refresh_servers(),
            button_type="secondary",
        )
        refresh_button.pack(side="left", padx=5)

    def create_server_list(self, parent) -> None:
        """
        建立伺服器列表
        Create server list

        Args:
            parent: 父容器
        """
        list_frame = ttk.LabelFrame(parent, text="伺服器列表", padding=10)
        list_frame.pack(fill="both", expand=True, pady=(0, 20))

        style = ttk.Style()
        style.configure("ServerList.TLabelframe.Label", font=get_font("Microsoft JhengHei", 18, "bold"))
        list_frame.configure(style="ServerList.TLabelframe")

        # 建立 Treeview
        columns = ("名稱", "版本", "載入器", "狀態", "備份狀態", "路徑")
        self.server_tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")

        # 配置 Treeview 的字體大小
        style.configure("Treeview", font=get_font("Microsoft JhengHei", 18))
        style.configure("Treeview.Heading", font=get_font("Microsoft JhengHei", 22, "bold"))
        # 設定欄位
        self.server_tree.heading("名稱", text="名稱")
        self.server_tree.heading("版本", text="版本")
        self.server_tree.heading("載入器", text="載入器")
        self.server_tree.heading("狀態", text="狀態")
        self.server_tree.heading("備份狀態", text="備份狀態")
        self.server_tree.heading("路徑", text="路徑")

        # 設定欄位寬度
        self.server_tree.column("名稱", width=150)
        self.server_tree.column("版本", width=100)
        self.server_tree.column("載入器", width=120)
        self.server_tree.column("狀態", width=100)
        self.server_tree.column("備份狀態", width=50)
        self.server_tree.column("路徑", width=200)

        # 綁定事件
        self.server_tree.bind("<<TreeviewSelect>>", self.on_server_select)
        self.server_tree.bind("<Double-1>", self.on_server_double_click)
        self.server_tree.bind("<Button-3>", self.show_server_context_menu)

        # 加入滾動條
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.server_tree.yview)
        self.server_tree.configure(yscrollcommand=scrollbar.set)

        # 佈局
        self.server_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def show_server_context_menu(self, event) -> None:
        """
        顯示右鍵選單
        Show right-click context menu

        Args:
            event: 事件物件
        """
        selection = self.server_tree.selection()
        if not selection:
            return
        menu = tk.Menu(self, tearoff=0, font=get_font("Microsoft JhengHei", 18))
        menu.add_command(label="🔄 重新檢測伺服器", command=self.recheck_selected_server)
        menu.add_separator()
        menu.add_command(label="📁 重新設定備份路徑", command=self.reset_backup_path)
        menu.add_command(label="📂 開啟備份資料夾", command=self.open_backup_folder)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _get_selected_server_config(self, show_warning: bool = True) -> Optional[ServerConfig]:
        """
        獲取當前選中的伺服器配置
        Get current selected server configuration

        Args:
            show_warning (bool): 是否顯示警告訊息

        Returns:
            Optional[ServerConfig]: 伺服器配置物件，若無選擇或錯誤則返回 None
        """
        selection = self.server_tree.selection()
        if not selection:
            if show_warning:
                UIUtils.show_warning("提示", "請先選擇伺服器", self.winfo_toplevel())
            return None

        item = self.server_tree.item(selection[0])
        values = item["values"]
        if not values or len(values) < 1:
            if show_warning:
                UIUtils.show_warning("提示", "無法取得伺服器名稱", self.winfo_toplevel())
            return None

        server_name = values[0]
        config = self.server_manager.servers.get(server_name)
        if not config:
            if show_warning:
                UIUtils.show_error("錯誤", f"找不到伺服器設定: {server_name}", self.winfo_toplevel())
            return None
            
        return config

    def recheck_selected_server(self) -> None:
        """
        重新檢測選中伺服器
        Recheck selected server
        """
        config = self._get_selected_server_config(show_warning=False)
        if not config:
            return
            
        server_name = config.name
        # 呼叫偵測
        ServerDetectionUtils.detect_server_type(Path(config.path), config)
        self.server_manager.save_servers_config()
        self.refresh_servers()
        UIUtils.show_info("完成", f"已重新檢測伺服器：{server_name}", self.winfo_toplevel())

    def reset_backup_path(self) -> None:
        """
        重新設定選中伺服器的備份路徑
        Reset backup path for selected server
        """
        config = self._get_selected_server_config()
        if not config:
            return

        server_name = config.name
        # 詢問使用者選擇新的備份父路徑
        parent_backup_path = filedialog.askdirectory(
            title=f"重新設定 {server_name} 的備份路徑", initialdir=os.path.expanduser("~")
        )

        if parent_backup_path:
            # 建立伺服器專用的備份資料夾
            backup_folder_name = f"{server_name}_backup"
            new_backup_path = os.path.join(parent_backup_path, backup_folder_name)

            # 建立備份資料夾（如果不存在）
            try:
                os.makedirs(new_backup_path, exist_ok=True)
            except Exception as e:
                LogUtils.error(f"無法建立備份資料夾: {e}\n{traceback.format_exc()}", "ManageServerFrame")
                UIUtils.show_error("錯誤", f"無法建立備份資料夾: {e}", self.winfo_toplevel())
                return

            # 更新配置
            config.backup_path = new_backup_path
            self.server_manager.save_servers_config()
            UIUtils.show_info(
                "成功", f"已將伺服器 {server_name} 的備份路徑設定為：\n{new_backup_path}", self.winfo_toplevel()
            )
            # 刷新列表以更新備份狀態顯示
            self.refresh_servers()
        else:
            UIUtils.show_info("取消", "未更改備份路徑設定", self.winfo_toplevel())

    def open_backup_folder(self) -> None:
        """
        開啟選中伺服器的備份資料夾
        Open backup folder for selected server
        """
        selection = self.server_tree.selection()
        if not selection:
            UIUtils.show_warning("提示", "請先選擇要開啟備份資料夾的伺服器", self.winfo_toplevel())
            return

        item = self.server_tree.item(selection[0])
        values = item["values"]
        if not values or len(values) < 1:
            UIUtils.show_warning("提示", "無法取得伺服器名稱", self.winfo_toplevel())
            return

        server_name = values[0]
        config = self.server_manager.servers.get(server_name)
        if not config:
            UIUtils.show_error("錯誤", f"找不到伺服器設定: {server_name}", self.winfo_toplevel())
            return

        # 檢查是否有設定備份路徑
        if not hasattr(config, "backup_path") or not config.backup_path:
            UIUtils.show_warning(
                "提示", f"伺服器 {server_name} 尚未設定備份路徑\n請先執行一次備份來設定備份路徑", self.winfo_toplevel()
            )
            return

        # 檢查備份路徑是否存在
        if not os.path.exists(config.backup_path):
            UIUtils.show_error(
                "錯誤", f"備份路徑不存在：\n{config.backup_path}\n\n請重新設定備份路徑", self.winfo_toplevel()
            )
            return

        try:
            os.startfile(config.backup_path)
        except Exception as e:
            LogUtils.error(f"無法開啟備份資料夾: {e}\n{traceback.format_exc()}", "ManageServerFrame")
            UIUtils.show_error("錯誤", f"無法開啟備份資料夾: {e}", self.winfo_toplevel())

    def get_backup_status(self, server_name: str) -> str:
        """
        獲取伺服器的備份狀態文字
        Get backup status text for server

        Args:
            server_name (str): 伺服器名稱

        Returns:
            str: 備份狀態文字
        """
        if not server_name or server_name not in self.server_manager.servers:
            return "❓ 無法檢查"

        config = self.server_manager.servers[server_name]

        # 檢查是否有設定備份路徑
        if not hasattr(config, "backup_path") or not config.backup_path:
            return "❌ 未設定路徑"

        # 檢查備份路徑是否存在
        if not os.path.exists(config.backup_path):
            return "❌ 路徑不存在"

        try:
            # 檢查備份資料夾中的world資料夾是否存在
            backup_world_path = os.path.join(config.backup_path, "world")

            if os.path.exists(backup_world_path):
                # 取得備份world資料夾的修改時間
                backup_time = os.path.getmtime(backup_world_path)
                backup_datetime = datetime.fromtimestamp(backup_time)

                # 計算距離現在的時間
                now = datetime.now()
                time_diff = now - backup_datetime

                if time_diff.days > 0:
                    if time_diff.days == 1:
                        time_ago = "1天前"
                    else:
                        time_ago = f"{time_diff.days}天前"
                    return f"✅ {time_ago}"
                elif time_diff.seconds > 3600:
                    hours = time_diff.seconds // 3600
                    return f"✅ {hours}小時前"
                else:
                    minutes = time_diff.seconds // 60
                    time_ago = f"{minutes}分鐘前" if minutes > 0 else "剛剛"
                    return f"✅ {time_ago}"
            else:
                return "📁 已設定路徑"

        except Exception as e:
            LogUtils.error(f"檢查備份狀態失敗: {e}\n{traceback.format_exc()}", "ManageServerFrame")
            return "❓ 檢查失敗"

    def create_actions(self, parent) -> None:
        """
        建立操作區
        Create action area
        """
        action_frame = ctk.CTkFrame(parent)
        action_frame.pack(fill="x")

        # 操作標題
        action_title = ctk.CTkLabel(action_frame, text="操作", font=get_font(size=14, weight="bold"))
        action_title.pack(anchor="w", pady=(5, 0), padx=(15, 0))

        # 資訊顯示
        info_frame = ctk.CTkFrame(action_frame, fg_color="transparent")
        info_frame.pack(fill="x", padx=15, pady=(5, 5))

        self.info_label = ctk.CTkLabel(info_frame, text="選擇一個伺服器以查看詳細資訊", font=get_font(size=14))
        self.info_label.pack(anchor="w")

        # 按鈕區域（獨立一行）
        button_frame = ctk.CTkFrame(action_frame, fg_color="transparent")
        button_frame.pack(fill="x", padx=15, pady=(0, 15))

        buttons = [
            ("🚀", "啟動", self.start_server),
            ("📊", "監控", self.monitor_server),
            ("⚙️", "設定", self.configure_server),
            ("📂", "開啟資料夾", self.open_server_folder),
            ("💾", "備份", self.backup_server),
            ("🗑️", "刪除", self.delete_server),
        ]

        self.action_buttons = {}
        for emoji, text, command in buttons:
            # 使用簡單的 emoji 文字按鈕
            btn_text = f"{emoji} {text}"
            btn = UIUtils.create_styled_button(
                button_frame,
                text=btn_text,
                command=command,
                button_type="secondary",
                state="disabled",
            )
            btn.pack(side="left", padx=(0, 5))
            self.action_buttons[f"{emoji} {text}"] = btn

    def browse_path(self) -> None:
        """
        瀏覽路徑，並自動正規化、寫入設定、建立 servers 子資料夾、刷新列表
        Browse path, automatically normalize, write settings, create servers subfolder, refresh list
        """
        path = filedialog.askdirectory(title="選擇伺服器目錄")
        if path:
            # 強制正規化分隔符與絕對路徑
            abs_path = os.path.abspath(path)
            norm_path = os.path.normpath(abs_path)
            base_dir = norm_path

            # 呼叫 main_window 傳入的 set_servers_root：寫入 user_settings.json（儲存 base dir）
            # 並回傳實際 servers_root (= <base>\servers)
            servers_root = None
            if self.set_servers_root:
                try:
                    servers_root = self.set_servers_root(base_dir)
                except Exception as e:
                    LogUtils.error(f"寫入伺服器路徑設定失敗: {e}\n{traceback.format_exc()}", "ManageServerFrame")
                    UIUtils.show_error("錯誤", f"無法寫入設定: {e}", self.winfo_toplevel())
                    return

            if not servers_root:
                servers_root = os.path.normpath(os.path.join(base_dir, "servers"))

            servers_root_path = Path(servers_root)
            if not servers_root_path.exists():
                try:
                    servers_root_path.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    LogUtils.error(f"無法建立 servers 資料夾: {e}\n{traceback.format_exc()}", "ManageServerFrame")
                    UIUtils.show_error("錯誤", f"無法建立 servers 資料夾: {e}", self.winfo_toplevel())
                    return

            # 更新 entry 顯示（顯示實際 servers 子資料夾）
            self.detect_path_var.set(servers_root)

            # 同步 server_manager 的 root
            self.server_manager.servers_root = Path(servers_root)
            # 變更後自動刷新伺服器列表
            self.refresh_servers()

    def detect_servers(self, show_message: bool = True) -> None:
        """
        偵測現有伺服器，無論新建或覆蓋都會呼叫 detect_server_type
        Detect existing servers, whether new or overwritten will call detect_server_type
        Args:
            show_message (bool): 是否顯示完成通知
        """
        path = self.detect_path_var.get()
        if not path or not os.path.exists(path):
            if show_message:
                UIUtils.show_error("錯誤", "請選擇有效的路徑", self.winfo_toplevel())
            return
            
        def task():
            try:
                count = self._detect_servers_task(path)
                self.ui_queue.put(lambda: self._detect_servers_callback(count, show_message))
            except Exception as error:
                LogUtils.error(f"偵測失敗: {error}\n{traceback.format_exc()}", "ManageServerFrame")
                self.ui_queue.put(lambda: UIUtils.show_error("錯誤", f"偵測失敗: {error}", self.winfo_toplevel()))

        threading.Thread(target=task, daemon=True).start()

    def _detect_servers_task(self, path):
        count = 0
        for item in os.listdir(path):
            item_path = os.path.join(path, item)
            if os.path.isdir(item_path):
                item_path_obj = Path(item_path)
                if ServerDetectionUtils.is_valid_server_folder(item_path_obj):
                    # 先建立 config 物件（無論新建或覆蓋都呼叫偵測）
                    if item in self.server_manager.servers:
                        config = self.server_manager.servers[item]
                        config.path = str(item_path)
                    else:
                        config = ServerConfig(
                            name=item,
                            minecraft_version="Unknown",
                            loader_type="Unknown",
                            loader_version="Unknown",
                            memory_max_mb=2048,
                            path=item_path,
                        )
                    # 強制呼叫偵測
                    ServerDetectionUtils.detect_server_type(item_path_obj, config)
                    if item in self.server_manager.servers:
                        self.server_manager.save_servers_config()
                        count += 1
                    else:
                        if self.server_manager.create_server(config):
                            count += 1
        return count

    def _detect_servers_callback(self, count, show_message):
        if show_message:
            UIUtils.show_info("完成", f"成功偵測/更新 {count} 個伺服器", self.winfo_toplevel())
        self.refresh_servers()

    def add_server(self) -> None:
        """
        手動新增伺服器 - 跳轉到建立伺服器頁面
        Manually add server - navigate to create server page
        """
        if self.on_navigate_callback:
            self.on_navigate_callback()

    def _get_server_status_text(self, name: str, config: ServerConfig) -> str:
        """
        獲取伺服器狀態文字
        Get server status text
        """
        is_running = self.server_manager.is_server_running(name)
        if is_running:
            return "🟢 運行中"

        # 檢查伺服器檔案
        server_jar_exists = False
        jar_patterns = ["server.jar", "minecraft_server*.jar", "fabric-server*.jar", "forge-*.jar"]
        for jar_pattern in jar_patterns:
            if "*" in jar_pattern:
                if glob.glob(os.path.join(config.path, jar_pattern)):
                    server_jar_exists = True
                    break
            elif os.path.exists(os.path.join(config.path, jar_pattern)):
                server_jar_exists = True
                break

        eula_exists = os.path.exists(os.path.join(config.path, "eula.txt"))
        eula_accepted = getattr(config, "eula_accepted", False)

        if server_jar_exists and eula_exists and eula_accepted:
            return "✅ 已就緒"
        elif server_jar_exists and eula_exists and not eula_accepted:
            return "⚠️ 需要接受 EULA"
        elif server_jar_exists:
            return "❌ 缺少 EULA"
        else:
            missing = ServerDetectionUtils.get_missing_server_files(Path(config.path))
            if missing:
                return f"❌ 未就緒 (缺少: {', '.join(missing)})"
            return "❌ 未就緒"

    def refresh_servers(self) -> None:
        """
        重新整理伺服器列表：只刷新 UI，不自動偵測。
        Refresh server list: only refresh UI, do not auto-detect.
        """
        def task():
            try:
                server_data = self._refresh_servers_task()
                self.ui_queue.put(lambda: self._refresh_servers_callback(server_data))
            except Exception as e:
                LogUtils.error(f"重新整理伺服器列表失敗: {e}\n{traceback.format_exc()}", "ManageServerFrame")
                # 這裡可以選擇是否要顯示錯誤，或者靜默失敗
                pass

        threading.Thread(target=task, daemon=True).start()

    def _refresh_servers_task(self):
        """
        後台任務：載入配置並獲取伺服器狀態
        Background task: load config and get server status
        """
        # 強制重載配置
        self.server_manager.load_servers_config()
        
        server_data = []
        if not self.server_manager.servers:
            return server_data

        for name, config in self.server_manager.servers.items():
            status = self._get_server_status_text(name, config)
            
            loader_type = (config.loader_type or "").lower()
            loader_version = (config.loader_version or "").lower()
            if loader_type == "vanilla":
                loader_col = "原版"
            elif loader_type == "unknown" or not loader_type:
                loader_col = "未知"
            else:
                loader_col = loader_type.capitalize()
                if loader_version and loader_version != "unknown":
                    loader_col = f"{loader_col} v{config.loader_version}"
            
            mc_version = (
                config.minecraft_version
                if config.minecraft_version and config.minecraft_version.lower() != "unknown"
                else "未知"
            )
            backup_status = self.get_backup_status(name)
            
            server_data.append((name, mc_version, loader_col, status, backup_status, config.path))
            
        return server_data

    def _refresh_servers_callback(self, server_data):
        """
        UI 更新回調
        UI update callback
        """
        if not getattr(self, "server_tree", None):
            return

        # 檢查數據是否變更 (簡單快取檢查)
        current_data_signature = str(server_data)
        if hasattr(self, '_last_server_data') and self._last_server_data == current_data_signature:
             # 如果數據沒變，只更新選擇狀態
            self.update_selection()
            return
            
        self._last_server_data = current_data_signature

        # 清空現有項目
        for item in self.server_tree.get_children():
            self.server_tree.delete(item)

        if not server_data:
            self.selected_server = None
            self.update_selection()
            return

        # 重新載入伺服器
        for item in server_data:
            self.server_tree.insert("", "end", values=item)
            
        self.selected_server = None
        self.update_selection()

    def on_server_select(self, event) -> None:
        """
        伺服器選擇事件
        Server selection event
        """
        selection = self.server_tree.selection()
        if selection:
            item = self.server_tree.item(selection[0])
            self.selected_server = item["values"][0]  # 伺服器名稱
            self.callback(self.selected_server)
        else:
            self.selected_server = None

        self.update_selection()

    def on_server_double_click(self, event) -> None:
        """
        伺服器雙擊事件
        Server double-click event
        """
        if self.selected_server:
            self.configure_server()

    def update_selection(self) -> None:
        """
        更新選擇狀態
        Update selection state
        """
        has_selection = self.selected_server is not None

        # 更新按鈕狀態
        if has_selection:
            # 檢查伺服器是否正在運行
            is_running = self.server_manager.is_server_running(self.selected_server)

            # 根據運行狀態設定按鈕
            start_stop_key = "🟢 啟動"
            if is_running:
                if start_stop_key in self.action_buttons:
                    self.action_buttons[start_stop_key].configure(text="🛑 停止", state="normal")
            else:
                if start_stop_key in self.action_buttons:
                    self.action_buttons[start_stop_key].configure(text="🟢 啟動", state="normal")

            # 其他按鈕
            for key, btn in self.action_buttons.items():
                if key != start_stop_key:
                    btn.configure(state="normal")
        else:
            # 沒有選擇時禁用所有按鈕
            for btn in self.action_buttons.values():
                btn.configure(state="disabled")
            start_stop_key = "🟢 啟動"
            if start_stop_key in self.action_buttons:
                self.action_buttons[start_stop_key].configure(text="🟢 啟動")

        # 更新資訊標籤
        if has_selection and self.selected_server in self.server_manager.servers:
            config = self.server_manager.servers[self.selected_server]
            is_running = self.server_manager.is_server_running(self.selected_server)
            status_emoji = "🟢" if is_running else "🔴"
            status_text = "運行中" if is_running else "已停止"

            # 使用統一的記憶體格式化函數

            memory_info = ""
            if hasattr(config, "memory_max_mb") and config.memory_max_mb:
                max_mem_str = MemoryUtils.format_memory_mb(config.memory_max_mb)
                if hasattr(config, "memory_min_mb") and config.memory_min_mb:
                    min_mem_str = MemoryUtils.format_memory_mb(config.memory_min_mb)
                    memory_info = f"記憶體: {min_mem_str}-{max_mem_str}"
                else:
                    memory_info = f"最大記憶體: {max_mem_str}"
            elif hasattr(config, "memory_mb") and config.memory_mb:
                memory_info = f"記憶體: {MemoryUtils.format_memory_mb(config.memory_mb)}"
            else:
                memory_info = "記憶體: 未設定"

            # 格式化載入器資訊
            loader_type = (config.loader_type or "").lower()
            loader_version = (config.loader_version or "").lower()
            if loader_type == "vanilla":
                loader_info = "原版"
            elif loader_type == "unknown" or not loader_type:
                loader_info = "未知"
            else:
                loader_info = loader_type.capitalize()
                if loader_version and loader_version != "unknown":
                    loader_info = f"{loader_info} v{config.loader_version}"
            info_text = f"{config.name} | {status_emoji} {status_text} | MC {config.minecraft_version if config.minecraft_version and config.minecraft_version.lower() != 'unknown' else '未知'} | {loader_info} | {memory_info}"
            self.info_label.configure(text=info_text)
        else:
            self.info_label.configure(text="✨ 選擇一個伺服器以查看詳細資訊")

    def start_server(self) -> None:
        """
        啟動/停止伺服器
        Start/stop server
        """
        if not self.selected_server:
            return

        is_running = self.server_manager.is_server_running(self.selected_server)

        if is_running:
            # 停止伺服器 - 使用工具函數
            success = ServerOperations.graceful_stop_server(self.server_manager, self.selected_server)
            if success:
                UIUtils.show_info("成功", f"伺服器 {self.selected_server} 停止命令已發送", self.winfo_toplevel())
            else:
                UIUtils.show_error("錯誤", f"停止伺服器 {self.selected_server} 失敗", self.winfo_toplevel())
            # 立即更新一次，然後延遲再更新
            self._schedule_post_action_updates(100, 2000)
        else:
            # 啟動伺服器
            success = self.server_manager.start_server(self.selected_server, parent=self.master)
            if success:
                # 啟動成功後自動開啟監控視窗，彈窗通知交由監控視窗處理
                self.monitor_server()
            else:
                UIUtils.show_error("錯誤", f"啟動伺服器 {self.selected_server} 失敗", self.winfo_toplevel())
            # 立即更新一次，然後延遲再更新
            self._schedule_post_action_updates(100, 1500)

    def _immediate_update(self) -> None:
        """
        立即更新狀態
        Immediate update status
        """
        self.update_selection()

    def _delayed_update(self) -> None:
        """
        延遲更新，確保狀態正確
        Delayed update to ensure status is correct
        """
        self.update_selection()
        self.refresh_servers()

    def monitor_server(self) -> None:
        """
        監控伺服器
        Monitor server
        """
        if not self.selected_server:
            return

        # 導入並創建監控視窗
        monitor_window = ServerMonitorWindow(self.winfo_toplevel(), self.server_manager, self.selected_server)
        monitor_window.show()

    def configure_server(self) -> None:
        """
        設定伺服器
        Configure server
        """
        if not self.selected_server:
            return

        config = self.server_manager.servers[self.selected_server]
        dialog = ServerPropertiesDialog(self.winfo_toplevel(), config, self.server_manager)

        if dialog.result:
            # 更新配置
            self.server_manager.servers[self.selected_server] = dialog.result
            self.server_manager.save_servers_config()
            self.refresh_servers()
            UIUtils.show_info("成功", "伺服器設定已更新", self.winfo_toplevel())

    def open_server_folder(self) -> None:
        """
        開啟伺服器資料夾
        Open server folder
        """
        if not self.selected_server:
            return

        config = self.server_manager.servers[self.selected_server]
        path = config.path

        try:
            os.startfile(path)
        except Exception as e:
            LogUtils.error(f"無法開啟資料夾: {e}\n{traceback.format_exc()}", "ManageServerFrame")
            UIUtils.show_error("錯誤", f"無法開啟資料夾: {e}", self.winfo_toplevel())

    def delete_server(self) -> None:
        """
        刪除伺服器
        Delete server
        """
        if not self.selected_server:
            return

        config = self.server_manager.servers[self.selected_server]

        # 檢查是否有備份
        has_backup = False
        backup_path = None
        if hasattr(config, "backup_path") and config.backup_path and os.path.exists(config.backup_path):
            backup_path = config.backup_path
            has_backup = True

        # 基本刪除確認
        result = UIUtils.ask_yes_no_cancel(
            "確認刪除",
            f"確定要刪除伺服器 '{self.selected_server}' 嗎？\n\n" + "⚠️ 這將永久刪除伺服器檔案，無法復原！",
            self.winfo_toplevel(),
            show_cancel=False,
        )

        if not result:
            return

        # 如果有備份，詢問是否一起刪除
        delete_backup = False
        if has_backup:
            backup_result = UIUtils.ask_yes_no_cancel(
                "刪除備份",
                f"偵測到伺服器 '{self.selected_server}' 有備份檔案：\n{backup_path}\n\n是否要一起刪除備份？\n\n• 點擊「是」：刪除伺服器和備份\n• 點擊「否」：只刪除伺服器，保留備份\n• 點擊「取消」：取消整個刪除操作",
                self.winfo_toplevel(),
            )

            if backup_result is None:  # 使用者點擊取消
                return

            delete_backup = backup_result  # True = 一起刪除，False = 保留備份

        # 執行刪除操作
        success = self.server_manager.delete_server(self.selected_server)
        if success:
            # 如果需要刪除備份
            if delete_backup and backup_path:
                try:
                    shutil.rmtree(backup_path)
                    UIUtils.show_info("成功", f"伺服器 {self.selected_server} 和其備份已刪除", self.winfo_toplevel())
                except Exception as e:
                    LogUtils.error(f"刪除備份失敗: {e}\n{traceback.format_exc()}", "ManageServerFrame")
                    UIUtils.show_warning(
                        "部分成功",
                        f"伺服器 {self.selected_server} 已刪除，但備份刪除失敗：\n{e}\n\n備份位置：{backup_path}",
                        self.winfo_toplevel(),
                    )
            else:
                if has_backup:
                    UIUtils.show_info(
                        "成功",
                        f"伺服器 {self.selected_server} 已刪除\n\n備份已保留於：{backup_path}",
                        self.winfo_toplevel(),
                    )
                else:
                    UIUtils.show_info("成功", f"伺服器 {self.selected_server} 已刪除", self.winfo_toplevel())

            self.refresh_servers()
        else:
            UIUtils.show_error("錯誤", f"刪除伺服器 {self.selected_server} 失敗", self.winfo_toplevel())

    def backup_server(self) -> None:
        """
        備份伺服器世界檔案
        Backup server world files
        """
        if not self.selected_server:
            return

        # 保存伺服器名稱，避免在列表刷新時被清除
        server_name = self.selected_server
        config = self.server_manager.servers[server_name]
        server_path = config.path
        world_path = os.path.join(server_path, "world")

        # 檢查世界資料夾是否存在
        if not os.path.exists(world_path):
            UIUtils.show_error("錯誤", f"找不到世界資料夾: {world_path}", self.winfo_toplevel())
            return

        # 檢查是否已有儲存的備份路徑
        backup_location = None
        is_new_backup_path = False  # 記錄是否是新設定的路徑

        if hasattr(config, "backup_path") and config.backup_path:
            # 檢查儲存的路徑是否仍然存在
            if os.path.exists(config.backup_path):
                backup_location = config.backup_path
            else:
                # 路徑不存在，清除配置中的路徑
                config.backup_path = None
                self.server_manager.save_servers_config()

        # 如果沒有備份路徑，詢問使用者
        if not backup_location:
            parent_backup_location = filedialog.askdirectory(
                title="選擇備份儲存位置", initialdir=os.path.expanduser("~")
            )

            if not parent_backup_location:
                return  # 使用者取消選擇

            # 建立伺服器專用的備份資料夾
            backup_folder_name = f"{server_name}_backup"
            backup_location = os.path.join(parent_backup_location, backup_folder_name)

            # 建立備份資料夾（如果不存在）
            try:
                os.makedirs(backup_location, exist_ok=True)
            except Exception as e:
                LogUtils.error(f"無法建立備份資料夾: {e}\n{traceback.format_exc()}", "ManageServerFrame")
                UIUtils.show_error("錯誤", f"無法建立備份資料夾: {e}", self.winfo_toplevel())
                return

            # 儲存備份路徑到配置檔案（儲存的是伺服器專用資料夾）
            config.backup_path = backup_location
            self.server_manager.save_servers_config()
            is_new_backup_path = True  # 標記為新設定的路徑

            # 立即刷新一次列表以更新備份狀態
            self.refresh_servers()

        # 建立備份檔案路徑
        backup_full_path = backup_location  # 備份路徑就是伺服器專用資料夾
        backup_world_path = os.path.join(backup_full_path, "world")

        # 轉換路徑為 Windows 格式
        world_path = os.path.normpath(world_path)
        backup_full_path = os.path.normpath(backup_full_path)
        backup_world_path = os.path.normpath(backup_world_path)

        # 生成批次檔內容
        bat_content = f"""@echo off

REM 備份 {server_name} 伺服器世界檔案
REM Backup {server_name} server world files

REM 刪除舊的備份世界資料夾（如果存在）
REM Remove old backup world folder (if exists)
IF EXIST "{backup_world_path}" RD /Q /S "{backup_world_path}"

REM 建立世界備份資料夾
REM Create world backup folder
MD "{backup_world_path}"

REM 複製世界檔案到備份位置
REM Copy world files to backup location
xcopy "{world_path}\\" "{backup_world_path}" /E /Y /K /R /H

echo 備份完成！
echo Backup completed!
echo 伺服器: {server_name}
echo Server: {server_name}
echo 來源: {world_path}
echo Source: {world_path}
echo 目標: {backup_world_path}
echo Target: {backup_world_path}
echo.
pause"""

        # 儲存批次檔到備份資料夾內
        bat_file_path = os.path.join(backup_full_path, f"backup_{server_name}.bat")

        try:
            with open(bat_file_path, "w", encoding="utf-8") as f:
                f.write(bat_content)

            # 如果是新設定的備份路徑，詢問是否立即執行備份
            # 如果已有備份路徑，直接執行備份
            if is_new_backup_path:
                # 詢問是否立即執行備份
                backup_msg = f"備份批次檔已建立：\n{bat_file_path}\n\n"
                backup_msg += (
                    f"✅ 備份資料夾已建立：{backup_full_path}\n"
                    "💡 如需更改備份路徑，請右鍵點擊伺服器選擇「重新設定備份路徑」。\n\n"
                )
                backup_msg += "是否立即執行備份？"

                result = UIUtils.ask_yes_no_cancel(
                    "備份檔案已建立", backup_msg, self.winfo_toplevel(), show_cancel=False
                )

                if not result:
                    UIUtils.show_info(
                        "備份檔案已建立",
                        f"備份批次檔已儲存至：\n{bat_file_path}\n\n您可以稍後手動執行此檔案來進行備份。",
                        self.winfo_toplevel(),
                    )
                    # 即使不立即執行備份，也要刷新列表以更新備份狀態（因為建立了備份資料夾）
                    self.refresh_servers()
                    return

            # 執行備份（新路徑詢問後同意，或已有路徑直接執行）
            # 執行批次檔（不顯示命令視窗）
            try:
                # 使用 subprocess 執行，隱藏命令視窗
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE

                subprocess.Popen([bat_file_path], startupinfo=startupinfo, shell=False)  # 安全性改進：移除 shell=True

                UIUtils.show_info(
                    "備份開始", f"備份已開始執行，請稍候...\n備份位置：{backup_full_path}", self.winfo_toplevel()
                )

                # 立即刷新一次列表
                self.refresh_servers()

                # 再次延遲刷新確保狀態正確
                self._schedule_refresh(5000)

            except Exception as e:
                LogUtils.error(f"執行備份批次檔失敗: {e}\n{traceback.format_exc()}", "ManageServerFrame")
                UIUtils.show_error("執行錯誤", f"執行備份批次檔失敗：{e}", self.winfo_toplevel())

        except Exception as e:
            LogUtils.error(f"建立備份批次檔失敗: {e}\n{traceback.format_exc()}", "ManageServerFrame")
            UIUtils.show_error("錯誤", f"建立備份批次檔失敗：{e}", self.winfo_toplevel())
