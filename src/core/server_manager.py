#!/usr/bin/env python3
"""伺服器管理器
負責建立、管理和配置 Minecraft 伺服器
Server Manager
Responsible for creating, managing, and configuring Minecraft servers.
"""

import contextlib
import os
import threading
import time
from collections import deque
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..models import ServerConfig
from ..utils import (
    MemoryUtils,
    PathUtils,
    ServerCommands,
    ServerDetectionUtils,
    ServerPropertiesHelper,
    SubprocessUtils,
    SystemUtils,
    UIUtils,
    get_logger,
)

logger = get_logger().bind(component="ServerManager")


class ServerManager:
    """負責建立、管理和配置 Minecraft 伺服器"""

    # ====== 類別常數 ======
    STARTUP_CHECK_DELAY = 0.1  # 伺服器啟動檢查延遲（秒）
    STOP_CHECK_INTERVAL = 0.1  # 停止檢查間隔（秒）
    STOP_TIMEOUT_SECONDS = 5  # 停止超時時間（秒）
    MAX_STOP_CHECKS = int(STOP_TIMEOUT_SECONDS / STOP_CHECK_INTERVAL)
    OUTPUT_QUEUE_MAX_SIZE = 1000  # 輸出佇列最大容量

    # ====== 初始化與配置管理 ======
    def __init__(self, servers_root: str | None = None):
        if not servers_root:
            raise ValueError("ServerManager 必須指定 servers_root 路徑，且不可為空。請於 UI 層先處理。")
        self.servers_root = Path(servers_root).resolve()
        self.servers_root.mkdir(parents=True, exist_ok=True)
        self.config_file = self.servers_root / "servers_config.json"
        self.servers: dict[str, ServerConfig] = {}
        self.running_servers: dict[str, Any] = {}  # 追踪運行中的伺服器
        self.output_queues: dict[str, tuple[deque, threading.Lock]] = {}  # server_name -> (deque, lock)
        self.output_threads: dict[str, threading.Thread] = {}  # server_name -> Thread
        self._properties_cache: dict[str, Any] = {}  # server_name -> (mtime, properties)
        self._config_lock = threading.Lock()  # 配置檔案讀寫鎖，防止併發寫入衝突
        self._save_schedule_lock = threading.Lock()
        self._pending_save = False
        self._save_timer: threading.Timer | None = None
        self._save_debounce_sec = 6.0
        self.load_servers_config()

    # ====== 伺服器建立與設定 ======
    def create_server(self, config: ServerConfig, properties: dict[str, str] | None = None) -> bool:
        """建立新伺服器並初始化設定"""
        try:
            server_path = (self.servers_root / config.name).resolve()

            is_safe = False
            try:
                is_safe = server_path.is_relative_to(self.servers_root)
            except AttributeError:
                try:
                    server_path.relative_to(self.servers_root)
                    is_safe = True
                except ValueError:
                    is_safe = False

            if not is_safe:
                raise ValueError(f"無效的伺服器名稱 (路徑遍歷偵測): {config.name}")

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
                    and (not config.loader_version or config.loader_version == "unknown")
                )
            )
            if need_detect:
                try:
                    ServerDetectionUtils.detect_server_type(server_path, config)
                    # 強制補齊欄位
                    if not config.loader_type or config.loader_type == "unknown":
                        raise Exception(
                            f"偵測失敗：loader_type 無法判斷，name={config.name}, path={config.path}, loader_type={config.loader_type}, minecraft_version={config.minecraft_version}, loader_version={config.loader_version}",
                        )
                    if not config.minecraft_version or config.minecraft_version == "unknown":
                        raise Exception(
                            f"偵測失敗：minecraft_version 無法判斷，name={config.name}, path={config.path}, loader_type={config.loader_type}, minecraft_version={config.minecraft_version}, loader_version={config.loader_version}",
                        )
                    if config.loader_type.lower() in ["forge", "fabric"] and (
                        not config.loader_version or config.loader_version == "unknown"
                    ):
                        raise Exception(
                            f"偵測失敗：loader_version 無法判斷，name={config.name}, path={config.path}, loader_type={config.loader_type}, minecraft_version={config.minecraft_version}, loader_version={config.loader_version}",
                        )
                except Exception as e:
                    logger.error(f"自動偵測伺服器類型失敗: {e}")
                    raise
            # 儲存配置
            self.servers[config.name] = config
            self.write_servers_config()
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
        """建立並同意 EULA 檔案"""
        eula_content = """eula=true"""
        PathUtils.write_text_file(server_path / "eula.txt", eula_content)

    def _create_server_structure(self, path: Path, loader_type: str) -> None:
        """建立伺服器檔案結構"""
        # 建立基本目錄
        if loader_type.lower() == "vanilla":
            directories = ["world", "logs"]
        elif loader_type.lower() in ["forge", "fabric"]:
            directories = ["world", "plugins", "mods", "config", "logs"]
        else:
            directories = ["world", "logs"]
            logger.warning(f"未知 loader_type: {loader_type}，使用預設目錄結構")

        for directory in directories:
            (path / directory).mkdir(exist_ok=True)

    def create_launch_script(self, config: ServerConfig) -> None:
        """建立伺服器啟動腳本"""
        server_path = Path(config.path)

        # 計算記憶體設定
        max_memory = config.memory_max_mb
        min_memory = config.memory_min_mb

        # 構建 Java 記憶體參數
        memory_args = f"-Xmx{max_memory}M"
        if min_memory:
            memory_args = f"-Xmx{max_memory}M -Xms{min_memory}M"
            memory_display = (
                f"最小 {MemoryUtils.format_memory_mb(min_memory)}, 最大 {MemoryUtils.format_memory_mb(max_memory)}"
            )
        else:
            memory_display = f"Java自行取用-{MemoryUtils.format_memory_mb(max_memory)}"

        # 使用統一的 Java 命令構建邏輯（返回列表形式便於處理）
        java_cmd_list = ServerCommands.build_java_command(config, return_list=True)

        # 除錯訊息
        logger.debug(f"Java 命令列表: {java_cmd_list}")
        logger.debug(f"記憶體參數: {memory_args}")

        # 處理命令列表，轉換為批次檔相容格式
        # 確保路徑使用絕對路徑並加上引號
        java_exe = java_cmd_list[0]
        if " " in java_exe and not (java_exe.startswith('"') and java_exe.endswith('"')):
            java_exe = f'"{java_exe}"'

        # 檢查是否使用 @args.txt 格式（Forge）
        # java_cmd_list 格式：[java_exe, "@args.txt", "nogui"] 或更多參數
        uses_args_file = len(java_cmd_list) >= 2 and java_cmd_list[1].startswith("@")

        if uses_args_file:
            # Forge 伺服器：使用 @args.txt（包含 JVM 參數），需要添加 nogui 參數
            args_spec = java_cmd_list[1]
            args_rel_path = args_spec[1:]  # 移除 @ 符號
            args_path = server_path / args_rel_path
            if args_path.exists():
                java_command_str = f"{java_exe} {args_spec} nogui"
            else:
                logger.warning(f"參數檔案不存在: {args_path}")
                java_command_str = f"{java_exe} {args_spec} nogui"
        else:
            # 其他伺服器（Vanilla / Fabric）：使用 -jar 格式
            cmd_parts = [java_exe]

            # 從列表中提取參數並轉換 JAR 路徑
            i = 1
            while i < len(java_cmd_list):
                arg = java_cmd_list[i]
                if arg == "-jar" and i + 1 < len(java_cmd_list):
                    cmd_parts.append(arg)
                    jar_spec = java_cmd_list[i + 1]
                    jar_path = server_path / jar_spec
                    if jar_path.exists():
                        cmd_parts.append(f'"{jar_path.resolve()}"')
                    else:
                        cmd_parts.append(f'"{jar_spec}"')
                    i += 2
                else:
                    cmd_parts.append(arg)
                    i += 1

            java_command_str = " ".join(cmd_parts)

        # Windows 批次檔
        bat_lines = [
            "@echo off",
            f"title {config.name} Minecraft Server",
            "echo ===============================================",
            f"echo 正在啟動 {config.name} 伺服器",
            f"echo Minecraft 版本: {config.minecraft_version}",
            f"echo 模組載入器: {config.loader_type}",
            f"echo 記憶體配置: {memory_display}",
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

        # 比較現有檔案內容，避免不必要的磁碟寫入（使用 GBK 編碼來自動比較）
        try:
            if start_script_path.exists():
                existing_content = PathUtils.read_text_file(start_script_path, encoding="gbk", errors="ignore")
                if existing_content == bat_content:
                    logger.debug("啟動腳本內容未變更，跳過寫入")
                    return
        except Exception as e:
            logger.debug(f"比較啟動腳本時發生錯誤 (將強制覆寫): {e}")

        # 使用 GBK/ANSI 編碼寫入批次檔，避免 "is not recognized" 錯誤
        PathUtils.write_text_file(start_script_path, bat_content, encoding="gbk", errors="replace")

    def update_server_properties(self, server_name: str, properties: dict[str, str]) -> bool:
        """更新 server.properties，只覆蓋有變動的欄位，其餘欄位保留原值"""
        try:
            config = self.servers.get(server_name)
            if not config:
                return False
            # 取得 server_path
            server_path = getattr(config, "path", None) or getattr(config, "server_path", None)
            if not server_path:
                logger.error(f"找不到伺服器路徑，無法儲存 server.properties。config={config}")
                return False
            properties_path = Path(server_path) / "server.properties"
            original = ServerPropertiesHelper.load_properties(properties_path)
            # 合併：只覆蓋有變動的欄位
            merged = {**original, **properties}
            # 寫回
            ServerPropertiesHelper.save_properties(properties_path, merged)
            # 同步更新記憶體中的配置並保存到 servers_config.json
            config.properties = merged
            self.write_servers_config()
            return True
        except Exception as e:
            logger.exception(f"update_server_properties 儲存失敗: {e}")
            return False

    def start_server(self, server_name: str, parent=None) -> bool:
        """啟動伺服器"""
        try:
            if server_name not in self.servers:
                UIUtils.show_error("伺服器未找到", f"找不到伺服器: {server_name}", parent=parent)
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

            # 確保啟動腳本存在且是最新的（每次啟動前重新建立，確保 JVM 參數正確）
            self.create_launch_script(config)

            # 尋找可用的啟動腳本（優先使用 start_server.bat）
            script_path = ServerDetectionUtils.find_startup_script(server_path)

            if script_path:
                logger.info(f"找到啟動腳本: {script_path}")
            else:
                UIUtils.show_error(
                    "啟動腳本未找到",
                    "找不到啟動腳本 (start_server.bat, run.bat, start.bat, server.bat)",
                    parent=parent,
                )
                return False

            # 增加除錯資訊
            logger.debug(f"準備啟動伺服器: {server_name}")
            logger.debug(f"腳本路徑: {script_path}")
            logger.debug(f"工作目錄: {server_path}")

            try:
                # 使用絕對路徑避免路徑問題
                abs_script_path = script_path.resolve()
                abs_server_path = server_path.resolve()

                # 建構正確的命令
                cmd = [str(abs_script_path)]
                logger.debug(f"執行命令: {cmd}")
                logger.debug(f"工作目錄: {abs_server_path}")

                # 在伺服器目錄中執行，支援標準輸入/輸出管道
                process = SubprocessUtils.popen_checked(
                    cmd,
                    cwd=str(abs_server_path),
                    stdin=SubprocessUtils.PIPE,
                    stdout=SubprocessUtils.PIPE,
                    stderr=SubprocessUtils.STDOUT,
                    text=True,
                    encoding="utf-8",
                    bufsize=0,  # 無緩衝，立即輸出
                    universal_newlines=True,
                    creationflags=SubprocessUtils.CREATE_NO_WINDOW,  # 隱藏 console 視窗
                )
                process.create_time = time.time()

                # 檢查行程是否立即失敗（減少等待時間提升響應）
                time.sleep(self.STARTUP_CHECK_DELAY)  # 等待行程啟動
                poll_result = process.poll()
                if poll_result is not None:
                    logger.error(f"行程立即結束，返回碼: {poll_result}")
                    # 嘗試讀取錯誤資訊
                    try:
                        stdout, _ = process.communicate(timeout=1)
                        if stdout:
                            logger.error(f"程式輸出: {stdout}")
                    except Exception as e:
                        logger.exception(f"無法讀取程式輸出: {e}")

                    # 檢查啟動腳本內容以供除錯
                    script_content = PathUtils.read_text_file(script_path)
                    if script_content is not None:
                        logger.debug(f"啟動腳本內容:\n{script_content}")
                    else:
                        logger.error(f"無法讀取啟動腳本: {script_path}")

                    UIUtils.show_error(
                        "啟動失敗",
                        f"伺服器行程立即結束，返回碼: {poll_result}\n請檢查日誌了解詳細資訊",
                        parent=parent,
                    )
                    return False  # 記錄運行中的伺服器
                self.running_servers[server_name] = process

                # 使用等待線程來實現非阻塞的結束通知
                def _process_waiter(proc, name):
                    try:
                        proc.wait()
                        logger.info(f"伺服器 {name} 已停止 (Exit code: {proc.returncode})")
                    except Exception as e:
                        logger.error(f"等待伺服器 {name}結束時發生錯誤: {e}")

                threading.Thread(
                    target=_process_waiter,
                    args=(process, server_name),
                    daemon=True,
                    name=f"Waiter-{server_name}",
                ).start()

                output_deque: deque[str] = deque(maxlen=self.OUTPUT_QUEUE_MAX_SIZE)
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
                        get_logger().bind(component="output_reader").exception(f"{name} 讀取錯誤: {e}")

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
        """刪除伺服器"""
        try:
            if server_name not in self.servers:
                return False

            config = self.servers[server_name]
            server_path = Path(config.path)

            # 刪除伺服器目錄
            PathUtils.delete_path(server_path)

            # 從配置中移除
            del self.servers[server_name]
            self.write_servers_config()

            return True
        except Exception as e:
            logger.exception(f"刪除伺服器失敗: {e}")
            UIUtils.show_error("刪除失敗", f"無法刪除伺服器 {server_name}。錯誤: {e}")
            return False

    def load_servers_config(self) -> None:
        """載入伺服器配置"""
        with self._config_lock:
            try:
                data = PathUtils.load_json(self.config_file)
                if data is not None:
                    self.servers.clear()
                    for name, config_data in data.items():
                        # 假設 ServerConfig 是一個資料類型，並且可以從字典初始化
                        self.servers[name] = ServerConfig(**config_data)
                else:
                    logger.warning("伺服器配置文件為空或無法解析")
            except Exception as e:
                logger.exception(f"載入配置失敗: {e}")

    def write_servers_config(self) -> None:
        """實際執行保存伺服器配置到 servers_config.json"""
        with self._config_lock:
            try:
                data = {k: asdict(v) for k, v in self.servers.items()}
                if not PathUtils.save_json(self.config_file, data):
                    logger.error("保存伺服器配置失敗: 無法寫入文件")
                else:
                    logger.info("伺服器配置已保存到 servers_config.json")
                    # 確保檔案同步到磁碟
                    with open(self.config_file, "r+b") as f:
                        os.fsync(f.fileno())
            except Exception as e:
                logger.exception(f"保存伺服器配置失敗: {e}")

    def get_default_server_properties(self) -> dict[str, str]:
        """獲取預設伺服器屬性"""
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
        """檢查伺服器是否已存在"""
        return name in self.servers

    def add_server(self, config: ServerConfig) -> bool:
        """添加伺服器配置（用於匯入）"""
        try:
            self.servers[config.name] = config
            self.write_servers_config()
            return True
        except Exception as e:
            logger.exception(f"添加伺服器失敗: {e}")
            return False

    def load_server_properties(self, server_name: str) -> dict[str, str]:
        """載入伺服器的 server.properties 檔案內容 (附帶緩存機制)"""
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

            cached_mtime, cached_props = self._properties_cache.get(server_name, (0, None))
            if cached_props is not None and mtime == cached_mtime:
                return cached_props

            # 使用統一的載入方法
            properties = ServerPropertiesHelper.load_properties(properties_file)
            self._properties_cache[server_name] = (mtime, properties)

            # 更新配置中的屬性
            config.properties = properties
            self.write_servers_config()

            return properties

        except Exception as e:
            logger.exception(f"讀取 server.properties 失敗: {e}")
            return {}

    def is_server_running(self, server_name: str) -> bool:
        """檢查伺服器是否正在運行"""
        if server_name not in self.running_servers:
            return False

        process = self.running_servers[server_name]
        if process.poll() is None:  # 程式還在運行
            return True
        # 程式已結束，從記錄中移除
        del self.running_servers[server_name]
        return False

    def stop_server(self, server_name: str) -> bool:
        """停止伺服器"""
        try:
            if server_name not in self.running_servers:
                logger.info(f"伺服器 {server_name} 未在運行")
                return False

            process = self.running_servers[server_name]
            if process.poll() is None:  # 程式還在運行
                # 先嘗試優雅停止
                try:
                    if process.stdin:
                        process.stdin.write("stop\n")
                        process.stdin.flush()
                    # 等待 5 秒讓伺服器自己停止
                    process.wait(timeout=5)
                except (SubprocessUtils.TimeoutExpired, OSError, BrokenPipeError):
                    # 如果優雅停止失敗，使用 terminate
                    try:
                        process.terminate()
                        process.wait(timeout=5)
                    except SubprocessUtils.TimeoutExpired:
                        # 最後手段：強制終止 (Force kill process tree)
                        SystemUtils.kill_process_tree(process.pid)
                        with contextlib.suppress(SubprocessUtils.TimeoutExpired):
                            process.wait(timeout=1)

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

    def get_server_info(self, server_name: str) -> dict | None:
        """獲取伺服器資訊，包括運行狀態和資源使用，補齊 UI 需要的欄位"""
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
                "players": 0,
                "max_players": 0,
                "version": "N/A",
            }

            # 讀取 server.properties 以取得 max_players 與 version
            try:
                properties = self.load_server_properties(server_name)
                if properties:
                    max_players = properties.get("max-players") or properties.get("max_players")
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
                if not SystemUtils.is_process_running(process.pid):
                    info["is_running"] = False
                    if server_name in self.running_servers:
                        del self.running_servers[server_name]
                    return info

                info["is_running"] = True

                # 嘗試查找真實的 Java 進程以獲取精確記憶體使用量
                java_pid = getattr(process, "java_pid", None)
                if not java_pid:
                    java_pid = SystemUtils.find_java_process(process.pid)
                    if java_pid:
                        process.java_pid = java_pid  # 快取起來

                target_pid = java_pid if java_pid else process.pid
                # 更新 PID 顯示為真實 Java PID
                if java_pid:
                    info["pid"] = java_pid

                # 獲取記憶體使用量 (Bytes -> MB)
                mem_bytes = SystemUtils.get_process_memory_usage(target_pid)
                info["memory"] = mem_bytes / (1024 * 1024)
                info["memory_mb"] = info["memory"]

                try:
                    if hasattr(process, "create_time"):
                        create_time = process.create_time
                        uptime_seconds = int(time.time() - create_time)
                        hours = uptime_seconds // 3600
                        minutes = (uptime_seconds % 3600) // 60
                        seconds = uptime_seconds % 60
                        info["uptime"] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                except Exception as e:
                    logger.exception(f"計算伺服器運行時間失敗: {e}")
            return info

        except Exception as e:
            logger.exception(f"獲取伺服器資訊失敗: {e}")
            return None

    def send_command(self, server_name: str, command: str) -> bool:
        """向運行中的伺服器發送命令"""
        try:
            if server_name not in self.running_servers:
                logger.info(f"伺服器 {server_name} 未在運行")
                return False

            process = self.running_servers[server_name]
            if process.poll() is not None:  # 程式已結束
                del self.running_servers[server_name]
                logger.info(f"伺服器 {server_name} 程式已結束")
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
                        for _i in range(self.MAX_STOP_CHECKS):
                            time.sleep(self.STOP_CHECK_INTERVAL)
                            if process.poll() is not None:
                                # 程式已停止
                                if server_name in self.running_servers:
                                    del self.running_servers[server_name]
                                    logger.info(f"伺服器 {server_name} 已確認停止")
                                break

                    # 在背景執行檢查
                    threading.Thread(target=check_stop, daemon=True).start()

                return True
            logger.error(
                f"無法向伺服器 {server_name} 發送命令：stdin 不可用",
                "ServerManager",
            )
            return False

        except Exception as e:
            logger.exception(f"發送命令失敗: {e}")
            return False

    def read_server_output(self, server_name: str, _timeout: float = 0.1) -> list[str]:
        """讀取伺服器輸出"""
        try:
            if server_name not in self.running_servers:
                return []

            process = self.running_servers[server_name]
            if process.poll() is not None:  # 程式已結束
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

    def get_server_log_file(self, server_name: str) -> Path | None:
        """獲取伺服器日誌檔案路徑"""
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
