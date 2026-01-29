#!/usr/bin/env python3
"""
伺服器 JAR 定位器模組
提供統一的伺服器主 JAR 檔案偵測與定位功能
Server JAR Locator Module
Provides unified detection and location of main server JAR files
"""

import re
from pathlib import Path

from . import get_logger
from .loader_constants import (
    FABRIC_JAR_NAMES,
    FORGE_ARGS_FILES,
    FORGE_PATTERNS,
    LOADER_TYPE_FABRIC,
    LOADER_TYPE_FORGE,
    VANILLA_JAR_NAMES,
)

logger = get_logger().bind(component="ServerJarLocator")


class ServerJarLocator:
    """
    伺服器 JAR 定位器類別，提供統一的主 JAR 檔案偵測功能
    Server JAR locator class providing unified main JAR file detection
    """

    @staticmethod
    def find_main_jar(
        server_path: Path,
        loader_type: str,
        server_config=None,
    ) -> str:
        """
        根據載入器類型尋找主伺服器 JAR 檔案
        Find main server JAR file based on loader type

        Args:
            server_path: 伺服器路徑
            loader_type: 載入器類型（fabric, forge, vanilla）
            server_config: 伺服器配置物件（可選，用於優化查找）

        Returns:
            主 JAR 檔案名稱或參數檔路徑（Forge 可能返回 @win_args.txt 格式）
        """
        loader_type_lower = loader_type.lower()

        if loader_type_lower == LOADER_TYPE_FORGE:
            return ServerJarLocator._find_forge_jar(server_path, server_config)
        elif loader_type_lower == LOADER_TYPE_FABRIC:
            return ServerJarLocator._find_fabric_jar(server_path)
        else:
            return ServerJarLocator._find_vanilla_jar(server_path)

    @staticmethod
    def _find_forge_jar(server_path: Path, server_config=None) -> str:
        """
        尋找 Forge 主 JAR 檔案或參數檔
        Find Forge main JAR file or argument file

        處理多種情況：
        1. Modern 1.21.1+ 使用 -jar 格式
        2. BootstrapLauncher 格式
        3. 舊版 Forge JAR 格式

        Args:
            server_path: 伺服器路徑
            server_config: 伺服器配置物件

        Returns:
            主 JAR 檔案名稱或參數檔路徑（例如 @win_args.txt）
        """
        logger.debug(f"開始尋找 Forge JAR: server_path={server_path}")

        # 嘗試從參數檔尋找
        args_path = ServerJarLocator._find_forge_args_file(server_path, server_config)

        if args_path:
            args_info = ServerJarLocator._parse_forge_args_file(args_path)

            # 情況 1: Modern 1.21.1+ 使用 -jar 格式
            jar_val = args_info.get("jar")
            if jar_val and isinstance(jar_val, str):
                logger.info(f"從參數檔找到 -jar 格式: {jar_val}")
                return jar_val

            # 情況 2+3: 從參數檔中尋找 forge library JAR
            libs_val = args_info.get("forge_libraries")
            if libs_val and isinstance(libs_val, list) and libs_val:
                # 優先選擇名稱中包含 "server" 的 JAR
                candidates = [lib for lib in libs_val if "server" in lib.lower()]
                if not candidates:
                    candidates = sorted(libs_val, key=len, reverse=True)
                if candidates:
                    logger.info(f"從參數檔解析出 Forge JAR: {candidates[0]}")
                    return candidates[0]

            # 情況 4: BootstrapLauncher 模式
            if args_info.get("bootstraplauncher"):
                result = f"@{args_path.relative_to(server_path)}"
                logger.info(f"BootstrapLauncher 模式，使用參數檔啟動: {result}")
                return result

            # Fallback: 返回參數檔本身
            result = f"@{args_path.relative_to(server_path)}"
            logger.info(f"使用參數檔作為主要執行檔: {result}")
            return result

        # 沒有參數檔，嘗試從 JAR 檔案尋找
        jar_files = [f.name for f in server_path.glob("*.jar")]

        # 嘗試提取版本資訊進行精確匹配
        mc_ver = None
        forge_ver = None
        for fname in jar_files:
            match = re.match(FORGE_PATTERNS["jar_filename"], fname)
            if match:
                mc_ver, forge_ver = match.group(1), match.group(2)
                logger.debug(f"從 JAR 檔名提取版本: MC={mc_ver}, Forge={forge_ver}")
                break

        # 版本匹配
        if mc_ver and forge_ver:
            for fname in jar_files:
                fname_lower = fname.lower()
                if (
                    "forge" in fname_lower
                    and mc_ver in fname_lower
                    and forge_ver in fname_lower
                    and "installer" not in fname_lower
                ):
                    logger.info(f"偵測到 Forge JAR (版本匹配): {fname}")
                    return fname

        # 模糊匹配（包含 forge 但不是 installer）
        for fname in jar_files:
            fname_lower = fname.lower()
            if "forge" in fname_lower and "installer" not in fname_lower:
                logger.info(f"偵測到 Forge JAR (模糊匹配): {fname}")
                return fname

        # 尋找任何非標準 JAR（排除 installer 和標準檔名）
        for fname in jar_files:
            fname_lower = fname.lower()
            if fname_lower not in ["server.jar", "minecraft_server.jar"] and "installer" not in fname_lower:
                logger.info(f"偵測到自定義主程式 JAR: {fname}")
                return fname

        # Fallback 到標準檔名
        return ServerJarLocator._find_vanilla_jar(server_path)

    @staticmethod
    def _find_fabric_jar(server_path: Path) -> str:
        """
        尋找 Fabric 主 JAR 檔案
        Find Fabric main JAR file

        Args:
            server_path: 伺服器路徑

        Returns:
            主 JAR 檔案名稱
        """
        # 檢查 Fabric 特定的啟動 JAR
        for jar_name in FABRIC_JAR_NAMES:
            if (server_path / jar_name).exists():
                logger.info(f"偵測到 Fabric 啟動 JAR: {jar_name}")
                return jar_name

        # Fallback 到 server.jar
        logger.info("未發現 Fabric 啟動 JAR，回退: server.jar")
        return "server.jar"

    @staticmethod
    def _find_vanilla_jar(server_path: Path) -> str:
        """
        尋找 Vanilla 主 JAR 檔案
        Find Vanilla main JAR file

        Args:
            server_path: 伺服器路徑

        Returns:
            主 JAR 檔案名稱
        """
        for jar_name in VANILLA_JAR_NAMES:
            if (server_path / jar_name).exists():
                logger.info(f"偵測到原版 JAR: {jar_name}")
                return jar_name

        logger.info("未發現原版 JAR，回退: server.jar")
        return "server.jar"

    @staticmethod
    def _find_forge_args_file(server_path: Path, server_config=None) -> Path | None:
        """
        尋找 Forge 參數檔
        Find Forge argument file

        Args:
            server_path: 伺服器路徑
            server_config: 伺服器配置物件（可選）

        Returns:
            參數檔路徑，若未找到則返回 None
        """
        # 如果配置中有指定參數檔，優先使用
        if server_config and hasattr(server_config, "forge_args_file"):
            forge_args = getattr(server_config, "forge_args_file", None)
            if forge_args:
                args_path = server_path / forge_args
                if args_path.exists():
                    logger.debug(f"從配置找到參數檔: {forge_args}")
                    return args_path

        # 按優先順序搜尋標準參數檔
        for args_file in FORGE_ARGS_FILES:
            args_path = server_path / args_file
            if args_path.exists():
                logger.debug(f"找到參數檔: {args_file}")
                return args_path

        logger.debug("未找到 Forge 參數檔")
        return None

    @staticmethod
    def _parse_forge_args_file(args_path: Path) -> dict:
        """
        解析 Forge 參數檔
        Parse Forge argument file

        支援多種格式：
        - @reference 格式（-jar xxx.jar）
        - BootstrapLauncher 格式
        - 直接列出函式庫路徑

        Args:
            args_path: 參數檔路徑

        Returns:
            包含解析結果的字典：
            - jar: -jar 參數值（如果存在）
            - forge_libraries: Forge 函式庫列表
            - bootstraplauncher: 是否為 BootstrapLauncher 模式
        """
        result = {
            "jar": None,
            "forge_libraries": [],
            "bootstraplauncher": False,
        }

        try:
            with args_path.open("r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # 檢查 -jar 參數
            jar_match = re.search(r"-jar\s+([^\s]+\.jar)", content)
            if jar_match:
                result["jar"] = jar_match.group(1)
                logger.debug(f"解析到 -jar 參數: {result['jar']}")

            # 檢查 BootstrapLauncher
            if "BootstrapLauncher" in content:
                result["bootstraplauncher"] = True
                logger.debug("偵測到 BootstrapLauncher")

            # 解析函式庫路徑
            # 尋找包含 forge 的函式庫路徑
            forge_lib_pattern = r"libraries[/\\]net[/\\]minecraftforge[/\\]forge[/\\][^\s]+"
            for match in re.finditer(forge_lib_pattern, content):
                lib_path = match.group(0)
                result["forge_libraries"].append(lib_path)
                logger.debug(f"解析到 Forge 函式庫: {lib_path}")

        except Exception as e:
            logger.exception(f"解析參數檔時發生錯誤: {e}")

        return result
