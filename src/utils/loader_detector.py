#!/usr/bin/env python3
"""
載入器偵測器模組
提供統一的 Fabric、Forge 和 Vanilla 載入器類型偵測與版本解析功能
Loader Detector Module
Provides unified detection and version parsing for Fabric, Forge, and Vanilla loaders
"""

import re
from pathlib import Path

from . import get_logger
from .loader_constants import (
    FABRIC_JAR_NAMES,
    FABRIC_MIN_MC_VERSION,
    FABRIC_PATTERNS,
    FORGE_LIBRARY_PATH,
    FORGE_PATTERNS,
    LOADER_TYPE_FABRIC,
    LOADER_TYPE_FORGE,
    LOADER_TYPE_UNKNOWN,
    LOADER_TYPE_VANILLA,
    MC_VERSION_PATTERN,
    VANILLA_JAR_NAMES,
)

logger = get_logger().bind(component="LoaderDetector")


class LoaderDetector:
    """
    載入器偵測器類別，提供統一的載入器類型偵測與版本解析功能
    Loader detector class providing unified loader type detection and version parsing
    """

    @staticmethod
    def detect_loader_type(
        server_path: Path,
        jar_files: list[str] | None = None,
    ) -> str:
        """
        偵測伺服器載入器類型
        Detect server loader type

        Args:
            server_path: 伺服器路徑
            jar_files: 可選的 JAR 檔案列表，若未提供則自動掃描

        Returns:
            載入器類型：fabric, forge, vanilla, 或 unknown
        """
        try:
            # 取得 JAR 檔案列表
            if jar_files is None:
                jar_files = [f.name for f in server_path.glob("*.jar")]
            jar_names_lower = [f.lower() for f in jar_files]

            # 檢查 Fabric
            if LoaderDetector._has_fabric_files(server_path):
                logger.debug("偵測到 Fabric 載入器（透過特定檔案）")
                return LOADER_TYPE_FABRIC

            # 檢查 Forge（透過函式庫目錄）
            if LoaderDetector._has_forge_libraries(server_path):
                logger.debug("偵測到 Forge 載入器（透過函式庫目錄）")
                return LOADER_TYPE_FORGE

            # 檢查 Forge（透過 JAR 檔名）
            if any(FORGE_PATTERNS["filename"] in name for name in jar_names_lower):
                logger.debug("偵測到 Forge 載入器（透過 JAR 檔名）")
                return LOADER_TYPE_FORGE

            # 檢查 Vanilla
            if any(name in jar_names_lower for name in VANILLA_JAR_NAMES):
                logger.debug("偵測到 Vanilla 伺服器")
                return LOADER_TYPE_VANILLA

            logger.debug("無法判斷載入器類型")
            return LOADER_TYPE_UNKNOWN

        except Exception as e:
            logger.exception(f"偵測載入器類型時發生錯誤: {e}")
            return LOADER_TYPE_UNKNOWN

    @staticmethod
    def detect_loader_from_filename(filename: str) -> str:
        """
        從檔名偵測載入器類型（用於模組檔案等）
        Detect loader type from filename (for mod files etc.)

        Args:
            filename: 檔案名稱

        Returns:
            載入器類型：Fabric, Forge, 或 未知
        """
        filename_lower = filename.lower()

        if re.search(FORGE_PATTERNS["filename"], filename_lower, re.IGNORECASE):
            return "Forge"
        if re.search(FABRIC_PATTERNS["filename"], filename_lower, re.IGNORECASE):
            return "Fabric"
        return "未知"

    @staticmethod
    def parse_mc_version(version_str: str) -> list[int]:
        """
        解析 Minecraft 版本字串為數字列表
        Parse Minecraft version string to list of integers

        例如：
        - "1.14.4" -> [1, 14, 4]
        - "1.20" -> [1, 20]
        - "1.21.4" -> [1, 21, 4]

        Args:
            version_str: 版本字串

        Returns:
            包含主要、次要、修補版本號的整數列表，解析失敗返回空列表
        """
        try:
            matches = re.findall(r"\d+", version_str)
            return [int(x) for x in matches] if matches else []
        except Exception as e:
            logger.exception(f"解析 MC 版本時發生錯誤: {e}")
            return []

    @staticmethod
    def is_fabric_compatible_version(mc_version: str) -> bool:
        """
        檢查 MC 版本是否與 Fabric 相容
        Check if MC version is compatible with Fabric

        Fabric 最早支援 1.14 版本
        Fabric supports versions 1.14 and above

        Args:
            mc_version: 要檢查的 MC 版本字串

        Returns:
            如果相容則為 True，否則為 False
        """
        try:
            version_parts = LoaderDetector.parse_mc_version(mc_version)
            if not version_parts:
                return False

            major = version_parts[0]
            minor = version_parts[1] if len(version_parts) > 1 else 0

            # Fabric supports 1.14+
            return bool(major > 1 or (major == 1 and minor >= FABRIC_MIN_MC_VERSION[1]))
        except Exception as e:
            logger.exception(f"檢查 Fabric 相容性時發生錯誤: {e}")
            return False

    @staticmethod
    def extract_version_from_forge_path(path_str: str) -> tuple[str, str] | None:
        """
        從 Forge 路徑中提取 MC 版本和 Forge 版本
        Extract MC version and Forge version from Forge path

        例如：
        - "libraries/net/minecraftforge/forge/1.20.1-47.3.0" -> ("1.20.1", "47.3.0")
        - "forge-1.21.4-54.0.0.jar" -> ("1.21.4", "54.0.0")

        Args:
            path_str: 包含版本資訊的路徑或檔名

        Returns:
            (mc_version, forge_version) 或 None（如果無法解析）
        """
        try:
            match = re.search(FORGE_PATTERNS["version_path"], path_str)
            if match:
                mc_ver = match.group(1)
                forge_ver = match.group(2)
                logger.debug(f"從路徑提取版本: MC={mc_ver}, Forge={forge_ver}")
                return mc_ver, forge_ver
            return None
        except Exception as e:
            logger.exception(f"從 Forge 路徑提取版本時發生錯誤: {e}")
            return None

    @staticmethod
    def extract_loader_version_from_jar_name(jar_name: str, loader_type: str) -> str | None:
        """
        從 JAR 檔名提取載入器版本
        Extract loader version from JAR filename

        Args:
            jar_name: JAR 檔案名稱
            loader_type: 載入器類型（fabric 或 forge）

        Returns:
            載入器版本字串，或 None（如果無法提取）
        """
        try:
            loader_type_lower = loader_type.lower()

            if loader_type_lower == LOADER_TYPE_FORGE:
                # 使用 Forge JAR 檔名模式
                match = re.match(FORGE_PATTERNS["jar_filename"], jar_name)
                if match:
                    forge_ver = match.group(2)
                    logger.debug(f"從 Forge JAR 提取版本: {forge_ver}")
                    return forge_ver

            # 其他載入器類型暫不支援從檔名提取
            return None

        except Exception as e:
            logger.exception(f"從 JAR 檔名提取載入器版本時發生錯誤: {e}")
            return None

    @staticmethod
    def standardize_loader_type(loader_type: str, loader_version: str = "") -> str:
        """
        標準化載入器類型：將輸入轉為小寫並進行基本推斷
        Standardize loader type: convert to lowercase and make basic inferences

        Args:
            loader_type: 載入器類型
            loader_version: 載入器版本（用於推斷）

        Returns:
            標準化後的載入器類型
        """
        lt_low = loader_type.lower()
        if lt_low != LOADER_TYPE_UNKNOWN:
            return lt_low

        # fallback 推斷
        if loader_version and loader_version.replace(".", "").isdigit():
            return LOADER_TYPE_FORGE
        if loader_version and FABRIC_PATTERNS["filename"] in loader_version.lower():
            return LOADER_TYPE_FABRIC
        return LOADER_TYPE_VANILLA

    # ====== 私有輔助方法 ======

    @staticmethod
    def _has_fabric_files(server_path: Path) -> bool:
        """
        檢查是否存在 Fabric 特定檔案
        Check if Fabric-specific files exist
        """
        return any((server_path / jar_name).exists() for jar_name in FABRIC_JAR_NAMES)

    @staticmethod
    def _has_forge_libraries(server_path: Path) -> bool:
        """
        檢查是否存在 Forge 函式庫目錄
        Check if Forge library directory exists
        """
        return (server_path / FORGE_LIBRARY_PATH).is_dir()
