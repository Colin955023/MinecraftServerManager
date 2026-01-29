#!/usr/bin/env python3
"""
載入器常數模組
提供 Fabric、Forge 和 Minecraft 版本相關的常數和正規表示式模式
Loader Constants Module
Provides constants and regex patterns for Fabric, Forge, and Minecraft version detection
"""

# ====== Minecraft 版本模式 ======
# Minecraft Version Patterns
MC_VERSION_PATTERN = r"(\d+\.\d+(?:\.\d+)?)"
"""
匹配 Minecraft 版本號，例如：1.20.1, 1.19, 1.21.4
Matches Minecraft version numbers like: 1.20.1, 1.19, 1.21.4
"""

# ====== Fabric 相關常數 ======
# Fabric Constants
FABRIC_JAR_NAMES = [
    "fabric-server-launch.jar",
    "fabric-server-launcher.jar",
]
"""
Fabric 伺服器啟動 JAR 檔案名稱列表
List of Fabric server launcher JAR file names
"""

FABRIC_PATTERNS = {
    "filename": r"fabric",
    "loader_version": [
        r"Fabric Loader (\d+\.\d+\.\d+)",
        r"fabric-loader (\d+\.\d+\.\d+)",
    ],
}
"""
Fabric 相關的正規表示式模式字典
Dictionary of Fabric-related regex patterns
- filename: 用於檔名中的 Fabric 識別
- loader_version: 用於從日誌或檔案中提取 Fabric Loader 版本
"""

# ====== Forge 相關常數 ======
# Forge Constants
FORGE_LIBRARY_PATH = "libraries/net/minecraftforge/forge"
"""
Forge 函式庫的標準路徑
Standard path for Forge libraries
"""

FORGE_ARGS_FILES = [
    "win_args.txt",
    "unix_args.txt",
    "user_jvm_args.txt",
]
"""
Forge 參數檔案列表（按優先順序）
List of Forge argument files (in priority order)
"""

FORGE_PATTERNS = {
    "filename": r"forge",
    "version_path": r"(\d+\.\d+(?:\.\d+)?)-(\d+\.\d+(?:\.\d+)?)",
    "jar_filename": r"forge-(\d+\.\d+(?:\.\d+)?)-(\d+\.\d+(?:\.\d+)?).*\.jar",
    "loader_version": [
        r"fml\.forgeVersion[,\s]+(\d+\.\d+\.\d+)",
        r"Forge\s+(\d+\.\d+\.\d+)",
    ],
}
"""
Forge 相關的正規表示式模式字典
Dictionary of Forge-related regex patterns
- filename: 用於檔名中的 Forge 識別
- version_path: 用於從路徑中提取 MC 版本和 Forge 版本
- jar_filename: 用於從 JAR 檔名中提取版本資訊
- loader_version: 用於從日誌或檔案中提取 Forge 版本
"""

# ====== Vanilla 相關常數 ======
# Vanilla Constants
VANILLA_JAR_NAMES = [
    "server.jar",
    "minecraft_server.jar",
]
"""
原版 Minecraft 伺服器 JAR 檔案名稱列表
List of vanilla Minecraft server JAR file names
"""

# ====== 載入器類型 ======
# Loader Types
LOADER_TYPE_VANILLA = "vanilla"
LOADER_TYPE_FABRIC = "fabric"
LOADER_TYPE_FORGE = "forge"
LOADER_TYPE_UNKNOWN = "unknown"

VALID_LOADER_TYPES = [
    LOADER_TYPE_VANILLA,
    LOADER_TYPE_FABRIC,
    LOADER_TYPE_FORGE,
]
"""
有效的載入器類型列表
List of valid loader types
"""

# ====== Fabric 最低支援版本 ======
# Fabric Minimum Supported Version
FABRIC_MIN_MC_VERSION = (1, 14)
"""
Fabric 最早支援的 Minecraft 版本（1.14）
Minimum Minecraft version supported by Fabric (1.14)
"""
