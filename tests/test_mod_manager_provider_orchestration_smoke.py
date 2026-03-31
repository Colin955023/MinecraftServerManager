from __future__ import annotations

from pathlib import Path
import time
from typing import Any

import pytest

from src.core import ModManager, ModPlatform


class _StubIndexManager:
    def __init__(self) -> None:
        self.cached: list[tuple[Path, dict[str, str]]] = []

    def cache_provider_metadata(self, file_path: Path, payload: dict[str, str]) -> None:
        self.cached.append((Path(file_path), payload))


@pytest.mark.smoke
def test_resolve_platform_info_prefers_cached_slug_identifier_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ModManager.__new__(ModManager)
    manager.index_manager = _StubIndexManager()
    manager._modrinth_identity_cache = {}

    monkeypatch.setattr(
        manager,
        "_resolve_modrinth_project_identity",
        lambda _identifier: ("YL57xq9U", "inventory-profiles-next"),
    )

    def _unexpected_fallback(*_args: Any, **_kwargs: Any):
        raise AssertionError("fallback search should not be called when cached slug can be resolved")

    monkeypatch.setattr(manager, "_detect_platform_info", _unexpected_fallback)

    platform, platform_id, platform_slug = manager._resolve_platform_info(
        file_path=Path("mods/inventoryprofilesnext.jar"),
        name="Inventory Profiles Next",
        base_name="inventoryprofilesnext",
        filename="inventoryprofilesnext.jar",
        cached_provider={"platform": "modrinth", "slug": "inventoryprofilesnext"},
    )

    assert platform == ModPlatform.MODRINTH
    assert platform_id == "YL57xq9U"
    assert platform_slug == "inventory-profiles-next"
    assert manager.index_manager.cached[-1][1]["project_id"] == "YL57xq9U"
    assert manager.index_manager.cached[-1][1]["slug"] == "inventory-profiles-next"


@pytest.mark.smoke
def test_resolve_platform_info_uses_fallback_detection_when_no_cached_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ModManager.__new__(ModManager)
    manager.index_manager = _StubIndexManager()
    manager._modrinth_identity_cache = {}

    monkeypatch.setattr(
        manager,
        "_detect_platform_info",
        lambda *_args, **_kwargs: (ModPlatform.MODRINTH, "AANobbMI", "sodium"),
    )

    platform, platform_id, platform_slug = manager._resolve_platform_info(
        file_path=Path("mods/sodium.jar"),
        name="Sodium",
        base_name="sodium",
        filename="sodium.jar",
        cached_provider={},
    )

    assert platform == ModPlatform.MODRINTH
    assert platform_id == "AANobbMI"
    assert platform_slug == "sodium"
    assert manager.index_manager.cached[-1][1]["project_id"] == "AANobbMI"


@pytest.mark.smoke
def test_resolve_platform_info_keeps_local_without_lookup_when_cached_local_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ModManager.__new__(ModManager)
    manager.index_manager = _StubIndexManager()
    manager._modrinth_identity_cache = {}

    def _unexpected_detect(*_args: Any, **_kwargs: Any):
        raise AssertionError("cached local marker should short-circuit provider detection")

    monkeypatch.setattr(manager, "_detect_platform_info", _unexpected_detect)

    platform, platform_id, platform_slug = manager._resolve_platform_info(
        file_path=Path("mods/local-only.jar"),
        name="Local Only",
        base_name="local-only",
        filename="local-only.jar",
        cached_provider={"platform": "local"},
    )

    assert platform == ModPlatform.LOCAL
    assert platform_id == ""
    assert platform_slug == ""
    assert manager.index_manager.cached == []


@pytest.mark.smoke
def test_resolve_platform_info_re_resolves_when_cached_provider_is_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ModManager.__new__(ModManager)
    manager.index_manager = _StubIndexManager()
    manager._modrinth_identity_cache = {}

    stale_epoch_ms = int(time.time() * 1000) - (13 * 60 * 60 * 1000)
    resolve_calls = {"count": 0}
    detect_calls = {"count": 0}

    def _track_resolve(_identifier: str) -> tuple[str, str]:
        resolve_calls["count"] += 1
        return "YL57xq9U", "inventory-profiles-next"

    monkeypatch.setattr(manager, "_resolve_modrinth_project_identity", _track_resolve)

    def _track_detect(*_args: Any, **_kwargs: Any) -> tuple[ModPlatform, str, str]:
        detect_calls["count"] += 1
        return ModPlatform.MODRINTH, "YL57xq9U", "inventory-profiles-next"

    monkeypatch.setattr(
        manager,
        "_detect_platform_info",
        _track_detect,
    )

    platform, platform_id, platform_slug = manager._resolve_platform_info(
        file_path=Path("mods/inventoryprofilesnext.jar"),
        name="Inventory Profiles Next",
        base_name="inventoryprofilesnext",
        filename="inventoryprofilesnext.jar",
        cached_provider={
            "platform": "modrinth",
            "project_id": "inventoryprofilesnext",
            "slug": "inventoryprofilesnext",
            "resolved_at_epoch_ms": str(stale_epoch_ms),
        },
    )

    assert platform == ModPlatform.MODRINTH
    assert platform_id == "YL57xq9U"
    assert platform_slug == "inventory-profiles-next"
    assert detect_calls["count"] >= 1
    assert resolve_calls["count"] == 0
