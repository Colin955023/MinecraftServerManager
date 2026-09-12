"""伺服器設定、建立、檢查與匯入模型"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """核心操作提供給 UI 的結構化進度事件"""

    phase: str
    message: str
    completed_units: int = 0
    total_units: int | None = None
    overall_percent: float | None = None

    @property
    def phase_percent(self) -> float | None:
        if self.total_units is None or self.total_units <= 0:
            return None
        return min(100.0, max(0.0, self.completed_units / self.total_units * 100.0))


@dataclass
class ServerConfig:
    """伺服器完整設定資料"""

    name: str
    minecraft_version: str
    loader_type: str
    loader_version: str
    memory_max_mb: int
    memory_min_mb: int | None = None
    path: str = ""
    jvm_args: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ServerOperationResult:
    """描述伺服器操作結果，供 UI 層決定呈現方式"""

    success: bool
    title: str = ""
    message: str = ""
    server_name: str = ""

    @property
    def failed(self) -> bool:
        return not self.success


CreationStatus = Literal["completed", "cancelled", "failed"]


@dataclass(frozen=True, slots=True)
class ServerCreationWarning:
    """建立計畫中需要使用者注意或確認的警告"""

    message: str


@dataclass(frozen=True, slots=True)
class ServerCreationPlan:
    """完成驗證後可交由交易執行器提交的不可變建立計畫"""

    transaction_id: str
    name: str
    minecraft_version: str
    loader_type: str
    loader_version: str
    memory_max_mb: int
    memory_min_mb: int | None
    jvm_args: tuple[str, ...]
    properties: tuple[tuple[str, str], ...]
    final_path: Path
    staging_path: Path
    user_java_path: str | None
    installer_artifact: Any | None
    warnings: tuple[ServerCreationWarning, ...]
    registry_revision: str = ""
    confirmation: Any | None = None

    def build_config(self, path: Path) -> ServerConfig:
        """
        建立指定交易路徑使用的伺服器設定

        Args:
            path: 交易完成後的伺服器目錄

        Returns:
            可供持久化的伺服器設定
        """
        return ServerConfig(
            name=self.name,
            minecraft_version=self.minecraft_version,
            loader_type=self.loader_type,
            loader_version=self.loader_version,
            memory_max_mb=self.memory_max_mb,
            memory_min_mb=self.memory_min_mb,
            path=str(path),
            jvm_args=list(self.jvm_args),
        )


@dataclass(frozen=True, slots=True)
class ServerCreationResult:
    """伺服器建立交易的最終狀態與診斷資訊"""

    status: CreationStatus
    message: str
    config: ServerConfig | None = None
    diagnostic_id: str = ""
    cleanup_complete: bool = True

    @property
    def completed(self) -> bool:
        return self.status == "completed"


ImportMode = Literal["import", "redetect"]
ImportSourceKind = Literal["archive", "directory", "in_place"]
ImportStatus = Literal["completed", "skipped", "cancelled", "failed"]
ConflictType = Literal["none", "disk", "config", "both"]
InspectionPurpose = Literal["import", "redetect", "status", "launch"]
EulaState = Literal["missing", "accepted", "rejected", "unreadable"]
LaunchTargetKind = Literal["script", "jar", "args", "none"]


@dataclass(frozen=True, slots=True)
class ServerInspectionIntent:
    """完整檢查的用途與既有身分期待值"""

    purpose: InspectionPurpose
    expected_loader_type: str = ""
    expected_minecraft_version: str = ""
    expected_loader_version: str = ""


@dataclass(frozen=True, slots=True)
class ServerLaunchTarget:
    """由完整檢查選出的唯一啟動目標"""

    kind: LaunchTargetKind
    value: str = ""
    command: str = ""
    candidates: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ServerInspection:
    """單次磁碟 revision 的不可變伺服器內容快照"""

    path: Path
    revision: str
    is_candidate: bool
    error: str
    loader_type: str = "unknown"
    minecraft_version: str = "unknown"
    loader_version: str = "unknown"
    evidence: tuple[tuple[str, str], ...] = ()
    conflicts: tuple[str, ...] = ()
    launch_target: ServerLaunchTarget = field(default_factory=lambda: ServerLaunchTarget("none"))
    memory_max_mb: int = 2048
    memory_min_mb: int | None = None
    eula_state: EulaState = "missing"
    missing_files: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    status_ready: bool = False
    launchable: bool = False


@dataclass(frozen=True, slots=True)
class ImportManifestEntry:
    """匯入來源內單一一般檔案的不可變快照"""

    relative_path: str
    size: int
    mtime_ns: int
    sha256: str = ""


@dataclass(frozen=True, slots=True)
class ImportManifest:
    """匯入檢查與執行共用的來源清單"""

    entries: tuple[ImportManifestEntry, ...]
    revision: str
    total_bytes: int


@dataclass(frozen=True, slots=True)
class ServerImportInspection:
    """不會修改來源的匯入候選快照"""

    transaction_id: str
    mode: ImportMode
    source_kind: ImportSourceKind
    source_path: Path
    name: str
    final_path: Path
    server: ServerInspection
    warnings: tuple[str, ...]
    committable: bool
    conflict_type: ConflictType = "none"
    manifest: ImportManifest | None = None

    def build_config(self, path: Path, previous: ServerConfig | None = None) -> ServerConfig:
        """
        建立提交邊界使用的可變持久化模型

        Args:
            path: 匯入後的伺服器目錄
            previous: 可沿用 JVM 參數的既有設定

        Returns:
            可供持久化的伺服器設定
        """
        return ServerConfig(
            name=self.name,
            path=str(path),
            minecraft_version=self.server.minecraft_version,
            loader_type=self.server.loader_type,
            loader_version=self.server.loader_version,
            memory_max_mb=self.server.memory_max_mb,
            memory_min_mb=self.server.memory_min_mb,
            jvm_args=list(previous.jvm_args) if previous else [],
        )


@dataclass(frozen=True, slots=True)
class ServerImportResult:
    """單一候選的最終交易結果"""

    status: ImportStatus
    message: str
    name: str
    config: ServerConfig | None = None
    warnings: tuple[str, ...] = ()
    evidence: tuple[tuple[str, str], ...] = ()
    diagnostic_id: str = ""
    cleanup_complete: bool = True

    @property
    def completed(self) -> bool:
        return self.status == "completed"


@dataclass(frozen=True, slots=True)
class ServerImportBatchResult:
    """批次執行的逐項結果與彙總計數"""

    items: tuple[ServerImportResult, ...]

    @property
    def completed_count(self) -> int:
        return sum(item.completed for item in self.items)

    @property
    def skipped_count(self) -> int:
        return sum(item.status == "skipped" for item in self.items)

    @property
    def failed_count(self) -> int:
        return sum(item.status == "failed" for item in self.items)


@dataclass(frozen=True, slots=True)
class ServerDiscoveryIssue:
    """單一候選目錄的探索失敗資訊"""

    path: Path
    message: str


@dataclass(frozen=True, slots=True)
class ServerDiscoveryReport:
    """伺服器探索成功項目、已管理項目與個別失敗資訊"""

    candidates: tuple[ServerImportInspection, ...] = ()
    issues: tuple[ServerDiscoveryIssue, ...] = ()
    managed_count: int = 0
