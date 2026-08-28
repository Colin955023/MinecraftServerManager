"""Mod Review workflow 的不可變外部契約"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

ReviewMode = Literal["online_install", "local_update"]


@dataclass(frozen=True, slots=True)
class ReviewContextStamp:
    """拒絕過期 Review 執行所需的伺服器與本地 Mod revision"""

    server_identity: str
    minecraft_version: str
    loader_type: str
    loader_version: str
    installed_mod_revision: tuple[tuple[str, str, str, str, int, int], ...]


@dataclass(frozen=True, slots=True)
class ReviewTaskView:
    """Review 工作樹單一節點的不可變呈現資料"""

    node_id: str
    root_key: str
    group_key: str
    title: str
    values: tuple[str, ...]
    node_kind: str
    parent_id: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class ReviewRootView:
    """Review root 的摘要與專案頁面資料"""

    root_key: str
    summary: str
    project_page_url: str


@dataclass(frozen=True, slots=True)
class ReviewViewSnapshot:
    """Qt adapter 繪製完整 Review 所需的不可變快照"""

    mode: ReviewMode
    subtitle: str
    overview: str
    task_nodes: tuple[ReviewTaskView, ...]
    roots: tuple[ReviewRootView, ...]
    group_specs: tuple[tuple[str, str], ...]
    action_label: str
    selected_count: int
    actionable_count: int
    blocked_count: int

    def root(self, root_key: str) -> ReviewRootView | None:
        """依 stable root key 取得摘要資料

        Args:
            root_key: Review root 的穩定識別碼

        Returns:
            相符的 root view；不存在時為 None
        """
        return next((root for root in self.roots if root.root_key == root_key), None)


@dataclass(frozen=True, slots=True)
class ReviewInstallStep:
    """Executor 可直接執行的下載、安裝或更新步驟"""

    kind: Literal["dependency", "online_root", "local_root"]
    root_key: str
    project_name: str
    version_name: str
    download_url: str
    filename: str
    expected_hash: str
    provider: str
    local_file_path: str = ""
    local_status: str = "enabled"


@dataclass(frozen=True, slots=True)
class ReviewExecutionHandoff:
    """Review session 驗證後交給 executor 的不可變執行契約"""

    mode: ReviewMode
    context_stamp: ReviewContextStamp
    steps: tuple[ReviewInstallStep, ...]
    root_keys: tuple[str, ...]
    confirmation_prompt: str
    source_confirmation_prompt: str
    skipped_text: str = ""
    completion_notes: str = ""
    unselected_count: int = 0
    dependency_count: int = 0
    duplicate_dependency_count: int = 0

    @property
    def root_count(self) -> int:
        return len(self.root_keys)


def normalize_status_value(value: Any) -> str:
    """
    將 enum 或字串狀態轉為小寫穩定值

    Args:
        value: Enum、字串或其他狀態值

    Returns:
        去除空白並轉為小寫的狀態字串
    """
    return str(getattr(value, "value", value) or "").strip().lower()


def _mod_revision_item(mod: Any) -> tuple[str, str, str, str, int, int]:
    file_path = str(getattr(mod, "file_path", "") or "").strip()
    resolved_path = str(Path(file_path).resolve(strict=False)) if file_path else ""
    size = int(getattr(mod, "file_size", 0) or 0)
    modified_ns = 0
    with suppress(OSError):
        if file_path:
            stat_result = Path(file_path).stat()
            size = stat_result.st_size
            modified_ns = stat_result.st_mtime_ns
    return (
        resolved_path or str(getattr(mod, "filename", "") or "").strip(),
        str(getattr(mod, "current_hash", "") or "").strip().lower(),
        str(getattr(mod, "version", "") or "").strip(),
        normalize_status_value(getattr(mod, "status", "")),
        size,
        modified_ns,
    )


def build_review_context_stamp(server: Any, installed_mods: list[Any]) -> ReviewContextStamp:
    """
    由伺服器與已安裝 Mod 建立執行前 context stamp

    Args:
        server: 目前伺服器設定
        installed_mods: 目前已安裝 Mod 清單

    Returns:
        可在 handoff 執行前重新比對的不可變 stamp
    """
    server_path = str(getattr(server, "path", "") or "").strip()
    server_identity = str(Path(server_path).resolve(strict=False)) if server_path else ""
    if not server_identity:
        server_identity = str(getattr(server, "name", "") or "").strip()
    return ReviewContextStamp(
        server_identity=server_identity,
        minecraft_version=str(getattr(server, "minecraft_version", "") or "").strip(),
        loader_type=str(getattr(server, "loader_type", "") or "").strip().lower(),
        loader_version=str(getattr(server, "loader_version", "") or "").strip(),
        installed_mod_revision=tuple(sorted(_mod_revision_item(mod) for mod in installed_mods)),
    )


def describe_context_mismatch(expected: ReviewContextStamp, actual: ReviewContextStamp) -> str:
    """
    描述兩個 Review context 最先出現的差異

    Args:
        expected: Review 建立時的 context
        actual: 執行前重新取得的 context

    Returns:
        使用者可讀的失效原因；完全相符時回傳空字串
    """
    if expected.server_identity != actual.server_identity:
        return "目標伺服器已變更"
    if expected.minecraft_version != actual.minecraft_version:
        return "Minecraft 版本已變更"
    if expected.loader_type != actual.loader_type or expected.loader_version != actual.loader_version:
        return "Loader context 已變更"
    if expected.installed_mod_revision != actual.installed_mod_revision:
        return "本地 Mod 清單已變更"
    return ""


__all__ = [
    "ReviewExecutionHandoff",
    "ReviewInstallStep",
    "ReviewMode",
    "ReviewRootView",
    "ReviewTaskView",
    "ReviewViewSnapshot",
    "build_review_context_stamp",
    "describe_context_mismatch",
    "normalize_status_value",
]
