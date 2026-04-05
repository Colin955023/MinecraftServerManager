from __future__ import annotations

from src.models import OnlineModVersion, ResolvedDependencyReference
from src.utils import resolve_dependency_reference


def test_resolve_dependency_reference_prefers_cached_project_name() -> None:
    calls = {"version": 0, "name": 0}

    def _get_mod_version_details(_: str) -> tuple[str, OnlineModVersion | None]:
        calls["version"] += 1
        return ("", None)

    def _fetch_project_name(_: str) -> str | None:
        calls["name"] += 1
        return None

    resolved = resolve_dependency_reference(
        {"project_id": " qvIfYCYJ ", "version_id": ""},
        {"qvifycyj": "Quilt Standard Libraries"},
        get_mod_version_details=_get_mod_version_details,
        fetch_project_name=_fetch_project_name,
    )

    assert isinstance(resolved, ResolvedDependencyReference)
    assert resolved.project_id == "qvIfYCYJ"
    assert resolved.project_name == "Quilt Standard Libraries"
    assert resolved.resolution_source == "project_id"
    assert calls == {"version": 0, "name": 0}


def test_resolve_dependency_reference_uses_version_detail_cache() -> None:
    calls = {"version": 0, "name": 0}
    dependency_names: dict[str, str] = {}
    version_cache: dict[str, tuple[str, OnlineModVersion | None]] = {}
    version = OnlineModVersion(version_id="ver-1", version_number="1.0.0", display_name="1.0.0")

    def _get_mod_version_details(version_id: str) -> tuple[str, OnlineModVersion | None]:
        calls["version"] += 1
        assert version_id == "version-lookup-1"
        return ("Project-A", version)

    def _fetch_project_name(project_id: str) -> str | None:
        calls["name"] += 1
        assert project_id == "Project-A"
        return "Project Alpha"

    first = resolve_dependency_reference(
        {"version_id": "version-lookup-1"},
        dependency_names,
        version_details_cache=version_cache,
        get_mod_version_details=_get_mod_version_details,
        fetch_project_name=_fetch_project_name,
    )
    second = resolve_dependency_reference(
        {"version_id": "version-lookup-1"},
        dependency_names,
        version_details_cache=version_cache,
        get_mod_version_details=_get_mod_version_details,
        fetch_project_name=_fetch_project_name,
    )

    assert first.project_id == "Project-A"
    assert first.version_name == "1.0.0"
    assert first.project_name == "Project Alpha"
    assert second.project_name == "Project Alpha"
    assert calls == {"version": 1, "name": 1}


def test_resolve_dependency_reference_applies_loader_override() -> None:
    version = OnlineModVersion(version_id="legacy-v", version_number="0.0.1", display_name="0.0.1")

    resolved = resolve_dependency_reference(
        {"project_id": "qvIfYCYJ", "version_id": "legacy-v"},
        {},
        loader="fabric",
        get_mod_version_details=lambda _: ("qvIfYCYJ", version),
        fetch_project_name=lambda _: None,
    )

    assert resolved.project_id == "P7dR8mSH"
    assert resolved.version_id == ""
    assert resolved.version_name == ""
    assert resolved.version is None
    assert resolved.resolution_source == "loader_override"
    assert resolved.resolution_confidence == "fallback"
