"""依賴計畫序列化工具。

集中處理 dependency plan 的資料模型、序列化、遷移與驗證邏輯，
讓 UI 層只保留查詢與流程組裝責任。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEPENDENCY_PLAN_PERSISTENCE_SCHEMA_VERSION = 1


@dataclass(slots=True)
class OnlineDependencyInstallItem:
    """必要依賴的自動安裝項目。"""

    project_id: str
    project_name: str
    version_id: str
    version_name: str
    filename: str
    download_url: str
    parent_name: str = ""
    maybe_installed: bool = False
    status_note: str = ""
    resolution_source: str = "project_id"
    resolution_confidence: str = "direct"
    enabled: bool = True
    is_optional: bool = False
    provider: str = "modrinth"
    required_by: list[str] = field(default_factory=list)
    decision_source: str = "required:auto"
    graph_depth: int = 1
    edge_kind: str = "required"
    edge_source: str = "required:modrinth_dependency"


@dataclass(slots=True)
class OnlineDependencyInstallPlan:
    """必要依賴的連鎖安裝計畫。"""

    items: list[OnlineDependencyInstallItem] = field(default_factory=list)
    advisory_items: list[OnlineDependencyInstallItem] = field(default_factory=list)
    unresolved_required: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def auto_install_count(self) -> int:
        """取得可自動安裝的項目數量。"""
        return len(self.items)

    @property
    def has_unresolved_required(self) -> bool:
        """判斷是否存在無法解析的必要依賴。"""
        return bool(self.unresolved_required)


def _get_source_value(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _normalize_string_list(raw_values: Any) -> list[str]:
    if not isinstance(raw_values, list):
        return []
    normalized: list[str] = []
    for value in raw_values:
        text = str(value or "").strip()
        if text:
            normalized.append(text)
    return normalized


def _normalize_required_by(item: Any) -> list[str]:
    if isinstance(item, dict):
        required_by = _normalize_string_list(item.get("required_by", []))
        if required_by:
            return required_by
        parent_name = str(item.get("parent_name", "") or "").strip()
        return [parent_name] if parent_name else []
    required_by = _normalize_string_list(getattr(item, "required_by", []))
    if required_by:
        return required_by
    parent_name = str(getattr(item, "parent_name", "") or "").strip()
    return [parent_name] if parent_name else []


def _normalize_text_value(source: Any, key: str, default: str = "", *, lowercase: bool = False) -> str:
    """正規化物件或映射中的文字欄位。"""
    raw_value = _get_source_value(source, key, default)
    value = str(raw_value or default).strip()
    if lowercase:
        return value.lower()
    return value


def _normalize_positive_int_value(source: Any, key: str, default: int = 1, min_value: int = 1) -> int:
    """正規化物件或映射中的正整數欄位。"""
    raw_value = _get_source_value(source, key, default)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = default
    if value < min_value:
        return min_value
    return value


def _build_dependency_graph_edge_payload(item_payload: Any, *, default_edge_kind: str = "required") -> dict[str, Any]:
    """將 dependency item 正規化為 graph edge payload。"""
    edge_kind = _normalize_text_value(item_payload, "edge_kind", default_edge_kind, lowercase=True) or default_edge_kind
    edge_source = _normalize_text_value(item_payload, "edge_source", "", lowercase=True)
    if not edge_source:
        edge_source = f"{edge_kind}:modrinth_dependency"
    return {
        "to_project_id": _normalize_text_value(item_payload, "project_id"),
        "to_version_id": _normalize_text_value(item_payload, "version_id"),
        "required_by": _normalize_string_list(_get_source_value(item_payload, "required_by", [])),
        "edge": edge_kind,
        "source": edge_source,
        "depth": _normalize_positive_int_value(item_payload, "graph_depth"),
        "decision_source": _normalize_text_value(item_payload, "decision_source") or "required:auto",
        "is_optional": bool(_get_source_value(item_payload, "is_optional", False)),
    }


def _build_online_dependency_install_item(payload: Any) -> OnlineDependencyInstallItem | None:
    """將 payload 還原為 `OnlineDependencyInstallItem`。"""
    if not isinstance(payload, dict):
        return None
    graph_depth = _normalize_positive_int_value(payload, "graph_depth")
    edge_kind = _normalize_text_value(payload, "edge_kind", "required", lowercase=True) or "required"
    edge_source = _normalize_text_value(payload, "edge_source", "", lowercase=True)
    if not edge_source:
        edge_source = f"{edge_kind}:modrinth_dependency"
    return OnlineDependencyInstallItem(
        project_id=_normalize_text_value(payload, "project_id"),
        project_name=_normalize_text_value(payload, "project_name"),
        version_id=_normalize_text_value(payload, "version_id"),
        version_name=_normalize_text_value(payload, "version_name"),
        filename=_normalize_text_value(payload, "filename"),
        download_url=_normalize_text_value(payload, "download_url"),
        parent_name=_normalize_text_value(payload, "parent_name"),
        maybe_installed=bool(payload.get("maybe_installed", False)),
        status_note=_normalize_text_value(payload, "status_note"),
        resolution_source=_normalize_text_value(payload, "resolution_source", "project_id"),
        resolution_confidence=_normalize_text_value(payload, "resolution_confidence", "direct"),
        enabled=bool(payload.get("enabled", True)),
        is_optional=bool(payload.get("is_optional", False)),
        provider=_normalize_text_value(payload, "provider", "modrinth") or "modrinth",
        required_by=_normalize_string_list(payload.get("required_by", [])),
        decision_source=_normalize_text_value(payload, "decision_source") or "required:auto",
        graph_depth=graph_depth,
        edge_kind=edge_kind,
        edge_source=edge_source,
    )


def serialize_online_dependency_install_item(item: Any) -> dict[str, Any]:
    """將依賴安裝項目正規化為可持久化 payload。

    Args:
        item: 原始依賴安裝項目，可以是物件或映射。

    Returns:
        可直接序列化與持久化的標準化字典。
    """
    graph_depth = _normalize_positive_int_value(item, "graph_depth")
    edge_kind = _normalize_text_value(item, "edge_kind", "required", lowercase=True) or "required"
    edge_source = _normalize_text_value(item, "edge_source", f"{edge_kind}:modrinth_dependency", lowercase=True)
    if not edge_source:
        edge_source = f"{edge_kind}:modrinth_dependency"
    return {
        "provider": _normalize_text_value(item, "provider", "modrinth") or "modrinth",
        "project_id": _normalize_text_value(item, "project_id"),
        "project_name": _normalize_text_value(item, "project_name"),
        "version_id": _normalize_text_value(item, "version_id"),
        "version_name": _normalize_text_value(item, "version_name"),
        "filename": _normalize_text_value(item, "filename"),
        "download_url": _normalize_text_value(item, "download_url"),
        "parent_name": _normalize_text_value(item, "parent_name"),
        "required_by": _normalize_required_by(item),
        "maybe_installed": bool(_get_source_value(item, "maybe_installed", False)),
        "status_note": _normalize_text_value(item, "status_note"),
        "resolution_source": _normalize_text_value(item, "resolution_source", "project_id"),
        "resolution_confidence": _normalize_text_value(item, "resolution_confidence", "direct"),
        "decision_source": _normalize_text_value(item, "decision_source") or "required:auto",
        "enabled": bool(_get_source_value(item, "enabled", True)),
        "is_optional": bool(_get_source_value(item, "is_optional", False)),
        "graph_depth": graph_depth,
        "edge_kind": edge_kind,
        "edge_source": edge_source,
    }


def serialize_online_dependency_install_plan(
    plan: Any,
    *,
    root_project_id: str = "",
    root_project_name: str = "",
    root_target_version_id: str = "",
    root_target_version_name: str = "",
    root_enabled: bool | None = None,
    plan_source: str = "review",
) -> dict[str, Any]:
    """將依賴安裝計畫轉為可持久化 payload。

    Args:
        plan: 原始依賴安裝計畫。
        root_project_id: 根專案 ID。
        root_project_name: 根專案名稱。
        root_target_version_id: 根目標版本 ID。
        root_target_version_name: 根目標版本名稱。
        root_enabled: 根專案是否啟用。
        plan_source: 計畫來源標記。

    Returns:
        可寫入快取或檔案的計畫 payload。
    """
    serialized_items = [
        serialize_online_dependency_install_item(item) for item in list(getattr(plan, "items", []) or [])
    ]
    serialized_advisory_items = [
        serialize_online_dependency_install_item(item) for item in list(getattr(plan, "advisory_items", []) or [])
    ]
    graph_edges = [
        _build_dependency_graph_edge_payload(item_payload)
        for item_payload in [*serialized_items, *serialized_advisory_items]
    ]
    payload: dict[str, Any] = {
        "schema_version": DEPENDENCY_PLAN_PERSISTENCE_SCHEMA_VERSION,
        "plan_source": str(plan_source or "review").strip() or "review",
        "root_project_id": str(root_project_id or "").strip(),
        "root_project_name": str(root_project_name or "").strip(),
        "root_target_version_id": str(root_target_version_id or "").strip(),
        "root_target_version_name": str(root_target_version_name or "").strip(),
        "items": serialized_items,
        "advisory_items": serialized_advisory_items,
        "graph_edges": graph_edges,
        "unresolved_required": _normalize_string_list(getattr(plan, "unresolved_required", [])),
        "notes": _normalize_string_list(getattr(plan, "notes", [])),
    }
    if root_enabled is not None:
        payload["root_enabled"] = bool(root_enabled)
    return payload


def validate_online_dependency_install_plan_payload(raw: dict[str, Any] | None) -> tuple[bool, str]:
    """驗證 dependency plan 快照是否符合 replay 契約。

    Args:
        raw: 待驗證的原始 payload。

    Returns:
        `(是否通過, 原因碼)` 的驗證結果。
    """
    if not isinstance(raw, dict):
        return (False, "payload-not-dict")
    schema_version = raw.get("schema_version")
    if schema_version != DEPENDENCY_PLAN_PERSISTENCE_SCHEMA_VERSION:
        return (False, "schema-mismatch")
    graph_edges = raw.get("graph_edges")
    if not isinstance(graph_edges, list):
        return (False, "missing-graph-edges")
    for edge_payload in graph_edges:
        if not isinstance(edge_payload, dict):
            return (False, "invalid-graph-edge")
        try:
            depth = int(edge_payload.get("depth", 0) or 0)
        except (TypeError, ValueError):
            return (False, "invalid-graph-depth")
        if depth < 1:
            return (False, "invalid-graph-depth")
        edge_kind = str(edge_payload.get("edge", "") or "").strip().lower()
        edge_source = str(edge_payload.get("source", "") or "").strip().lower()
        if edge_kind not in {"required", "optional", "incompatible", "embedded", "unknown"}:
            return (False, "invalid-edge-kind")
        if not edge_source:
            return (False, "invalid-edge-source")
        required_by = edge_payload.get("required_by", [])
        if required_by is not None and (not isinstance(required_by, list)):
            return (False, "invalid-required-by")
    for collection_key in ("items", "advisory_items"):
        entries = raw.get(collection_key, [])
        if not isinstance(entries, list):
            return (False, f"invalid-{collection_key}")
        for item_payload in entries:
            if not isinstance(item_payload, dict):
                return (False, f"invalid-{collection_key}-entry")
            try:
                item_depth = int(item_payload.get("graph_depth", 0) or 0)
            except (TypeError, ValueError):
                return (False, "invalid-item-depth")
            if item_depth < 1:
                return (False, "invalid-item-depth")
            item_edge_kind = str(item_payload.get("edge_kind", "") or "").strip().lower()
            item_edge_source = str(item_payload.get("edge_source", "") or "").strip().lower()
            if not item_edge_kind:
                return (False, "missing-item-edge-kind")
            if not item_edge_source:
                return (False, "missing-item-edge-source")
    return (True, "ok")


def migrate_online_dependency_install_plan_payload(raw: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str]:
    """嘗試遷移舊版 dependency plan payload 至可回放格式。

    Args:
        raw: 待遷移的原始 payload。

    Returns:
        `(遷移後 payload, 狀態碼)` 的結果；失敗時回傳 `(None, 原因碼)`。
    """
    if not isinstance(raw, dict):
        return (None, "payload-not-dict")
    schema_version = raw.get("schema_version")
    if schema_version != DEPENDENCY_PLAN_PERSISTENCE_SCHEMA_VERSION:
        return (None, "schema-mismatch")
    migrated_payload: dict[str, Any] = dict(raw)
    migrated = False

    def _migrate_item_collection(collection_key: str) -> list[dict[str, Any]] | None:
        nonlocal migrated
        entries = migrated_payload.get(collection_key, [])
        if not isinstance(entries, list):
            return None
        normalized_entries: list[dict[str, Any]] = []
        optional_default = collection_key == "advisory_items"
        for entry in entries:
            if not isinstance(entry, dict):
                return None
            normalized_entry = dict(entry)
            if not _normalize_text_value(normalized_entry, "edge_kind"):
                normalized_entry["edge_kind"] = "optional" if optional_default else "required"
                migrated = True
            if not _normalize_text_value(normalized_entry, "edge_source"):
                normalized_entry["edge_source"] = f"{normalized_entry['edge_kind']}:modrinth_dependency"
                migrated = True
            if "graph_depth" not in normalized_entry:
                normalized_entry["graph_depth"] = 1
                migrated = True
            depth = _normalize_positive_int_value(normalized_entry, "graph_depth")
            if depth != normalized_entry.get("graph_depth", 1):
                migrated = True
            normalized_entry["graph_depth"] = depth
            if not isinstance(normalized_entry.get("required_by", []), list):
                normalized_entry["required_by"] = _normalize_string_list(normalized_entry.get("required_by", []))
                migrated = True
            normalized_entries.append(normalized_entry)
        return normalized_entries

    normalized_items = _migrate_item_collection("items")
    normalized_advisory_items = _migrate_item_collection("advisory_items")
    if normalized_items is None or normalized_advisory_items is None:
        return (None, "invalid-item-collection")
    migrated_payload["items"] = normalized_items
    migrated_payload["advisory_items"] = normalized_advisory_items
    graph_edges = migrated_payload.get("graph_edges")
    if not isinstance(graph_edges, list):
        migrated_payload["graph_edges"] = [
            _build_dependency_graph_edge_payload(item_payload)
            for item_payload in [*normalized_items, *normalized_advisory_items]
        ]
        migrated = True
    if migrated:
        notes = _normalize_string_list(migrated_payload.get("notes", []))
        migration_note = "已套用 dependency snapshot v1 遷移：補齊 graph_edges 與舊欄位預設值。"
        if migration_note not in notes:
            notes.append(migration_note)
        migrated_payload["notes"] = notes
    valid, reason = validate_online_dependency_install_plan_payload(migrated_payload)
    if not valid:
        return (None, f"migration-invalid:{reason}")
    if migrated:
        return (migrated_payload, "migrated")
    return (migrated_payload, "not-needed")


def deserialize_online_dependency_install_plan(raw: dict[str, Any] | None) -> OnlineDependencyInstallPlan:
    """從持久化 payload 還原 `OnlineDependencyInstallPlan`。

    Args:
        raw: 已序列化的原始 payload。

    Returns:
        還原後的 `OnlineDependencyInstallPlan`。
    """
    if not isinstance(raw, dict):
        return OnlineDependencyInstallPlan()

    items = [_build_online_dependency_install_item(item) for item in list(raw.get("items", []) or [])]
    advisory_items = [_build_online_dependency_install_item(item) for item in list(raw.get("advisory_items", []) or [])]
    return OnlineDependencyInstallPlan(
        items=[item for item in items if item is not None],
        advisory_items=[item for item in advisory_items if item is not None],
        unresolved_required=_normalize_string_list(raw.get("unresolved_required", [])),
        notes=_normalize_string_list(raw.get("notes", [])),
    )
