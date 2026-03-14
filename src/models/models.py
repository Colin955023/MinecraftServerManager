"""資料模型定義
定義應用程式中使用的核心資料結構與配置類別
Data Model Definitions
Defines core data structures and configuration classes used in the application
"""

from dataclasses import dataclass


@dataclass
class LoaderVersion:
    """模組載入器版本資訊的資料結構，支援 Forge 和 Fabric 載入器"""

    version: str
    build: str | None = None
    url: str | None = None
    stable: bool | None = None
    mc_version: str | None = None


@dataclass
class ServerConfig:
    """伺服器完整配置資料類別，包含所有伺服器設定和屬性"""

    name: str
    minecraft_version: str
    loader_type: str
    loader_version: str
    memory_max_mb: int
    memory_min_mb: int | None = None
    path: str = ""
    eula_accepted: bool = False
    properties: dict[str, str] | None = None
    backup_path: str | None = None

    @property
    def memory_mb(self) -> int:
        """取得伺服器最大記憶體配置，提供向後相容性"""
        return self.memory_max_mb

    @memory_mb.setter
    def memory_mb(self, value: int):
        """設定伺服器最大記憶體配置，提供向後相容性"""
        self.memory_max_mb = value
