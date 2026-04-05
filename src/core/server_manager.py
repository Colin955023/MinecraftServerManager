"""伺服器管理器
負責建立、管理與配置 Minecraft 伺服器。
"""

import contextlib
import threading
import time
from dataclasses import asdict, is_dataclass
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
    atomic_write_json,
    get_logger,
    record_and_mark,
)
from . import ServerInstance

logger = get_logger().bind(component="ServerManager")


class ServerManager:
    """負責建立、管理和配置 Minecraft 伺服器"""

    STARTUP_CHECK_DELAY = 0.1
    STOP_CHECK_INTERVAL = 0.1
    STOP_TIMEOUT_SECONDS = 5
    OUTPUT_QUEUE_MAX_SIZE = 1000

    def __init__(self, servers_root: str | None = None):
        if not servers_root:
            raise ValueError("ServerManager 必須指定 servers_root 路徑，且不可為空。請於 UI 層先處理。")
        self.servers_root = Path(servers_root).resolve()
        self.servers_root.mkdir(parents=True, exist_ok=True)
        self.config_file = self.servers_root / "servers_config.json"
        self.servers: dict[str, ServerConfig] = {}
        self.running_servers: dict[str, ServerInstance] = {}
        self._properties_cache: dict[str, Any] = {}
        self._config_lock = threading.Lock()
        self.load_servers_config()

    def _cleanup_running_server_state(self, server_name: str) -> None:
        """清除執行中伺服器的 runtime 狀態。"""
        instance = self.running_servers.pop(server_name, None)
        if instance is not None:
            instance.clear_process()
            instance.clear_output_buffer()

    def _get_running_instance(self, server_name: str) -> ServerInstance | None:
        """取得仍在執行中的 instance；若已過期則自動清理。"""
        instance = self.running_servers.get(server_name)
        if instance is None:
            return None
        try:
            if instance.is_running():
                return instance
        except Exception as e:
            logger.error(f"檢查伺服器狀態時發生錯誤: {e}")
        process = instance.get_process()
        if process is None:
            self._cleanup_running_server_state(server_name)
            return None
        self._cleanup_running_server_state(server_name)
        return None

    @staticmethod
    def _wait_for_process_exit(process: Any, timeout_seconds: float, interval_seconds: float | None = None) -> bool:
        """在指定期限內等待 process 結束，並以 Event.wait 取代 sleep 輪詢。"""
        if timeout_seconds <= 0:
            return process.poll() is not None
        wait_interval = interval_seconds if interval_seconds and interval_seconds > 0 else timeout_seconds
        deadline = time.monotonic() + timeout_seconds
        waiter = threading.Event()
        while True:
            if process.poll() is not None:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return process.poll() is not None
            waiter.wait(min(wait_interval, remaining))

    def create_server(self, config: ServerConfig, properties: dict[str, str] | None = None) -> bool:
        """建立新伺服器並初始化設定。

        Args:
            config: 要建立的伺服器設定。
            properties: 要寫入 server.properties 的初始屬性。

        Returns:
            建立成功時回傳 True，失敗時回傳 False。
        """
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
            config.path = str(server_path)
            need_detect = (
                not config.loader_type
                or config.loader_type == "unknown"
                or (not config.minecraft_version)
                or (config.minecraft_version == "unknown")
                or (
                    config.loader_type
                    and config.loader_type.lower() in ["forge", "fabric"]
                    and (not config.loader_version or config.loader_version == "unknown")
                )
            )
            if need_detect:
                try:
                    ServerDetectionUtils.detect_server_type(server_path, config)
                    if not config.loader_type or config.loader_type == "unknown":
                        raise Exception(
                            f"偵測失敗：loader_type 無法判斷，name={config.name}, path={config.path}, loader_type={config.loader_type}, minecraft_version={config.minecraft_version}, loader_version={config.loader_version}"
                        )
                    if not config.minecraft_version or config.minecraft_version == "unknown":
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
            self.servers[config.name] = config
            self.write_servers_config()
            self._create_eula_file(server_path)
            config.eula_accepted = True
            self._create_server_structure(Path(config.path), config.loader_type)
            properties_file = server_path / "server.properties"
            if properties is None:
                properties = self.get_default_server_properties()
            properties = dict(properties)
            properties["motd"] = f"Minecraft 伺服器 - {config.name}"
            ServerPropertiesHelper.save_properties(properties_file, properties)
            config.properties = properties
            self.create_launch_script(config)
            return True
        except Exception as e:
            try:
                server_path = (self.servers_root / config.name).resolve()
            except Exception:
                server_path = None
            record_and_mark(
                e, marker_path=server_path, reason="建立伺服器失敗", details={"server": getattr(config, "name", None)}
            )
            return False

    def _create_eula_file(self, server_path: Path) -> None:
        """建立並同意 EULA 檔案"""
        eula_content = "eula=true"
        PathUtils.write_text_file(server_path / "eula.txt", eula_content)

    def _create_server_structure(self, path: Path, loader_type: str) -> None:
        """建立伺服器檔案結構"""
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
        """建立伺服器啟動腳本。

        Args:
            config: 伺服器設定與啟動參數來源。
        """
        server_path = Path(config.path)
        max_memory = config.memory_max_mb
        min_memory = config.memory_min_mb
        if min_memory:
            memory_display = (
                f"最小 {MemoryUtils.format_memory_mb(min_memory)}, 最大 {MemoryUtils.format_memory_mb(max_memory)}"
            )
        else:
            memory_display = f"Java自行取用-{MemoryUtils.format_memory_mb(max_memory)}"
        java_cmd_list = ServerCommands.build_java_command(config, return_list=True)
        logger.debug(f"Java 命令列表: {java_cmd_list}")
        java_exe = java_cmd_list[0]
        if " " in java_exe and (not (java_exe.startswith('"') and java_exe.endswith('"'))):
            java_exe = f'"{java_exe}"'
        uses_args_file = len(java_cmd_list) >= 2 and java_cmd_list[1].startswith("@")
        if uses_args_file:
            args_spec = java_cmd_list[1]
            args_rel_path = args_spec[1:]
            args_path = server_path / args_rel_path
            if args_path.exists():
                java_command_str = f"{java_exe} {args_spec} nogui"
            else:
                logger.warning(f"參數檔案不存在: {args_path}")
                java_command_str = f"{java_exe} {args_spec} nogui"
        else:
            cmd_parts = [java_exe]
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
        try:
            if start_script_path.exists():
                existing_content = PathUtils.read_text_file(start_script_path, encoding="gbk", errors="ignore")
                if existing_content == bat_content:
                    logger.debug("啟動腳本內容未變更，跳過寫入")
                    return
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(
                    e,
                    marker_path=start_script_path,
                    reason="compare_start_script_failed",
                    details={"server": getattr(config, "name", None)},
                )
            logger.debug(f"比較啟動腳本時發生錯誤 (將強制覆寫): {e}")
        PathUtils.write_text_file(start_script_path, bat_content, encoding="gbk", errors="replace")

    def update_server_properties(self, server_name: str, properties: dict[str, str]) -> bool:
        """更新 server.properties，只覆蓋有變動的欄位，其餘欄位保留原值。

        Args:
            server_name: 目標伺服器名稱。
            properties: 要合併寫入的屬性。

        Returns:
            成功時回傳 True，失敗時回傳 False。
        """
        try:
            config = self.servers.get(server_name)
            if not config:
                logger.error(f"update_server_properties 找不到伺服器設定: {server_name}")
                return False
            server_path = getattr(config, "path", None) or getattr(config, "server_path", None)
            if not server_path:
                logger.error(f"找不到伺服器路徑，無法儲存 server.properties。config={config}")
                return False
            properties_path = Path(server_path) / "server.properties"
            original = ServerPropertiesHelper.load_properties(properties_path)
            merged = {**original, **properties}
            changed_keys = sorted((key for key, value in merged.items() if original.get(key) != value))
            logger.info(
                f"準備儲存 server.properties: server={server_name}, path={properties_path}, changed_keys={len(changed_keys)}"
            )
            if not ServerPropertiesHelper.save_properties(properties_path, merged):
                logger.error(f"儲存 server.properties 失敗: server={server_name}, path={properties_path}")
                return False
            try:
                mtime = properties_path.stat().st_mtime
            except OSError:
                mtime = time.time()
            self._properties_cache[server_name] = (mtime, dict(merged))
            config.properties = merged
            if not self.write_servers_config():
                logger.error(f"儲存 servers_config.json 失敗: server={server_name}")
                return False
            logger.info(
                f"server.properties 與 servers_config.json 已同步保存: server={server_name}, changed_keys={changed_keys}"
            )
            return True
        except Exception as e:
            try:
                properties_path = Path(getattr(self.servers.get(server_name), "path", "")) / "server.properties"
            except Exception:
                properties_path = None
            record_and_mark(
                e,
                marker_path=properties_path,
                reason="update_server_properties 儲存失敗",
                details={"server": server_name},
            )
            return False

    def start_server(self, server_name: str, parent=None) -> bool:
        """啟動伺服器。

        Args:
            server_name: 目標伺服器名稱。
            parent: 用於 UI 錯誤提示的父視窗。

        Returns:
            成功時回傳 True，失敗時回傳 False。
        """
        try:
            if server_name not in self.servers:
                UIUtils.show_error("伺服器未找到", f"找不到伺服器: {server_name}", parent=parent)
                return False
            config = self.servers[server_name]
            server_path = Path(config.path)
            if not server_path.exists():
                UIUtils.show_error("伺服器路徑不存在", f"伺服器路徑不存在: {server_path}", parent=parent)
                return False
            self.create_launch_script(config)
            script_path = ServerDetectionUtils.find_startup_script(server_path)
            if script_path:
                logger.info(f"找到啟動腳本: {script_path}")
            else:
                UIUtils.show_error(
                    "啟動腳本未找到", "找不到啟動腳本 (start_server.bat, run.bat, start.bat, server.bat)", parent=parent
                )
                return False
            logger.debug(f"準備啟動伺服器: {server_name}")
            logger.debug(f"腳本路徑: {script_path}")
            logger.debug(f"工作目錄: {server_path}")
            try:
                abs_script_path = script_path.resolve()
                abs_server_path = server_path.resolve()
                cmd = [str(abs_script_path)]
                logger.debug(f"執行命令: {cmd}")
                logger.debug(f"工作目錄: {abs_server_path}")
                process = SubprocessUtils.popen_checked(
                    cmd,
                    cwd=str(abs_server_path),
                    stdin=SubprocessUtils.PIPE,
                    stdout=SubprocessUtils.PIPE,
                    stderr=SubprocessUtils.STDOUT,
                    text=True,
                    encoding="utf-8",
                    bufsize=0,
                    universal_newlines=True,
                    creationflags=SubprocessUtils.CREATE_NO_WINDOW,
                )
                process.create_time = time.time()
                if self._wait_for_process_exit(process, self.STARTUP_CHECK_DELAY):
                    poll_result = process.poll()
                    logger.error(f"進程立即結束，返回碼: {poll_result}")
                    try:
                        stdout, _ = process.communicate(timeout=1)
                        if stdout:
                            logger.error(f"程式輸出: {stdout}")
                    except Exception as e:
                        logger.exception(f"無法讀取程式輸出: {e}")
                    script_content = PathUtils.read_text_file(script_path)
                    if script_content is not None:
                        logger.debug(f"啟動腳本內容:\n{script_content}")
                    else:
                        logger.error(f"無法讀取啟動腳本: {script_path}")
                    UIUtils.show_error(
                        "啟動失敗", f"伺服器進程立即結束，返回碼: {poll_result}\n請檢查日誌了解詳細資訊", parent=parent
                    )
                    return False
                instance = ServerInstance(id=server_name, name=server_name, path=server_path, config=config)
                instance.attach_process(process)
                instance.attach_output_buffer(self.OUTPUT_QUEUE_MAX_SIZE)
                self.running_servers[server_name] = instance

                def _process_waiter(proc, name):
                    try:
                        proc.wait()
                        logger.info(f"伺服器 {name} 已停止 (Exit code: {proc.returncode})")
                    except Exception as e:
                        logger.error(f"等待伺服器 {name}結束時發生錯誤: {e}")

                threading.Thread(
                    target=_process_waiter, args=(process, server_name), daemon=True, name=f"Waiter-{server_name}"
                ).start()

                def _output_reader(proc, running_instance, name):
                    try:
                        while True:
                            line = None
                            try:
                                line = proc.stdout.readline()
                            except UnicodeDecodeError:
                                try:
                                    raw = proc.stdout.buffer.readline()
                                    line = raw.decode("utf-8", errors="ignore")
                                except Exception as e2:
                                    logger.exception(f"{name} 嚴重編碼錯誤: {e2}", "output_reader", e2)
                                    continue
                            if not line:
                                break
                            running_instance.append_output_line(line)
                            if proc.poll() is not None:
                                break
                    except Exception as e:
                        get_logger().bind(component="output_reader").exception(f"{name} 讀取錯誤: {e}")

                threading.Thread(target=_output_reader, args=(process, instance, server_name), daemon=True).start()
                logger.info(f"伺服器 {server_name} 啟動成功，PID: {process.pid}")
                return True
            except FileNotFoundError as e:
                logger.exception(f"檔案路徑錯誤: {e}")
                return False
        except Exception as e:
            try:
                server_path = Path(getattr(self.servers.get(server_name), "path", ""))
            except Exception:
                server_path = None
            record_and_mark(e, marker_path=server_path, reason="啟動伺服器失敗", details={"server": server_name})
            UIUtils.show_error("啟動失敗", f"無法啟動伺服器 {server_name}。錯誤: {e}", parent=parent)
            return False

    def delete_server(self, server_name: str) -> bool:
        """刪除伺服器。

        Args:
            server_name: 要刪除的伺服器名稱。

        Returns:
            成功時回傳 True，失敗時回傳 False。
        """
        try:
            if server_name not in self.servers:
                return False
            config = self.servers[server_name]
            server_path = Path(config.path)
            PathUtils.delete_path(server_path)
            del self.servers[server_name]
            self.write_servers_config()
            return True
        except Exception as e:
            try:
                server_path = Path(getattr(self.servers.get(server_name), "path", ""))
            except Exception:
                server_path = None
            record_and_mark(e, marker_path=server_path, reason="刪除伺服器失敗", details={"server": server_name})
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
                        self.servers[name] = ServerConfig(**config_data)
                else:
                    logger.warning("伺服器配置文件為空或無法解析")
            except Exception as e:
                with contextlib.suppress(Exception):
                    record_and_mark(e, marker_path=self.config_file, reason="load_servers_config_failed")

    def write_servers_config(self) -> bool:
        """實際執行保存伺服器配置到 servers_config.json。

        Returns:
            成功寫入時回傳 True，失敗時回傳 False。
        """
        with self._config_lock:
            try:
                data: dict[str, dict[str, Any]] = {}
                for name, config in self.servers.items():
                    if is_dataclass(config) and not isinstance(config, type):
                        data[name] = asdict(config)
                    elif isinstance(config, dict):
                        data[name] = config
                    else:
                        logger.error(f"保存伺服器配置失敗: 無法序列化類型 {type(config).__name__} ({name})")
                        return False
                logger.debug(f"寫入 servers_config.json: path={self.config_file}, server_count={len(data)}")
                if not atomic_write_json(self.config_file, data):
                    logger.error("保存伺服器配置失敗: 無法寫入文件")
                    return False
                logger.info("伺服器配置已保存到 servers_config.json")
                return True
            except Exception as e:
                with contextlib.suppress(Exception):
                    record_and_mark(e, marker_path=self.config_file, reason="write_servers_config_failed")
                logger.exception(f"保存伺服器配置失敗: {e}")
                return False

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
        """檢查伺服器是否已存在。

        Args:
            name: 伺服器名稱。

        Returns:
            若伺服器存在則回傳 True。
        """
        return name in self.servers

    def add_server(self, config: ServerConfig) -> bool:
        """添加伺服器配置（用於匯入）。

        Args:
            config: 要加入的伺服器設定。

        Returns:
            成功寫入設定時回傳 True，失敗時回傳 False。
        """
        try:
            self.servers[config.name] = config
            self.write_servers_config()
            return True
        except Exception as e:
            logger.exception(f"添加伺服器失敗: {e}")
            return False

    def load_server_properties(self, server_name: str) -> dict[str, str]:
        """載入伺服器的 server.properties 檔案內容（附帶快取機制）。

        Args:
            server_name: 伺服器名稱。

        Returns:
            讀取到的屬性字典；找不到或失敗時回傳空字典。
        """
        try:
            if server_name not in self.servers:
                return {}
            config = self.servers[server_name]
            server_path = Path(config.path)
            properties_file = server_path / "server.properties"
            if not properties_file.exists():
                return {}
            try:
                mtime = properties_file.stat().st_mtime
            except OSError:
                return {}
            cached_mtime, cached_props = self._properties_cache.get(server_name, (0, None))
            if cached_props is not None and mtime == cached_mtime:
                return cached_props
            properties = ServerPropertiesHelper.load_properties(properties_file)
            self._properties_cache[server_name] = (mtime, properties)
            logger.debug(
                f"重新載入 server.properties: server={server_name}, path={properties_file}, property_count={len(properties)}"
            )
            existing_properties = dict(getattr(config, "properties", {}) or {})
            if existing_properties != properties:
                config.properties = dict(properties)
                self.write_servers_config()
            return properties
        except Exception as e:
            logger.exception(f"讀取 server.properties 失敗: {e}")
            return {}

    def invalidate_server_properties_cache(self, server_name: str | None = None) -> None:
        """清除 server.properties 快取。

        傳入 server_name 時僅清除單一伺服器，否則清除全部。

        Args:
            server_name: 要清除快取的伺服器名稱；為 None 時清除全部。
        """
        if server_name is None:
            self._properties_cache.clear()
            return
        self._properties_cache.pop(server_name, None)

    def is_server_running(self, server_name: str) -> bool:
        """檢查伺服器是否正在運行"""
        return self._get_running_instance(server_name) is not None

    def stop_server(self, server_name: str) -> bool:
        """停止伺服器。

        Args:
            server_name: 目標伺服器名稱。

        Returns:
            成功停止或已處於停止狀態時回傳 True。
        """
        try:
            instance = self.running_servers.get(server_name)
            if instance is None:
                logger.info(f"伺服器 {server_name} 未在運行")
                return False
            process = instance.get_process()
            if process is None:
                logger.info(f"伺服器 {server_name} 已停止")
                return True
            try:
                is_running = process.poll() is None
            except Exception:
                is_running = False
            if not is_running:
                logger.info(f"伺服器 {server_name} 已停止")
                return True
            try:
                if process.stdin:
                    process.stdin.write("stop\n")
                    process.stdin.flush()
                process.wait(timeout=5)
            except (SubprocessUtils.TimeoutExpired, OSError, BrokenPipeError):
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except SubprocessUtils.TimeoutExpired:
                    SystemUtils.kill_process_tree(process.pid)
                    with contextlib.suppress(SubprocessUtils.TimeoutExpired):
                        process.wait(timeout=1)
            logger.info(f"伺服器 {server_name} 已停止")
            return True
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(e, reason="stop_server_failed", details={"server": server_name})
            logger.exception(f"停止伺服器失敗: {e}")
            return False
        finally:
            self._cleanup_running_server_state(server_name)

    def get_server_info(self, server_name: str) -> dict | None:
        """獲取伺服器資訊，包括運行狀態和資源使用，補齊 UI 需要的欄位。

        Args:
            server_name: 目標伺服器名稱。

        Returns:
            伺服器資訊字典；找不到伺服器時回傳 None。
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
                "players": 0,
                "max_players": 0,
                "version": "N/A",
            }
            try:
                properties = self.load_server_properties(server_name)
                if properties:
                    max_players = properties.get("max-players") or properties.get("max_players")
                    if max_players:
                        try:
                            info["max_players"] = int(max_players)
                        except (ValueError, TypeError) as exc:
                            logger.debug(f"解析 max_players 失敗: {exc}")
                            info["max_players"] = 0
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
            instance = self._get_running_instance(server_name)
            if instance is not None:
                process = instance.get_process()
                if process is None:
                    return info
                info["pid"] = process.pid
                if not SystemUtils.is_process_running(process.pid):
                    info["is_running"] = False
                    self._cleanup_running_server_state(server_name)
                    return info
                info["is_running"] = True
                java_pid = getattr(process, "java_pid", None)
                if not java_pid:
                    java_pid = SystemUtils.find_java_process(process.pid)
                    if java_pid:
                        process.java_pid = java_pid
                target_pid = java_pid if java_pid else process.pid
                if java_pid:
                    info["pid"] = java_pid
                mem_bytes = SystemUtils.get_process_memory_usage(target_pid)
                info["memory"] = mem_bytes / (1024 * 1024)
                info["memory_mb"] = info["memory"]
                try:
                    if hasattr(process, "create_time"):
                        create_time = process.create_time
                        uptime_seconds = int(time.time() - create_time)
                        hours = uptime_seconds // 3600
                        minutes = uptime_seconds % 3600 // 60
                        seconds = uptime_seconds % 60
                        info["uptime"] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                except Exception as e:
                    logger.exception(f"計算伺服器運行時間失敗: {e}")
            return info
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(e, reason="get_server_info_failed", details={"server": server_name})
            logger.exception(f"獲取伺服器資訊失敗: {e}")
            return None

    def send_command(self, server_name: str, command: str) -> bool:
        """向運行中的伺服器發送命令。

        Args:
            server_name: 目標伺服器名稱。
            command: 要送出的控制台指令。

        Returns:
            成功送出時回傳 True，失敗時回傳 False。
        """
        try:
            instance = self._get_running_instance(server_name)
            if instance is None:
                logger.info(f"伺服器 {server_name} 未在運行")
                return False
            process = instance.get_process()
            if process is None:
                logger.info(f"伺服器 {server_name} 程式已結束")
                return False
            if process.stdin:
                process.stdin.write(command + "\n")
                process.stdin.flush()
                logger.debug(f"已向伺服器 {server_name} 發送命令: {command}")
                if command.lower() == "stop":

                    def check_stop():
                        if (
                            self._wait_for_process_exit(process, self.STOP_TIMEOUT_SECONDS, self.STOP_CHECK_INTERVAL)
                            and server_name in self.running_servers
                        ):
                            self._cleanup_running_server_state(server_name)
                            logger.info(f"伺服器 {server_name} 已確認停止")

                    threading.Thread(target=check_stop, daemon=True).start()
                return True
            logger.error(f"無法向伺服器 {server_name} 發送命令：stdin 不可用", "ServerManager")
            return False
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(e, reason="send_command_failed", details={"server": server_name, "command": command})
            logger.exception(f"發送命令失敗: {e}")
            return False

    def read_server_output(self, server_name: str, _timeout: float = 0.1) -> list[str]:
        """讀取伺服器輸出。

        Args:
            server_name: 目標伺服器名稱。
            _timeout: 保留的相容參數，現階段未使用。

        Returns:
            目前緩衝中的輸出行清單。
        """
        try:
            instance = self._get_running_instance(server_name)
            if instance is None:
                return []
            process = instance.get_process()
            if process is None or process.poll() is not None:
                self._cleanup_running_server_state(server_name)
                return []
            return instance.consume_output_lines()
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(e, reason="read_server_output_failed", details={"server": server_name})
            logger.exception(f"讀取伺服器輸出失敗: {e}")
            return []

    def get_server_log_file(self, server_name: str) -> Path | None:
        """獲取伺服器日誌檔案路徑。

        Args:
            server_name: 目標伺服器名稱。

        Returns:
            找到的日誌檔案路徑；找不到時回傳 None。
        """
        try:
            if server_name not in self.servers:
                return None
            server_config = self.servers[server_name]
            server_path = Path(server_config.path)
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
            with contextlib.suppress(Exception):
                record_and_mark(e, reason="get_server_log_file_failed", details={"server": server_name})
            logger.exception(f"獲取伺服器日誌檔案失敗: {e}")
            return None
