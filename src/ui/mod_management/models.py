"""模組管理頁面資料模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PendingOnlineInstall:
    """待安裝的線上模組項目。"""

    project_id: str
    project_name: str
    version: Any
    report: Any | None = None
    homepage_url: str = ""
    source_url: str = ""
    server_side: str = ""
    client_side: str = ""


@dataclass(slots=True, kw_only=True)
class AbstractReviewEntry:
    """Review 項目共用屬性與狀態判斷。"""

    blocking_reasons: list[str] = field(default_factory=list)
    warning_messages: list[str] = field(default_factory=list)
    enabled: bool = True
    provider: str = "modrinth"
    version_type: str = ""
    date_published: str = ""
    changelog: str = ""

    @property
    def actionable(self) -> bool:
        return self.enabled and (not self.blocking_reasons)

    @property
    def runnable(self) -> bool:
        return not self.blocking_reasons


@dataclass(slots=True, kw_only=True)
class PendingInstallReviewEntry(AbstractReviewEntry):
    """待安裝項目的最終驗證結果。"""

    pending: PendingOnlineInstall
    report: Any | None
    dependency_plan: Any


@dataclass(slots=True, kw_only=True)
class LocalUpdateReviewEntry(AbstractReviewEntry):
    """本地模組更新 review 項目。"""

    candidate: Any
    dependency_plan: Any

    @property
    def candidate_actionable(self) -> bool:
        return bool(getattr(self.candidate, "actionable", False))


@dataclass(slots=True)
class ReviewTaskNode:
    """Review 對話框中的共用 task 節點。"""

    node_id: str
    root_key: str
    group_key: str
    title: str
    values: tuple[str, ...]
    node_kind: str
    parent_id: str | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class OnlineBrowseRequest:
    """線上模組瀏覽/搜尋請求。"""

    query: str
    minecraft_version: str | None
    loader_type: str
    sort_by: str


__all__ = [
    "AbstractReviewEntry",
    "LocalUpdateReviewEntry",
    "OnlineBrowseRequest",
    "PendingInstallReviewEntry",
    "PendingOnlineInstall",
    "ReviewTaskNode",
]
