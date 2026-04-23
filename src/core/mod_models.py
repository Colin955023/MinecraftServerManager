"""模組管理共享模型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

MODRINTH_HASH_ALGORITHM = "sha512"
MODRINTH_SEARCH_URL = "https://api.modrinth.com/v2/search"


class ModStatus(Enum):
    """模組狀態。"""

    ENABLED = "enabled"
    DISABLED = "disabled"


class ModPlatform(Enum):
    """模組來源平台。"""

    MODRINTH = "modrinth"
    LOCAL = "local"


@dataclass
class LocalModInfo:
    """本地模組資訊。"""

    id: str
    name: str
    filename: str
    version: str
    minecraft_version: str
    loader_type: str
    description: str = ""
    author: str = ""
    platform: ModPlatform = ModPlatform.LOCAL
    platform_id: str = ""
    platform_slug: str = ""
    status: ModStatus = ModStatus.ENABLED
    file_path: str = ""
    download_url: str = ""
    homepage_url: str = ""
    dependencies: list[str] | None = None
    file_size: int = 0
    current_hash: str = ""
    hash_algorithm: str = ""
    resolution_source: str = ""
    resolved_at_epoch_ms: str = ""
    provider_lifecycle_state: str = ""
    stale_revalidation_failures: int = 0
    next_retry_not_before_epoch_ms: str = ""

    def __post_init__(self) -> None:
        if self.dependencies is None:
            self.dependencies = []


@dataclass(slots=True)
class ModFileOperationResult:
    """描述遠端下載/覆蓋流程的最終狀態。"""

    status: str
    final_path: Path | None = None
    rollback_performed: bool = False
    message: str = ""

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    @property
    def cancelled(self) -> bool:
        return self.status == "cancelled"


@dataclass(slots=True)
class LocalModMutationResult:
    """描述本地模組檔案異動結果，供 UI 層決定呈現方式。"""

    status: str
    title: str = ""
    message: str = ""
    final_path: Path | None = None
    affected_count: int = 0
    missing_ids: tuple[str, ...] = ()

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    @property
    def partial(self) -> bool:
        return self.status == "partial"

    @property
    def failed(self) -> bool:
        return self.status == "failed"
