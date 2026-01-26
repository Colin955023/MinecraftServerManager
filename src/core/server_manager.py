#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
伺服器管理器
負責建立、管理和配置 Minecraft 伺服器
Server Manager
Responsible for creating, managing, and configuring Minecraft servers.
"""
from collections import deque
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional
import shutil
import subprocess
import threading
import time
import psutil
from ..models import ServerConfig
from ..utils import (
    ServerCommands,
    MemoryUtils,
    ServerPropertiesHelper,
    ServerDetectionUtils,
    get_logger,
    PathUtils,
    UIUtils,
)

logger = get_logger().bind(component="ServerManager")


class ServerManager:
    """
    伺服器管理器類別，負責建立、管理和配置 Minecraft 伺服器
    Server Manager class responsible for creating, managing, and configuring Minecraft servers
    """
    # ====== 類別常數 ======
    # 伺服器啟動檢查常數
    STARTUP_CHECK_DELAY = 0.1  # 伺服器啟動檢查延遲（秒）
    # 伺服器停止檢查常數
    STOP_CHECK_INTERVAL = 0.1  # 停止檢查間隔（秒）
    STOP_TIMEOUT_SECONDS = 5  # 停止超時時間（秒）
    MAX_STOP_CHECKS = int(
        STOP_TIMEOUT_SECONDS / STOP_CHECK_INTERVAL
    )  # 最大停止檢查次數
    # 輸出佇列大小限制
    OUTPUT_QUEUE_MAX_SIZE = 1000  # 輸出佇列最大容量

    # ====== 初始化與配置管理 ======
    # 初始化伺服器管理器
    def __init__(self, servers_root: str = None):
        """
        初始化伺服器管理器
        Initialize server manager

        Args:
            servers_root (str): 伺服器根目錄路徑

        Returns:
            None
        """
        # servers_root 必須由外部明確傳入，且必須是 servers 資料夾的絕對路徑
        if not servers_root:
            raise ValueError(
                "ServerManager 必須指定 servers_root 路徑，且不可為空。請於 UI 層先處理。"
            )
        self.servers_root = Path(servers_root).resolve()
        self.servers_root.mkdir(parents=True, exist_ok=True)
        self.config_file = self.servers_root / "servers_config.json"
        self.servers: Dict[str, ServerConfig] = {}
        self.running_servers: Dict[str, subprocess.Popen] = {}  # 追踪運行中的伺服器
        self.output_queues = {}  # server_name -> queue.Queue
        self.output_threads = {}  # server_name -> Thread
        self._properties_cache = {}  # server_name -> (mtime, properties)
        self.load_servers_config()

    # ====== 伺服器建立與設定 ======
    # 建立新伺服器
    def create_server(
        self, config: ServerConfig, properties: Optional[Dict[str, str]] = None
    ) -> bool:
        """
        建立新伺服器並初始化設定
        Create new server and initialize configuration

        Args:
            config (ServerConfig): 伺服器配置物件
            properties (Dict[str, str], optional): 伺服器屬性設定

        Returns:
            bool: 建立成功返回 True，失敗返回 False
        """
        try:
            server_path = self.servers_root / config.name
            server_path.mkdir(exist_ok=True)
            # 更新配置路徑
            config.path = str(server_path)
            # 僅在必要時自動偵測補齊 loader_type/minecraft_version/loader_version
            need_detect = (
                not config.loader_type
                or config.loader_type == "unknown"
                or not config.minecraft_version
                or config.minecraft_version == "unknown"
                or (
                    config.loader_type
                    and config.loader_type.lower() in ["forge", "fabric"]
                    and (
                        not config.loader_version or config.loader_version == "unknown"
                    )
                )
            )
            if need_detect:
                try:
                    ServerDetectionUtils.detect_server_type(server_path, config)
                    # 強制補齊欄位
                    if not config.loader_type or config.loader_type == "unknown":
                        raise Exception(
                            f"偵測失敗：loader_type 無法判斷，name={config.name}, path={config.path}, loader_type={config.loader_type}, minecraft_version={config.minecraft_version}, loader_version={config.loader_version}"
                        )
                    if (
                        not config.minecraft_version
                        or config.minecraft_version == "unknown"
                    ):
                        raise Exception(
                            f"偵測失敗：minecraft_version 無法判斷，name={config.name}, path={config.path}, loader_type={config.loader_type}, minecraft_version={config.minecraft_version}, loader_version={config.loader_version}"
                        )
                    if config.loader_type.lower() in ["forge", "fabric"] and (
                        not config.loader_version or config.loader_version == "unknown"
                    ):
                        raise Exception(
                            f"偵測失敗：loader_version 無法判斷，name={config.name}, path={config.path}, loader_type={config.loader_type}, minecraft_version={config.minecraft_version}, loader_version={config.loader_version}"
                        )
                except Exception as e:
                    logger.error(f"自動偵測伺服器類型失敗: {e}")
                    raise
            # 儲存配置
            self.servers[config.name] = config
            self.save_servers_config()
            # 總是建立 EULA 檔案 (自動接受)
            self._create_eula_file(server_path)
            config.eula_accepted = True
            # 建立基本檔案結構
            self._create_server_structure(Path(config.path), config.loader_type)
            # 初始化 server.properties
            properties_file = server_path / "server.properties"
            if properties is None:
                properties = self.get_default_server_properties()
            # motd 預設帶入伺服器名稱
            properties = dict(properties)
            properties["motd"] = f"Minecraft 伺服器 - {config.name}"
            ServerPropertiesHelper.save_properties(properties_file, properties)
            config.properties = properties
            # 建立啟動腳本
            self.create_launch_script(config)
            return True
        except Exception as e:
            logger.exception(f"建立伺服器失敗: {e}")
            return False

    def _create_eula_file(self, server_path: Path) -> None:
        """
        建立並同意 EULA 檔案
        Create and accept EULA file.

        Args:
            server_path (Path): 伺服器根目錄路徑
        """
        eula_content = """eula=true"""
        with open(server_path / "eula.txt", "w", encoding="utf-8") as f:
            f.write(eula_content)

    def _create_server_structure(self, path: Path, loader_type: str) -> None:
        """
        建立伺服器檔案結構
        Create server file structure.

        Args:
            path (Path): 伺服器根目錄路徑
            loader_type (str): 伺服器載入器類型
        """
        # 建立基本目錄
        if loader_type.lower() == "vanilla":
            directories = ["world", "logs"]
        elif loader_type.lower() in ["forge", "fabric"]:
            directories = ["world", "plugins", "mods", "config", "logs"]

        for directory in directories:
            (path / directory).mkdir(exist_ok=True)

    def create_launch_script(self, config: ServerConfig) -> None:
        """
        建立伺服器啟動腳本 (Windows)
        Create server launch script (Windows).

        Args:
            config (ServerConfig): 伺服器配置物件
        """
        server_path = Path(config.path)

        # 計算記憶體設定
        max_memory = config.memory_max_mb
        min_memory = config.memory_min_mb

        # 構建 Java 記憶體參數
        memory_args = f"-Xmx{max_memory}M"
        if min_memory:
            memory_args = f"-Xmx{max_memory}M -Xms{min_memory}M"
            memory_display = f"最小 {MemoryUtils.format_memory_mb(min_memory)}, 最大 {MemoryUtils.format_memory_mb(max_memory)}"
        else:
            memory_display = f"0-{MemoryUtils.format_memory_mb(max_memory)}"

        # 使用統一的 Java 命令構建邏輯
        java_command_str = ServerCommands.build_java_command(config, return_list=False)

        # 調試信息
        logger.debug(f"Java 命令: {java_command_str}")
        logger.debug(f"記憶體參數: {memory_args}")

        # Windows 批次檔
        bat_lines = [
            "@echo off",
            "chcp 65001 > nul",
            f"title {config.name} Minecraft Server",
            "echo ===============================================",
            f"echo   正在啟動 {config.name} 伺服器",
            f"echo   Minecraft 版本: {config.minecraft_version}",
            f"echo   模組載入器: {config.loader_type}",
            f"echo   記憶體配置: {memory_display}",
            "echo ===============================================",
            "echo.",
            "",
            java_command_str,
            "",
            "echo.",
            "echo 伺服器已停止運行",
        ]

        bat_content = "\n".join(bat_lines)

        start_script_path = server_path / "start_server.bat"

        # 比較現有檔案內容，避免不必要的磁碟寫入
        try:
            if start_script_path.exists():
                with open(start_script_path, "r", encoding="utf-8") as f:
                    existing_content = f.read()
                if existing_content == bat_content:
                    logger.debug("啟動腳本內容未變更，跳過寫入")
                    return
        except Exception as e:
            logger.debug(f"比較啟動腳本時發生錯誤 (將強制覆寫): {e}")

        with open(start_script_path, "w", encoding="utf-8") as f:
            f.write(bat_content)

    def update_server_properties(
        self, server_name: str, properties: Dict[str, str]
    ) -> bool:
        """
        更新 server.properties，只覆蓋有變動的欄位，其餘欄位保留原值
        update server.properties, only overwrite changed fields, keep other fields unchanged

        Args:
            server_name (str): 伺服器名稱
            properties (Dict[str, str]): 要更新的屬性字典

        Returns:
            bool: 更新成功返回 True，否則返回 False
        """
        try:
            config = self.servers.get(server_name)
            if not config:
                return False
            # 取得 server_path
            server_path = getattr(config, "path", None) or getattr(
                config, "server_path", None
            )
            if not server_path:
                logger.error(
                    f"找不到伺服器路徑，無法儲存 server.properties。config={config}"
                )
                return False
            properties_path = Path(server_path) / "server.properties"
            # 讀取原本的 server.properties
            if properties_path.exists():
                with open(properties_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                original = {}
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        original[k.strip()] = v.strip()
            else:
                original = {}
            # 合併：只覆蓋有變動的欄位
            merged = {**original, **properties}
            # 寫回
            with open(properties_path, "w", encoding="utf-8") as f:
                f.write("# Minecraft server properties\n")
                f.write("# Generated by Minecraft Server Manager\n\n")
                for k, v in merged.items():
                    f.write(f"{k}={v}\n")
            return True
        except Exception as e:
            logger.exception(f"update_server_properties 儲存失敗: {e}")
            return False

    def start_server(self, server_name: str, parent=None) -> bool:
        """
        啟動伺服器
        Start the server.

        Args:
            server_name (str): 伺服器名稱
            parent: 父級視窗，通常是主視窗

        Returns:
            bool: 啟動成功返回 True，否則返回 False
        """
        try:
            if server_name not in self.servers:
                UIUtils.show_error(
                    "伺服器未找到", f"找不到伺服器: {server_name}", parent=parent
                )
                return False

            config = self.servers[server_name]
            server_path = Path(config.path)

            if not server_path.exists():
                UIUtils.show_error(
                    "伺服器路徑不存在",
                    f"伺服器路徑不存在: {server_path}",
                    parent=parent,
                )
                return False

            # 尋找可用的啟動腳本
            script_path = ServerDetectionUtils.find_startup_script(server_path)

            if script_path:
                logger.info(f"找到啟動腳本: {script_path}")
            else:
                UIUtils.show_error(
                    "啟動腳本未找到",
                    "找不到啟動腳本 (run.bat, start_server.bat, start.bat, server.bat)",
                    parent=parent,
                )
                return False

            # 增加調試信息
            logger.debug(f"準備啟動伺服器: {server_name}")
            logger.debug(f"腳本路徑: {script_path}")
            logger.debug(f"工作目錄: {server_path}")

            # 啟動伺服器 (Windows)
            try:
                # 使用絕對路徑避免路徑問題
                abs_script_path = script_path.resolve()
                abs_server_path = server_path.resolve()

                # 建構正確的命令
                cmd = [str(abs_script_path)]
                logger.debug(f"執行命令: {cmd}")
                logger.debug(f"工作目錄: {abs_server_path}")

                # 在伺服器目錄中執行，支援標準輸入/輸出管道
                process = subprocess.Popen(
                    cmd,
                    cwd=str(abs_server_path),
                    shell=False,  # 安全性改進：移除 shell=True
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    bufsize=0,  # 無緩衝，立即輸出
                    universal_newlines=True,
                    creationflags=getattr(
                        subprocess, "CREATE_NO_WINDOW", 0
                    ),  # 隱藏 console 視窗
                )

                # 檢查進程是否立即失敗（減少等待時間提升響應）
                time.sleep(self.STARTUP_CHECK_DELAY)  # 等待進程啟動
                poll_result = process.poll()
                if poll_result is not None:
                    logger.error(f"進程立即結束，返回碼: {poll_result}")
                    # 嘗試讀取錯誤信息
                    try:
                        stdout, stderr = process.communicate(timeout=1)
                        logger.error(f"標準輸出: {stdout}")
                        if stderr:
                            logger.error(f"標準錯誤: {stderr}")
                    except Exception as e:
                        logger.exception(f"無法讀取錯誤信息: {e}")
                    UIUtils.show_error(
                        "啟動失敗",
                        f"伺服器進程立即結束，返回碼: {poll_result}",
                        parent=parent,
                    )
                    return False  # 記錄運行中的伺服器
                self.running_servers[server_name] = process

                # 使用等待線程來實現非阻塞的結束通知
                # 這樣就不需要 UI 端進行輪詢 (Polling) 了
                def _process_waiter(proc, name):
                    try:
                        proc.wait()  # 阻塞直到進程結束，但只阻塞這個線程
                        # 進程結束後的清理與通知 (可以在這裡擴充回調機制)
                        logger.info(
                            f"伺服器 {name} 已停止 (Exit code: {proc.returncode})"
                        )
                    except Exception as e:
                        logger.error(f"等待伺服器 {name}結束時發生錯誤: {e}")

                threading.Thread(
                    target=_process_waiter,
                    args=(process, server_name),
                    daemon=True,
                    name=f"Waiter-{server_name}",
                ).start()

                # 建立有界 deque 與 output thread（防止記憶體洩漏，原子操作）
                # 使用 deque 替代 Queue 以獲得更好的記憶體管理與原子操作
                output_deque = deque(maxlen=self.OUTPUT_QUEUE_MAX_SIZE)
                output_lock = threading.Lock()
                self.output_queues[server_name] = (output_deque, output_lock)

                def _output_reader(proc, output_data, name):
                    output_deque, output_lock = output_data
                    try:
                        while True:
                            line = None
                            try:
                                line = proc.stdout.readline()
                            except UnicodeDecodeError:
                                # 嘗試以 bytes 讀取並忽略非法字元
                                try:
                                    raw = proc.stdout.buffer.readline()
                                    line = raw.decode("utf-8", errors="ignore")
                                except Exception as e2:
                                    logger.exception(
                                        f"{name} 嚴重編碼錯誤: {e2}",
                                        "output_reader",
                                        e2,
                                    )
                                    continue
                            if not line:
                                break
                            # deque 的 append 在達到 maxlen 時會自動移除最舊項目（原子操作）
                            with output_lock:
                                output_deque.append(line.rstrip("\r\n"))
                            if proc.poll() is not None:
                                break
                    except Exception as e:
                        get_logger().bind(component="output_reader").exception(
                            f"{name} 讀取錯誤: {e}"
                        )

                t = threading.Thread(
                    target=_output_reader,
                    args=(process, (output_deque, output_lock), server_name),
                    daemon=True,
                )
                t.start()
                self.output_threads[server_name] = t

                logger.info(f"伺服器 {server_name} 啟動成功，PID: {process.pid}")
                return True

            except FileNotFoundError as e:
                logger.exception(f"檔案路徑錯誤: {e}")
                return False

        except Exception as e:
            logger.exception(f"啟動伺服器失敗: {e}")
            UIUtils.show_error("啟動失敗", f"無法啟動伺服器 {server_name}。錯誤: {e}")
            return False

    def delete_server(self, server_name: str) -> bool:
        """
        刪除伺服器
        Delete the server.

        Args:
            server_name (str): 伺服器名稱
        """
        try:
            if server_name not in self.servers:
                return False

            config = self.servers[server_name]
            server_path = Path(config.path)

            # 刪除伺服器目錄
            if server_path.exists():
                shutil.rmtree(server_path)

            # 從配置中移除
            del self.servers[server_name]
            self.save_servers_config()

            return True

        except Exception as e:
            logger.exception(f"刪除伺服器失敗: {e}")
            UIUtils.show_error("刪除失敗", f"無法刪除伺服器 {server_name}。錯誤: {e}")
            return False

    def load_servers_config(self) -> None:
        """
        載入伺服器配置
        Load server configuration.

        Args:
            config_file (Path): 伺服器配置檔案路徑
        """
        try:
            data = PathUtils.load_json(self.config_file)
            if data:
                for name, config_data in data.items():
                    self.servers[name] = ServerConfig(**config_data)
        except Exception as e:
            logger.exception(f"載入配置失敗: {e}")

    def save_servers_config(self) -> None:
        """
        儲存伺服器配置
        Save server configuration.

        Args:
            config_file (Path): 伺服器配置檔案路徑
        """
        try:
            data = {name: asdict(config) for name, config in self.servers.items()}
            PathUtils.save_json(self.config_file, data)
        except Exception as e:
            logger.exception(f"儲存配置失敗: {e}")

    def get_default_server_properties(self) -> Dict[str, str]:
        """
        獲取預設伺服器屬性
        Get default server properties.
        """
        return {
            "accepts-transfers": "false",
            "allow-flight": "false",
            "allow-nether": "true",
            "broadcast-console-to-ops": "true",
            "broadcast-rcon-to-ops": "true",
            "bug-report-link": "",
            "difficulty": "easy",
            "enable-command-block": "false",
            "enable-jmx-monitoring": "false",
            "enable-query": "false",
            "enable-rcon": "false",
            "enable-status": "true",
            "enforce-secure-profile": "true",
            "enforce-whitelist": "false",
            "entity-broadcast-range-percentage": "100",
            "force-gamemode": "false",
            "function-permission-level": "2",
            "gamemode": "survival",
            "generate-structures": "true",
            "generator-settings": "{}",
            "hardcore": "false",
            "hide-online-players": "false",
            "initial-disabled-packs": "",
            "initial-enabled-packs": "vanilla",
            "level-name": "world",
            "level-seed": "",
            "level-type": "minecraft:normal",
            "log-ips": "true",
            "max-chained-neighbor-updates": "1000000",
            "max-players": "20",
            "max-tick-time": "60000",
            "max-world-size": "29999984",
            "motd": "A Minecraft Server",
            "network-compression-threshold": "256",
            "online-mode": "true",
            "op-permission-level": "4",
            "pause-when-empty-seconds": "60",
            "player-idle-timeout": "0",
            "prevent-proxy-connections": "false",
            "pvp": "true",
            "query.port": "25565",
            "rate-limit": "0",
            "rcon.password": "",
            "rcon.port": "25575",
            "region-file-compression": "deflate",
            "require-resource-pack": "false",
            "resource-pack": "",
            "resource-pack-id": "",
            "resource-pack-prompt": "",
            "resource-pack-sha1": "",
            "server-ip": "",
            "server-port": "25565",
            "simulation-distance": "10",
            "spawn-monsters": "true",
            "spawn-protection": "16",
            "sync-chunk-writes": "true",
            "text-filtering-config": "",
            "text-filtering-version": "0",
            "use-native-transport": "true",
            "view-distance": "10",
            "white-list": "false",
        }

    def server_exists(self, name: str) -> bool:
        """
        檢查伺服器是否已存在
        Check if the server exists.

        Args:
            name (str): 伺服器名稱
        """
        return name in self.servers

    def add_server(self, config: ServerConfig) -> bool:
        """
        添加伺服器配置（用於匯入）
        Add server configuration (for import).

        Args:
            config (ServerConfig): 伺服器配置
        """
        try:
            self.servers[config.name] = config
            self.save_servers_config()
            return True
        except Exception as e:
            logger.exception(f"添加伺服器失敗: {e}")
            return False

    def load_server_properties(self, server_name: str) -> Dict[str, str]:
        """
        載入伺服器的 server.properties 檔案內容 (附帶緩存機制)
        Load the server.properties file content for the server (with caching).

        Args:
            server_name (str): 伺服器名稱

        Returns:
            Dict[str, str]: 伺服器屬性設定
        """
        try:
            if server_name not in self.servers:
                return {}

            config = self.servers[server_name]
            server_path = Path(config.path)
            properties_file = server_path / "server.properties"

            # 檢查檔案是否存在
            if not properties_file.exists():
                return {}

            # 檢查檔案修改時間
            try:
                mtime = properties_file.stat().st_mtime
            except OSError:
                return {}

            cached_mtime, cached_props = self._properties_cache.get(
                server_name, (0, None)
            )
            if cached_props is not None and mtime == cached_mtime:
                return cached_props

            # 使用統一的載入方法
            properties = ServerPropertiesHelper.load_properties(properties_file)
            self._properties_cache[server_name] = (mtime, properties)

            # 更新配置中的屬性
            config.properties = properties
            self.save_servers_config()

            return properties

        except Exception as e:
            logger.exception(f"讀取 server.properties 失敗: {e}")
            return {}

    def is_server_running(self, server_name: str) -> bool:
        """
        檢查伺服器是否正在運行
        Check if the server is running.

        Args:
            server_name (str): 伺服器名稱

        Returns:
            bool: 如果伺服器正在運行，則為 True，否則為 False
        """
        if server_name not in self.running_servers:
            return False

        process = self.running_servers[server_name]
        if process.poll() is None:  # 程序還在運行
            return True
        else:
            # 程序已結束，從記錄中移除
            del self.running_servers[server_name]
            return False

    def stop_server(self, server_name: str) -> bool:
        """
        停止伺服器
        Stop the server.

        Args:
            server_name (str): 伺服器名稱
        """
        try:
            if server_name not in self.running_servers:
                logger.info(f"伺服器 {server_name} 未在運行")
                return False

            process = self.running_servers[server_name]
            if process.poll() is None:  # 程序還在運行
                # 先嘗試優雅停止
                try:
                    process.stdin.write("stop\n")
                    process.stdin.flush()
                    # 等待 5 秒讓伺服器自己停止
                    process.wait(timeout=5)
                except (subprocess.TimeoutExpired, OSError, BrokenPipeError):
                    # 如果優雅停止失敗，使用 terminate
                    try:
                        process.terminate()
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        # 最後手段：強制終止
                        process.kill()
                        process.wait()

                logger.info(f"伺服器 {server_name} 已停止")

            # 清理所有相關資源
            del self.running_servers[server_name]

            # 清理輸出佇列和執行緒
            if hasattr(self, "output_queues") and server_name in self.output_queues:
                del self.output_queues[server_name]
            if hasattr(self, "output_threads") and server_name in self.output_threads:
                del self.output_threads[server_name]

            return True

        except Exception as e:
            logger.exception(f"停止伺服器失敗: {e}")
            # 即使出現錯誤，也要清理記錄
            if server_name in self.running_servers:
                del self.running_servers[server_name]
            return False

    def get_server_info(self, server_name: str) -> Optional[Dict]:
        """
        獲取伺服器資訊，包括運行狀態和資源使用，補齊 UI 需要的欄位
        Get server information, including running status and resource usage, fill in the fields needed by the UI.

        Args:
            server_name (str): 伺服器名稱

        Returns:
            Optional[Dict]: 伺服器資訊字典，如果伺服器不存在則為 None
        """
        try:
            if server_name not in self.servers:
                return None

            config = self.servers[server_name]
            info = {
                "name": server_name,
                "config": asdict(config),
                "is_running": self.is_server_running(server_name),
                "pid": None,
                "cpu_percent": 0.0,
                "memory_mb": 0.0,
                "memory": 0,
                "uptime": "00:00:00",
                "players": 0,  # 由 UI 端 list 指令即時更新
                "max_players": 0,
                "version": "N/A",
            }

            # 讀取 server.properties 以取得 max_players 與 version
            try:
                properties = self.load_server_properties(server_name)
                if properties:
                    max_players = properties.get("max-players") or properties.get(
                        "max_players"
                    )
                    if max_players:
                        try:
                            info["max_players"] = int(max_players)
                        except Exception:
                            info["max_players"] = 0
                    # 版本顯示為 mc_version(loader_type)
                    mc_version = getattr(config, "minecraft_version", None)
                    loader_type = getattr(config, "loader_type", None)
                    if mc_version and loader_type:
                        info["version"] = f"{mc_version}({loader_type})"
                    elif mc_version:
                        info["version"] = str(mc_version)
                    elif "version" in properties:
                        info["version"] = str(properties["version"])
            except Exception as e:
                logger.exception(f"讀取 server.properties 失敗: {e}")

            if self.is_server_running(server_name):
                process = self.running_servers[server_name]
                info["pid"] = process.pid
                try:
                    if psutil:
                        ps_process = psutil.Process(process.pid)
                        # 收集所有相關 java 進程（自己+所有子孫）
                        all_candidates = []
                        try:
                            if ps_process.name().lower().startswith("java"):
                                all_candidates.append(ps_process)
                        except Exception as e:
                            logger.exception(
                                f"取得進程名稱失敗 pid={process.pid}: {e}",
                                "ServerManager",
                                e,
                            )
                        try:
                            all_candidates.extend(
                                [
                                    c
                                    for c in ps_process.children(recursive=True)
                                    if c.name().lower().startswith("java")
                                ]
                            )
                        except Exception as e:
                            logger.exception(
                                f"取得子進程清單失敗 pid={process.pid}: {e}",
                                "ServerManager",
                                e,
                            )

                        # 選擇 cmdline 含 server.jar/fabric/forge 關鍵字且記憶體用量最大的 java 進程
                        def is_server_java(proc):
                            try:
                                cmd = " ".join(proc.cmdline()).lower()
                                return any(
                                    k in cmd for k in ["server.jar", "fabric", "forge"]
                                )
                            except Exception:
                                return False

                        server_java_candidates = [
                            p for p in all_candidates if is_server_java(p)
                        ]
                        if server_java_candidates:
                            # 取記憶體用量最大的
                            target_proc = max(
                                server_java_candidates,
                                key=lambda p: p.memory_info().rss,
                            )
                        elif all_candidates:
                            target_proc = max(
                                all_candidates, key=lambda p: p.memory_info().rss
                            )
                        else:
                            target_proc = ps_process
                        # 更新 info 以 Java 進程為主
                        info["pid"] = target_proc.pid
                        cpu_percent = target_proc.cpu_percent()
                        memory_info = target_proc.memory_info()
                        create_time = target_proc.create_time()
                        info["cpu_percent"] = cpu_percent
                        info["memory_mb"] = memory_info.rss / 1024 / 1024
                        info["memory"] = int(memory_info.rss / 1024 / 1024)
                        # 計算運行時間
                        uptime_seconds = int(time.time() - create_time)
                        hours = uptime_seconds // 3600
                        minutes = (uptime_seconds % 3600) // 60
                        seconds = uptime_seconds % 60
                        info["uptime"] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                except (psutil.NoSuchProcess, psutil.AccessDenied, Exception) as e:
                    logger.warning(f"無法獲取程序資訊，可能已停止: {e}")
                    if server_name in self.running_servers:
                        if self.running_servers[server_name].poll() is not None:
                            del self.running_servers[server_name]
                            info["is_running"] = False
            return info

        except Exception as e:
            logger.exception(f"獲取伺服器資訊失敗: {e}")
            return None

    def send_command(self, server_name: str, command: str) -> bool:
        """
        向運行中的伺服器發送命令
        Send a command to the running server.

        Args:
            server_name (str): 伺服器名稱
            command (str): 要發送的命令

        Returns:
            bool: 如果命令發送成功則為 True，否則為 False
        """
        try:
            if server_name not in self.running_servers:
                logger.info(f"伺服器 {server_name} 未在運行")
                return False

            process = self.running_servers[server_name]
            if process.poll() is not None:  # 程序已結束
                del self.running_servers[server_name]
                logger.info(f"伺服器 {server_name} 程序已結束")
                return False

            # 發送命令
            if process.stdin:
                process.stdin.write(command + "\n")
                process.stdin.flush()
                logger.debug(f"已向伺服器 {server_name} 發送命令: {command}")

                # 如果是停止命令，啟動更頻繁的檢查（優化等待邏輯）
                if command.lower() == "stop":

                    def check_stop():
                        # 使用輪詢檢查，總時長約 5 秒
                        for i in range(self.MAX_STOP_CHECKS):
                            time.sleep(self.STOP_CHECK_INTERVAL)
                            if process.poll() is not None:
                                # 程序已停止
                                if server_name in self.running_servers:
                                    del self.running_servers[server_name]
                                    logger.info(
                                        f"伺服器 {server_name} 已確認停止",
                                        "ServerManager",
                                    )
                                break

                    # 在背景執行檢查
                    threading.Thread(target=check_stop, daemon=True).start()

                return True
            else:
                logger.error(
                    f"無法向伺服器 {server_name} 發送命令：stdin 不可用",
                    "ServerManager",
                )
                return False

        except Exception as e:
            logger.exception(f"發送命令失敗: {e}")
            return False

    def read_server_output(self, server_name: str, timeout: float = 0.1) -> List[str]:
        """
        讀取伺服器輸出（非阻塞，避免 readline 卡住）
        Read server output (non-blocking, avoid readline blocking).

        Args:
            server_name (str): 伺服器名稱
            timeout (float): 讀取超時時間

        Returns:
            List[str]: 伺服器輸出行列表
        """
        try:
            if server_name not in self.running_servers:
                return []

            process = self.running_servers[server_name]
            if process.poll() is not None:  # 程序已結束
                if server_name in self.running_servers:
                    del self.running_servers[server_name]
                return []

            output_lines = []

            output_data = self.output_queues.get(server_name)
            if not output_data:
                return []

            output_deque, output_lock = output_data
            # 從 deque 讀取所有可用輸出（原子操作）
            with output_lock:
                output_lines = list(output_deque)
                output_deque.clear()

            return output_lines
        except Exception as e:
            logger.exception(f"讀取伺服器輸出失敗: {e}")
            return []

    def get_server_log_file(self, server_name: str) -> Optional[Path]:
        """
        獲取伺服器日誌檔案路徑
        Get the server log file path.

        Args:
            server_name (str): 伺服器名稱

        Returns:
            Optional[Path]: 伺服器日誌檔案路徑，如果不存在則為 None
        """
        try:
            if server_name not in self.servers:
                return None

            server_config = self.servers[server_name]
            server_path = Path(server_config.path)

            # 檢查常見的日誌檔案位置
            log_files = [
                server_path / "logs" / "latest.log",
                server_path / "server.log",
                server_path / "logs" / "server.log",
            ]

            for log_file in log_files:
                if log_file.exists():
                    return log_file

            return None

        except Exception as e:
            logger.exception(f"獲取伺服器日誌檔案失敗: {e}")
            return None
