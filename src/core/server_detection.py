#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
伺服器檢測工具模組
提供 Minecraft 伺服器的自動檢測、驗證和設定解析功能
Server Detection Utilities Module
Provides automatic detection, validation, and configuration parsing functions for Minecraft servers
"""
# ====== 標準函式庫 ======
from pathlib import Path
from typing import List, Optional
import json
import os
import re
import traceback
# ====== 專案內部模組 ======
from ..models import ServerConfig
from ..utils.log_utils import LogUtils
from ..utils.ui_utils import UIUtils
from ..utils.memory_utils import MemoryUtils

class ServerDetectionUtils:
    """
    伺服器檢測工具類別，提供各種伺服器相關的檢測和驗證功能
    Server detection utility class providing various server-related detection and validation functions
    """
    # ====== 檔案與設定檢測 ======
    # 取得缺少的伺服器檔案清單
    @staticmethod
    def get_missing_server_files(folder_path: Path) -> list:
        """
        檢查伺服器資料夾中缺少的關鍵檔案清單
        Check list of missing critical files in server folder

        Args:
            folder_path (Path): 伺服器資料夾路徑

        Returns:
            list: 缺少的檔案名稱清單
        """
        missing = []
        # 主程式 JAR
        if not (folder_path / "server.jar").exists() and not any(
            (folder_path / f).exists()
            for f in ["minecraft_server.jar", "fabric-server-launch.jar", "fabric-server-launcher.jar"]
        ):
            missing.append("server.jar 或同等主程式 JAR")
        # EULA
        if not (folder_path / "eula.txt").exists():
            missing.append("eula.txt")
        # server.properties
        if not (folder_path / "server.properties").exists():
            missing.append("server.properties")
        return missing

    # 檢測 EULA 接受狀態
    @staticmethod
    def detect_eula_acceptance(server_path: Path) -> bool:
        """
        檢測 eula.txt 檔案中是否已設定 eula=true
        Detect if eula=true is set in eula.txt file

        Args:
            server_path (Path): 伺服器根目錄路徑

        Returns:
            bool: 已接受 EULA 返回 True，否則返回 False
        """
        eula_file = server_path / "eula.txt"
        if not eula_file.exists():
            return False

        try:
            with open(eula_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # 查找 eula=true 設定（忽略大小寫和空白）
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    if key.strip().lower() == "eula":
                        return value.strip().lower() == "true"
            return False
        except Exception as e:
            LogUtils.error(f"讀取 eula.txt 失敗: {e}", "detect_eula_acceptance")
            return False

    # ====== 記憶體設定管理 ======
    # 更新 Forge JVM 參數檔案
    @staticmethod
    def update_forge_user_jvm_args(server_path: Path, config: ServerConfig) -> None:
        """
        更新新版 Forge 的 user_jvm_args.txt 檔案，設定記憶體參數
        Update user_jvm_args.txt file for newer Forge versions with memory parameters

        Args:
            server_path (Path): 伺服器根目錄路徑
            config (ServerConfig): 伺服器配置物件

        Returns:
            None
        """
        user_jvm_args_path = server_path / "user_jvm_args.txt"
        lines = []
        if config.memory_min_mb:
            lines.append(f"-Xms{config.memory_min_mb}M\n")
        if config.memory_max_mb:
            lines.append(f"-Xmx{config.memory_max_mb}M\n")
        try:
            with open(user_jvm_args_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception as e:
            LogUtils.error(f"寫入失敗: {e}", "update_forge_user_jvm_args")
            UIUtils.show_error("寫入失敗", f"無法更新 {user_jvm_args_path} 檔案。請檢查權限或磁碟空間。錯誤: {e}")

    # 從多個來源檢測記憶體設定
    @staticmethod
    def detect_memory_from_sources(server_path: Path, config: ServerConfig) -> None:
        """
        檢測記憶體大小
        detect memory size

        Args:
            server_path (Path): 伺服器根目錄路徑
            config (ServerConfig): 伺服器配置物件
        """
        max_mem = None
        min_mem = None
        # === 1. 解析 JVM 參數檔 (user_jvm_args.txt / jvm.args) ===
        for args_file in ["user_jvm_args.txt", "jvm.args"]:
            fpath = server_path / args_file
            if fpath.exists():
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        # 使用統一的記憶體解析函數
                        parsed_max = MemoryUtils.parse_memory_setting(content, "Xmx")
                        if parsed_max:
                            max_mem = parsed_max
                        parsed_min = MemoryUtils.parse_memory_setting(content, "Xms")
                        if parsed_min:
                            min_mem = parsed_min
                except Exception:
                    pass
        # === 2. 優先解析常見啟動腳本 (start_server.bat / start.bat) ===
        for bat_name in ["start_server.bat", "start.bat"]:
            fpath = server_path / bat_name
            if fpath.exists():
                try:
                    # 讀取並處理啟動腳本
                    script_content = []
                    script_modified = False

                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            # 移除 pause 命令
                            line_stripped = line.strip().lower()
                            if line_stripped in ["pause", "@pause", "pause.", "@pause."]:
                                script_modified = True
                                LogUtils.info(f"發現並移除 pause 命令: {line.strip()}", "ServerDetection")
                                continue  # 跳過這行

                            # 檢查 Java 命令行並處理 nogui
                            if "java" in line and ("-Xmx" in line or "-Xms" in line or ".jar" in line):
                                # 確保有 nogui 參數
                                if "nogui" not in line.lower():
                                    # 在行尾添加 nogui (移除換行符再加回)
                                    line = line.rstrip("\r\n") + " nogui\n"
                                    script_modified = True
                                    LogUtils.info("在 Java 命令行添加 nogui 參數", "ServerDetection")

                            script_content.append(line)

                            # 解析記憶體設定
                            if "java" in line and ("-Xmx" in line or "-Xms" in line):
                                if not max_mem:
                                    parsed_max = MemoryUtils.parse_memory_setting(line, "Xmx")
                                    if parsed_max:
                                        max_mem = parsed_max
                                if not min_mem:
                                    parsed_min = MemoryUtils.parse_memory_setting(line, "Xms")
                                    if parsed_min:
                                        min_mem = parsed_min

                    # 如果移除了 pause 命令，重寫腳本
                    if script_modified:
                        try:
                            with open(fpath, "w", encoding="utf-8") as f:
                                f.writelines(script_content)
                            LogUtils.info(f"已從 {fpath} 移除 pause 命令", "ServerDetection")
                        except Exception as e:
                            LogUtils.warning(f"無法重寫腳本 {fpath}: {e}", "ServerDetection")

                except Exception:
                    pass
        # === 3. 備援：掃描所有 .bat 與 .sh 腳本，同時移除 pause ===
        memory_detection_incomplete = max_mem is None or min_mem is None
        if memory_detection_incomplete:
            for pattern in ["*.bat", "*.sh"]:
                for script in server_path.glob(pattern):
                    try:
                        script_content = []
                        script_modified = False

                        with open(script, "r", encoding="utf-8", errors="ignore") as f:
                            for line in f:
                                # 移除 pause 命令
                                line_stripped = line.strip().lower()
                                if line_stripped in ["pause", "@pause", "pause.", "@pause."]:
                                    script_modified = True
                                    LogUtils.info(f"發現並移除 pause 命令: {line.strip()}", "ServerDetection")
                                    continue  # 跳過這行

                                # 檢查 Java 命令行並處理 nogui
                                if "java" in line and ("-Xmx" in line or "-Xms" in line or ".jar" in line):
                                    # 確保有 nogui 參數
                                    if "nogui" not in line.lower():
                                        # 在行尾添加 nogui (移除換行符再加回)
                                        line = line.rstrip("\r\n") + " nogui\n"
                                        script_modified = True
                                        LogUtils.info("在 Java 命令行添加 nogui 參數", "ServerDetection")

                                script_content.append(line)

                                if "java" in line and ("-Xmx" in line or "-Xms" in line):
                                    if not max_mem:
                                        parsed_max = MemoryUtils.parse_memory_setting(line, "Xmx")
                                        if parsed_max:
                                            max_mem = parsed_max
                                    if not min_mem:
                                        parsed_min = MemoryUtils.parse_memory_setting(line, "Xms")
                                        if parsed_min:
                                            min_mem = parsed_min
                                    break  # 第一筆匹配後跳出

                        # 如果移除了 pause 命令，重寫腳本
                        if script_modified:
                            try:
                                with open(script, "w", encoding="utf-8") as f:
                                    f.writelines(script_content)
                                LogUtils.info(f"已從 {script} 移除 pause 命令", "ServerDetection")
                            except Exception as e:
                                LogUtils.warning(f"無法重寫腳本 {script}: {e}", "ServerDetection")

                    except Exception:
                        pass
        # 寫入 config
        if max_mem:
            config.memory_max_mb = max_mem
            config.memory_min_mb = min_mem  # 可能為 None
        elif min_mem:
            # 只有最小值沒有最大值的情況（比較少見）
            config.memory_max_mb = min_mem
            config.memory_min_mb = min_mem
        # 若是 Forge，則自動覆蓋 user_jvm_args.txt
        if hasattr(config, "loader_type") and str(getattr(config, "loader_type", "")).lower() == "forge":
            ServerDetectionUtils.update_forge_user_jvm_args(server_path, config)

    @staticmethod
    def detect_server_type(server_path: Path, config: "ServerConfig", print_result: bool = True) -> None:
        """
        檢測伺服器類型和版本 - 統一的偵測邏輯
        Detect server type and version - Unified detection logic.

        Args:
            server_path (Path): 伺服器路徑
            config (ServerConfig): 伺服器配置
        """
        try:
            jar_files = list(server_path.glob("*.jar"))
            jar_names = [f.name.lower() for f in jar_files]

            # 判斷 loader_type
            fabric_files = ["fabric-server-launch.jar", "fabric-server-launcher.jar"]
            if any((server_path / f).exists() for f in fabric_files):
                config.loader_type = "fabric"
            elif (server_path / "libraries/net/minecraftforge/forge").is_dir():
                config.loader_type = "forge"
            elif any("forge" in name for name in jar_names):
                config.loader_type = "forge"
            elif any(name in ("server.jar", "minecraft_server.jar") for name in jar_names):
                config.loader_type = "vanilla"
            else:
                config.loader_type = "unknown"

            # 呼叫進一步偵測
            ServerDetectionUtils.detect_loader_and_version_from_sources(server_path, config, config.loader_type)

            # 偵測記憶體設定
            ServerDetectionUtils.detect_memory_from_sources(server_path, config)

            # 偵測 EULA 狀態
            config.eula_accepted = ServerDetectionUtils.detect_eula_acceptance(server_path)

            # 顯示結果（若有啟用）
            if print_result:
                LogUtils.info(f"偵測結果 - 路徑: {server_path.name}", "ServerDetection")
                LogUtils.info(f"  載入器: {config.loader_type}", "ServerDetection")
                LogUtils.info(f"  MC版本: {config.minecraft_version}", "ServerDetection")
                LogUtils.info(f"  EULA狀態: {'已接受' if config.eula_accepted else '未接受'}", "ServerDetection")
                # 記憶體顯示邏輯
                if hasattr(config, "memory_max_mb") and config.memory_max_mb:
                    if hasattr(config, "memory_min_mb") and config.memory_min_mb:
                        LogUtils.info(
                            f"  記憶體: 最小 {config.memory_min_mb}MB, 最大 {config.memory_max_mb}MB", "ServerDetection"
                        )
                    else:
                        LogUtils.info(f"  記憶體: 0-{config.memory_max_mb}MB", "ServerDetection")
                else:
                    LogUtils.info("  記憶體: 未設定", "ServerDetection")

        except Exception as e:
            LogUtils.error(f"檢測伺服器類型失敗: {e}\n{traceback.format_exc()}", "ServerDetection")

    @staticmethod
    def is_valid_server_folder(folder_path: Path) -> bool:
        """
        檢查是否為有效的 Minecraft 伺服器資料夾
        Check if the folder is a valid Minecraft server directory.

        Args:
            folder_path (Path): 伺服器資料夾路徑

        Returns:
            bool: 是否為有效的伺服器資料夾
        """
        if not folder_path.is_dir():
            return False

        # 檢查伺服器 jar 檔案
        server_jars = ["server.jar", "minecraft_server.jar", "fabric-server-launch.jar", "fabric-server-launcher.jar"]
        for jar_name in server_jars:
            if (folder_path / jar_name).exists():
                return True

        # 檢查 Forge/其他 jar 檔案
        for file in folder_path.glob("*.jar"):
            jar_name = file.name.lower()
            if any(pattern in jar_name for pattern in ["forge", "server", "minecraft"]):
                return True

        # 檢查特徵檔案
        server_indicators = ["server.properties", "eula.txt"]
        for indicator in server_indicators:
            if (folder_path / indicator).exists():
                return True

        return False

    @staticmethod
    def detect_loader_and_version_from_sources(server_path: Path, config, loader: str) -> None:
        """
        從多種來源偵測 Fabric/Forge 載入器與 Minecraft 版本：
        - logs()
        - libraries/net/minecraftforge/forge
        - JAR 檔名
        - version.json

        Args:
            server_path (Path): 伺服器路徑
            config: 伺服器配置物件
            loader (str): 載入器類型
        """
        # ---------- 共用小工具 ----------
        def is_unknown(value: Optional[str]) -> bool:
            return value in (None, "", "unknown", "Unknown", "無")

        def set_if_unknown(attr_name: str, value: str):
            if is_unknown(getattr(config, attr_name)):
                setattr(config, attr_name, value)

        def first_match(content: str, patterns: List[str]) -> Optional[str]:
            for pat in patterns:
                m = re.search(pat, content, re.IGNORECASE)
                if m:
                    return m.group(1)
            return None

        # ---------- 偵測來源 ----------
        def detect_from_logs():
            log_files = ["latest.log", "server.log", "debug.log"]
            loader_patterns = {
                "fabric": [
                    r"Fabric Loader (\d+\.\d+\.\d+)",
                    r"FabricLoader/(\d+\.\d+\.\d+)",
                    r"fabric-loader (\d+\.\d+\.\d+)",
                    r"Loading Fabric (\d+\.\d+\.\d+)",
                ],
                "forge": [
                    r"fml.forgeVersion, (\d+\.\d+\.\d+)",
                    r"Forge Mod Loader version (\d+\.\d+\.\d+)",  # 1.12.2 以下
                    r"MinecraftForge v(\d+\.\d+\.\d+)",  # 1.12.2 以下
                    r"Forge (\d+\.\d+\.\d+)",
                    r"forge-(\d+\.\d+\.\d+)",
                ],
            }
            mc_patterns = [
                r"Starting minecraft server version (\d+\.\d+(?:\.\d+)?)",
                r"Minecraft (\d+\.\d+(?:\.\d+)?)",
                r"Server version: (\d+\.\d+(?:\.\d+)?)",
            ]

            for name in log_files:
                fp = server_path / "logs" / name
                if not fp.exists():
                    continue
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    content = "".join(f.readlines()[:1000])

                if loader in loader_patterns:
                    v = first_match(content, loader_patterns[loader])
                    if v:
                        set_if_unknown("loader_version", v)

                mc_ver = first_match(content, mc_patterns)
                if mc_ver:
                    set_if_unknown("minecraft_version", mc_ver)

                if not is_unknown(config.loader_version) and not is_unknown(config.minecraft_version):
                    break  # 已取得兩版本即可提前結束

        def detect_from_forge_lib():
            forge_dir = server_path / "libraries" / "net" / "minecraftforge" / "forge"
            if not forge_dir.is_dir():
                return
            subdirs = [d for d in forge_dir.iterdir() if d.is_dir()]
            if not subdirs:
                return

            folder = subdirs[0].name
            m = re.match(r"(\d+\.\d+(?:\.\d+)?)-(\d+\.\d+(?:\.\d+)?)", folder)
            if m:
                mc, forge_ver = m.groups()
                set_if_unknown("minecraft_version", mc)
                set_if_unknown("loader_version", forge_ver)

            # 再從同層 JAR 補值
            for jar in subdirs[0].glob("*.jar"):
                m2 = re.match(r"forge-(\d+\.\d+(?:\.\d+)?)-(\d+\.\d+(?:\.\d+)?)-.*\.jar", jar.name)
                if m2:
                    mc2, _ = m2.groups()
                    set_if_unknown("minecraft_version", mc2)
                    break

        def detect_from_jars():
            for jar in server_path.glob("*.jar"):
                name_lower = jar.name.lower()

                # loader_type
                if is_unknown(config.loader_type):
                    if "fabric" in name_lower:
                        config.loader_type = "fabric"
                    elif "forge" in name_lower:
                        config.loader_type = "forge"
                    else:
                        config.loader_type = "vanilla"

                # Forge 版本(1.12.2 以下)
                m = re.search(r"forge-(\d+\.\d+(?:\.\d+)?)-(\d+\.\d+(?:\.\d+)?).*\.jar", jar.name)
                if m:
                    mc, forge_ver = m.groups()
                    set_if_unknown("minecraft_version", mc)
                    set_if_unknown("loader_version", forge_ver)

                if (
                    not is_unknown(config.loader_type)
                    and not is_unknown(config.loader_version)
                    and not is_unknown(config.minecraft_version)
                ):
                    break

        def detect_from_version_json():
            fp = server_path / "version.json"
            if not fp.exists():
                return
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "id" in data:
                    set_if_unknown("minecraft_version", data["id"])
                if "forgeVersion" in data:
                    set_if_unknown("loader_version", data["forgeVersion"])
            except Exception:
                pass

        # －－－－－－－－－－ 主流程 －－－－－－－－－－

        # 1. logs
        detect_from_logs()

        # Fabric 若仍無版本，統一為 'unknown'
        if loader == "fabric" and is_unknown(config.loader_version):
            config.loader_version = "unknown"

        # 2. Forge libraries
        if loader == "forge":
            detect_from_forge_lib()

        # 3. JAR 與 version.json
        detect_from_jars()
        detect_from_version_json()

        # 4. 最終保底 loader_type
        if is_unknown(config.loader_type):
            detect_from_jars()
            if is_unknown(config.loader_type):
                config.loader_type = "vanilla"

    @staticmethod
    def detect_main_jar_file(server_path: Path, loader_type: str) -> str:
        """
        偵測主伺服器 JAR 檔案名稱，根據載入器類型（Forge/Fabric/Vanilla）返回適當的 JAR 名稱
        Detects the main server JAR file name based on the loader type (Forge/Fabric/Vanilla) and returns the appropriate JAR name.

        Args:
            server_path (Path): 伺服器路徑
            loader_type (str): 載入器類型

        Returns:
            str: 主伺服器 JAR 檔案名稱
        """
        LogUtils.debug(f"server_path={server_path}", "detect_main_jar_file")
        LogUtils.debug(f"loader_type={loader_type}", "detect_main_jar_file")

        loader_type_lc = loader_type.lower() if loader_type else ""
        jar_files = [f for f in os.listdir(server_path) if f.endswith(".jar")]
        jar_files_lower = [f.lower() for f in jar_files]

        # ---------- Forge ----------
        if loader_type_lc == "forge":
            # 1. 新版 Forge：libraries/.../forge/**/win_args.txt
            forge_lib_dir = server_path / "libraries/net/minecraftforge/forge"
            LogUtils.debug(f"forge_lib_dir={forge_lib_dir}", "detect_main_jar_file")
            if forge_lib_dir.is_dir():
                arg_files = list(forge_lib_dir.rglob("win_args.txt"))
                LogUtils.debug(f"rglob args.txt found: {[str(f) for f in arg_files]}", "detect_main_jar_file")
                if arg_files:
                    arg_files.sort(key=lambda p: len(p.parts), reverse=True)
                    result = f"@{arg_files[0].relative_to(server_path)}"
                    LogUtils.debug(f"return (forge new args.txt): {result}", "detect_main_jar_file")
                    return result

            # 2. 舊版 Forge：尋找 jar 名中含 forge-<mc>-<forge> 結構
            mc_ver = None
            forge_ver = None
            for fname in jar_files:
                m = re.match(r"forge-(\d+\.\d+(?:\.\d+)?)-(\d+\.\d+(?:\.\d+)?).*\\.jar", fname)
                if m:
                    mc_ver, forge_ver = m.group(1), m.group(2)
                    break

            if mc_ver and forge_ver:
                for fname, lower in zip(jar_files, jar_files_lower):
                    if "forge" in lower and mc_ver in lower and forge_ver in lower and "installer" not in lower:
                        LogUtils.debug(f"return (forge old): {fname}", "detect_main_jar_file")
                        return fname

            # 3. fallback: 任一含 forge 且非 installer 的 jar
            for fname, lower in zip(jar_files, jar_files_lower):
                if "forge" in lower and "installer" not in lower:
                    LogUtils.debug(f"return (forge fallback): {fname}", "detect_main_jar_file")
                    return fname

            # 4. fallback: server.jar 存在
            if (server_path / "server.jar").exists():
                LogUtils.debug("return (server.jar fallback): server.jar", "detect_main_jar_file")
                return "server.jar"

            # 5. fallback: 任一 jar
            if jar_files:
                LogUtils.debug(f"return (any jar fallback): {jar_files[0]}", "detect_main_jar_file")
                return jar_files[0]

            LogUtils.debug("return (final fallback): server.jar", "detect_main_jar_file")
            return "server.jar"

        # ---------- Fabric ----------
        elif loader_type_lc == "fabric":
            for candidate in ["fabric-server-launch.jar", "fabric-server-launcher.jar", "server.jar"]:
                if (server_path / candidate).exists():
                    LogUtils.debug(f"return (fabric): {candidate}", "detect_main_jar_file")
                    return candidate
            LogUtils.debug("return (fabric fallback): server.jar", "detect_main_jar_file")
            return "server.jar"

        # ---------- Vanilla / Unknown ----------
        else:
            for candidate in ["server.jar", "minecraft_server.jar"]:
                if (server_path / candidate).exists():
                    LogUtils.debug(f"return (vanilla): {candidate}", "detect_main_jar_file")
                    return candidate
            LogUtils.debug("return (vanilla fallback): server.jar", "detect_main_jar_file")
            return "server.jar"
