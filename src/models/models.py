"""資料模型定義
定義應用程式中使用的核心資料結構與配置類別
Data Model Definitions
Defines core data structures and configuration classes used in the application
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OnlineModVersion:
    """Modrinth 上單一模組版本資訊。"""

    version_id: str
    version_number: str
    display_name: str
    game_versions: list[str] = field(default_factory=list)
    loaders: list[str] = field(default_factory=list)
    version_type: str = ""
    date_published: str = ""
    changelog: str = ""
    provider: str = "modrinth"
    files: list[dict[str, Any]] = field(default_factory=list)
    dependencies: list[dict[str, Any]] = field(default_factory=list)

    @property
    def primary_file(self) -> dict[str, Any] | None:
        if not self.files:
            return None
        for file_info in self.files:
            if isinstance(file_info, dict) and file_info.get("primary"):
                return file_info
        for file_info in self.files:
            if isinstance(file_info, dict):
                filename = str(file_info.get("filename", "") or "")
                if filename.lower().endswith(".jar"):
                    return file_info
        for file_info in self.files:
            if isinstance(file_info, dict):
                return file_info
        return None


@dataclass
class ModrinthVersionLookupResult:
    """以雜湊查詢 Modrinth 版本後的結果。"""

    file_hash: str
    algorithm: str
    project_id: str
    version: OnlineModVersion


@dataclass(slots=True)
class ResolvedDependencyReference:
    """解析後的依賴資訊，支援 project_id 與 version_id 兩種來源。"""

    project_id: str = ""
    project_name: str = ""
    version_id: str = ""
    version_name: str = ""
    file_name: str = ""
    version: OnlineModVersion | None = None
    resolution_source: str = "project_id"
    resolution_confidence: str = "direct"

    @property
    def label(self) -> str:
        if self.project_name:
            base = self.project_name
        elif self.project_id:
            base = f"未知模組（project id: {self.project_id}）"
        elif self.file_name:
            base = self.file_name
        elif self.version_id:
            base = f"未知模組（version id: {self.version_id}）"
        else:
            base = "未知依賴"
        if self.version_name:
            return f"{base}（需求版本：{self.version_name}）"
        return base

    @property
    def compare_project_id(self) -> str:
        return str(self.project_id or "").strip().lower()


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
