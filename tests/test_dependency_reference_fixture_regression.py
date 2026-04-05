from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.models import OnlineModVersion
from src.utils import resolve_dependency_reference

FIXTURE_PATH = Path(__file__).parent / "dependency_reference_cases.json"


def _build_online_mod_version(payload: dict[str, Any]) -> OnlineModVersion:
    return OnlineModVersion(
        version_id=str(payload.get("version_id", "") or ""),
        version_number=str(payload.get("version_number", "") or ""),
        display_name=str(payload.get("display_name", "") or payload.get("version_number", "") or ""),
        game_versions=[str(item) for item in payload.get("game_versions", []) if item],
        loaders=[str(item) for item in payload.get("loaders", []) if item],
        version_type=str(payload.get("version_type", "") or ""),
        date_published=str(payload.get("date_published", "") or ""),
        changelog=str(payload.get("changelog", "") or ""),
        files=list(payload.get("files", []) or []),
        dependencies=list(payload.get("dependencies", []) or []),
    )


def _serialize_resolved_dependency(result: Any) -> dict[str, Any]:
    return {
        "project_id": result.project_id,
        "project_name": result.project_name,
        "version_id": result.version_id,
        "version_name": result.version_name,
        "resolution_source": result.resolution_source,
        "resolution_confidence": result.resolution_confidence,
        "compare_project_id": result.compare_project_id,
        "label": result.label,
        "version": (
            {
                "version_id": result.version.version_id,
                "display_name": result.version.display_name,
            }
            if result.version is not None
            else None
        ),
    }


def test_dependency_reference_regression_with_offline_fixture() -> None:
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = list(raw.get("cases", []) or [])

    assert cases, "fixture cases should not be empty"

    for case in cases:
        call_stats = {"version_details": 0, "project_name": 0}
        version_details_payload = dict(case.get("version_details", {}) or {})
        project_names_payload = dict(case.get("project_names", {}) or {})
        dependency_names = dict(case.get("dependency_names", {}) or {})
        version_details_cache: dict[str, tuple[str, OnlineModVersion | None]] = {}

        def _get_mod_version_details(version_id: str) -> tuple[str, OnlineModVersion | None]:
            call_stats["version_details"] += 1
            payload = version_details_payload.get(version_id)
            if not isinstance(payload, dict):
                return ("", None)
            project_id = str(payload.get("project_id", "") or "")
            version_payload = payload.get("version")
            if not isinstance(version_payload, dict):
                return (project_id, None)
            return (project_id, _build_online_mod_version(version_payload))

        def _fetch_project_name(project_id: str) -> str | None:
            call_stats["project_name"] += 1
            value = project_names_payload.get(project_id)
            return str(value).strip() if value else None

        repeat = max(1, int(case.get("repeat", 1) or 1))
        expected = dict(case.get("expected", {}) or {})
        for _ in range(repeat):
            resolved = resolve_dependency_reference(
                dependency=dict(case.get("dependency", {}) or {}),
                dependency_names=dependency_names,
                loader=case.get("loader"),
                version_details_cache=version_details_cache,
                get_mod_version_details=_get_mod_version_details,
                fetch_project_name=_fetch_project_name,
            )
            assert _serialize_resolved_dependency(resolved) == expected, case.get("name", "unknown")

        assert call_stats == dict(case.get("expected_calls", {}) or {}), case.get("name", "unknown")
        assert dependency_names == dict(case.get("expected_dependency_names", {}) or {}), case.get("name", "unknown")
