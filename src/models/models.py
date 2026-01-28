"""資料模型定義
定義應用程式中使用的核心資料結構與配置類別
Data Model Definitions
Defines core data structures and configuration classes used in the application
"""

from dataclasses import dataclass


# 模組載入器版本資訊資料類別
@dataclass
class LoaderVersion:
    """模組載入器版本資訊的資料結構，支援 Forge 和 Fabric 載入器
    Data structure for mod loader version information supporting Forge and Fabric loaders

    Attributes:
        version (str): 載入器版本號
        build (str | None): 構建編號
        url (str | None): 下載連結
        stable (bool | None): 是否為穩定版本
        mc_version (str | None): 對應的 Minecraft 版本

    """

    version: str
    build: str | None = None
    url: str | None = None
    stable: bool | None = None
    mc_version: str | None = None


# ====== 伺服器配置模型 ======
# 伺服器完整配置資料類別
@dataclass
class ServerConfig:
    """伺服器完整配置資料類別，包含所有伺服器設定和屬性
    Complete server configuration data class containing all server settings and properties

    Attributes:
        name (str): 伺服器顯示名稱
        minecraft_version (str): Minecraft 版本號
        loader_type (str): 模組載入器類型 (vanilla/fabric/forge)
        loader_version (str): 模組載入器版本號
        memory_max_mb (int): 最大記憶體配置 (MB)
        memory_min_mb (int | None): 最小記憶體配置 (MB)
        path (str): 伺服器檔案存放路徑
        eula_accepted (bool): 是否接受 Minecraft EULA 協議
        properties (Dict[str, str] | None): server.properties 設定字典
        backup_path (str | None): 備份檔案存放路徑

    """

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
        """取得伺服器最大記憶體配置，提供向後相容性
        Get server maximum memory configuration for backward compatibility

        Args:
            None

        Returns:
            int: 最大記憶體配置 (MB)

        """
        return self.memory_max_mb

    @memory_mb.setter
    def memory_mb(self, value: int):
        """設定伺服器最大記憶體配置，提供向後相容性
        Set server maximum memory configuration for backward compatibility

        Args:
            value (int): 要設定的記憶體大小 (MB)

        Returns:
            None

        """
        self.memory_max_mb = value
