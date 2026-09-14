"""Mod Review workflow 的內部可變狀態"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.models import PendingOnlineInstall


@dataclass(slots=True, kw_only=True)
class AbstractReviewEntry:
    """Review 項目的阻擋、提醒與本次變更選取狀態"""

    blocking_reasons: list[str] = field(default_factory=list)
    warning_messages: list[str] = field(default_factory=list)
    selected: bool = True
    provider: str = "modrinth"
    version_type: str = ""
    date_published: str = ""
    changelog: str = ""
    selected_dependency_keys: set[tuple[str, str]] = field(default_factory=set)

    @property
    def actionable(self) -> bool:
        return self.selected and self.runnable

    @property
    def runnable(self) -> bool:
        return not self.blocking_reasons


@dataclass(slots=True, kw_only=True)
class PendingInstallReviewEntry(AbstractReviewEntry):
    """待安裝項目的 workflow 內部驗證狀態"""

    pending: PendingOnlineInstall
    report: Any | None
    dependency_plan: Any


@dataclass(slots=True, kw_only=True)
class LocalUpdateReviewEntry(AbstractReviewEntry):
    """本地模組更新的 workflow 內部驗證狀態"""

    candidate: Any
    dependency_plan: Any


@dataclass(slots=True)
class ReviewTaskNode:
    """產生 immutable view snapshot 前的內部工作節點"""

    node_id: str
    root_key: str
    group_key: str
    title: str
    values: tuple[str, ...]
    node_kind: str
    parent_id: str | None = None
    detail: str = ""


__all__ = ["LocalUpdateReviewEntry", "PendingInstallReviewEntry", "ReviewTaskNode"]
