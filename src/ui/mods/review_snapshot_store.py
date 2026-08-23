"""本地更新 dependency snapshot 的 Review internal store"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.models import LocalUpdateReviewEntry
from src.ui import mod_management_logger as logger
from src.utils import (
    deserialize_online_dependency_install_plan,
    migrate_online_dependency_install_plan_payload,
    serialize_online_dependency_install_plan,
    validate_online_dependency_install_plan_payload,
)


class LocalReviewSnapshotStore:
    """以 Mod index 保存及還原本地更新依賴規劃快照"""

    def __init__(self, manager: Any, telemetry: dict[str, int]) -> None:
        self._manager = manager
        self._telemetry = telemetry

    def _record(self, event: str) -> None:
        if event in self._telemetry:
            self._telemetry[event] += 1

    def save(self, candidate: Any, dependency_plan: Any, *, root_enabled: bool | None = None) -> None:
        """
        保存單一更新候選的 dependency plan

        Args:
            candidate: 含本地檔案與目標版本資料的更新候選
            dependency_plan: 要序列化的依賴規劃
            root_enabled: Review root 的選取狀態
        """
        local_mod = getattr(candidate, "local_mod", None)
        file_path_raw = str(getattr(local_mod, "file_path", "") or "").strip()
        if not file_path_raw:
            return
        snapshot = serialize_online_dependency_install_plan(
            dependency_plan,
            root_project_id=str(getattr(candidate, "project_id", "") or "").strip(),
            root_project_name=str(getattr(candidate, "project_name", "") or "").strip(),
            root_target_version_id=str(getattr(candidate, "target_version_id", "") or "").strip(),
            root_target_version_name=str(getattr(candidate, "target_version_name", "") or "").strip(),
            root_enabled=root_enabled,
            plan_source="local_update_review",
        )
        if not any(snapshot.get(key) for key in ("items", "advisory_items", "unresolved_required", "notes")):
            return
        file_path = Path(file_path_raw)
        review_metadata = self._manager.index_manager.get_review_metadata(file_path) or {}
        review_metadata["dependency_plan_v1"] = snapshot
        self._manager.index_manager.replace_review_metadata(file_path, review_metadata)

    def load(self, candidate: Any) -> tuple[Any | None, bool | None]:
        """
        載入、必要時遷移並驗證候選的 dependency plan

        Args:
            candidate: 要比對 project/version identity 的更新候選

        Returns:
            可重播的依賴規劃與先前 root 選取狀態
        """
        local_mod = getattr(candidate, "local_mod", None)
        file_path_raw = str(getattr(local_mod, "file_path", "") or "").strip()
        if not file_path_raw:
            return (None, None)
        review_metadata = self._manager.index_manager.get_review_metadata(Path(file_path_raw)) or {}
        snapshot_raw = review_metadata.get("dependency_plan_v1")
        if not isinstance(snapshot_raw, dict):
            return (None, None)
        self._record("checked")
        migrated_snapshot, migration_state = migrate_online_dependency_install_plan_payload(snapshot_raw)
        if migrated_snapshot is None:
            self._record("fallback_rebuild")
            return (None, None)
        if migration_state == "migrated":
            self._record("migrated")
            review_metadata["dependency_plan_v1"] = migrated_snapshot
            self._manager.index_manager.replace_review_metadata(Path(file_path_raw), review_metadata)
            logger.info(f"已遷移 dependency_plan_v1 快照並回寫：{file_path_raw}")
            snapshot_raw = migrated_snapshot
        snapshot_valid, _snapshot_reason = validate_online_dependency_install_plan_payload(snapshot_raw)
        if not snapshot_valid:
            self._record("fallback_rebuild")
            return (None, None)
        snapshot_root_enabled_raw = snapshot_raw.get("root_enabled")
        snapshot_root_enabled = snapshot_root_enabled_raw if isinstance(snapshot_root_enabled_raw, bool) else None
        expected_project_id = str(getattr(candidate, "project_id", "") or "").strip()
        expected_version_id = str(getattr(candidate, "target_version_id", "") or "").strip()
        actual_project_id = str(snapshot_raw.get("root_project_id", "") or "").strip()
        actual_version_id = str(snapshot_raw.get("root_target_version_id", "") or "").strip()
        if expected_project_id and actual_project_id and expected_project_id != actual_project_id:
            self._record("fallback_rebuild")
            return (None, snapshot_root_enabled)
        if expected_version_id and actual_version_id and expected_version_id != actual_version_id:
            self._record("fallback_rebuild")
            return (None, snapshot_root_enabled)
        restored = deserialize_online_dependency_install_plan(snapshot_raw)
        has_content = any(
            list(getattr(restored, key, []) or [])
            for key in ("items", "advisory_items", "unresolved_required", "notes")
        )
        if has_content:
            self._record("replayed")
        return (restored if has_content else None, snapshot_root_enabled)

    def save_entries(self, entries: tuple[LocalUpdateReviewEntry, ...]) -> None:
        """
        保存完整本地 Review session 的所有項目

        Args:
            entries: 要逐項保存的本地更新 Review 項目
        """
        for entry in entries:
            self.save(entry.candidate, entry.dependency_plan, root_enabled=bool(entry.enabled))


__all__ = ["LocalReviewSnapshotStore"]
