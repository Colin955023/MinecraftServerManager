"""資料模型定義
定義應用程式中使用的核心資料結構與配置類別
Data Model Definitions
Defines core data structures and configuration classes used in the application
"""

from dataclasses import dataclass


# 模組載入器版本資訊資料類別
@dataclass
class LoaderVersion:
    """模組載入器版本資訊的資料結構，支援 Forge 和 Fabric 載入器"""

    version: str
    build: str | None = None
    url: str | None = None
    stable: bool | None = None
    mc_version: str | None = None


# ====== 伺服器配置模型 ======
# 伺服器完整配置資料類別
@dataclass
class ServerConfig:
    """伺服器完整配置資料類別，包含所有伺服器設定和屬性"""

    name: str  # 伺服器名稱
    minecraft_version: str  # Minecraft 版本
    loader_type: str  # 模組載入器類型: vanilla, fabric, forge
    loader_version: str  # 模組載入器版本
    memory_max_mb: int  # 最大記憶體 (MB) - 必填
    memory_min_mb: int | None = None  # 最小記憶體 (MB) - 選填
    path: str = ""  # 伺服器路徑
    eula_accepted: bool = False  # 是否接受 EULA
    properties: dict[str, str] | None = None  # 伺服器屬性設定
    backup_path: str | None = None  # 備份路徑

    @property
    def memory_mb(self) -> int:
        """取得伺服器最大記憶體配置，提供向後相容性"""
        return self.memory_max_mb

    @memory_mb.setter
    def memory_mb(self, value: int):
        """設定伺服器最大記憶體配置，提供向後相容性"""
        self.memory_max_mb = value
