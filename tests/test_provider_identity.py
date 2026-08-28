from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from src.core.mods.modrinth_provider_adapter import ModrinthProviderAdapter
from src.core.mods.provider_identity import ProviderIdentityService
from src.models import (
    HTTPJSONResponse,
    ProviderCatalogOutcome,
    ProviderIdentityEvidence,
    ProviderIdentitySnapshot,
)
from src.utils import HTTPClient


class MemoryIdentityStore:
    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self.initial = initial
        self.payload = initial
        self._payloads: dict[Path, dict[str, Any]] = {}
        self.writes: list[dict[str, Any]] = []

    def load(self, file_path: Path) -> dict[str, Any] | None:
        return self._payloads.get(file_path, self.initial)

    def replace(self, file_path: Path, payload: dict[str, Any]) -> None:
        self.payload = dict(payload)
        self._payloads[file_path] = dict(payload)
        self.writes.append(dict(payload))


class FakeCatalog:
    def __init__(self, outcome: ProviderCatalogOutcome) -> None:
        self.outcome = outcome
        self.lookups: list[str] = []
        self.searches: list[str] = []

    def lookup(self, identifier: str) -> ProviderCatalogOutcome:
        self.lookups.append(identifier)
        return self.outcome

    def search(self, query: str) -> ProviderCatalogOutcome:
        self.searches.append(query)
        return self.outcome


def test_legacy_identity_without_timestamp_is_stale() -> None:
    snapshot = ProviderIdentitySnapshot.from_payload(
        {"platform": "modrinth", "project_id": "project-old", "slug": "old-alias"}
    )

    assert snapshot.lifecycle == "stale"
    assert snapshot.canonical is False


def test_service_replaces_identity_payload_with_canonical_catalog_result(tmp_path: Path) -> None:
    store = MemoryIdentityStore(
        {
            "schema_version": 2,
            "provider": "modrinth",
            "alias": "obsolete-alias",
            "lifecycle": "retrying",
        }
    )
    catalog = FakeCatalog(
        ProviderCatalogOutcome(
            "found",
            provider="modrinth",
            project_id="project-1",
            alias="",
            display_name="Example",
            confidence=100,
        )
    )
    service = ProviderIdentityService(store=store, catalog=catalog)

    snapshot = service.resolve(ProviderIdentityEvidence(file_path=tmp_path / "example.jar", alias_hint="example"))

    assert snapshot.canonical is True
    assert store.payload == snapshot.as_payload()
    assert store.payload is not None
    assert store.payload["alias"] == ""
    assert "slug" not in store.payload


def test_hash_identity_change_clears_alias_from_previous_project(tmp_path: Path) -> None:
    stale_ms = int(time.time() * 1000) - 13 * 60 * 60 * 1000
    store = MemoryIdentityStore(
        ProviderIdentitySnapshot(
            provider="modrinth",
            project_id="old-project",
            alias="old-alias",
            lifecycle="stale",
            resolved_at_epoch_ms=stale_ms,
        ).as_payload()
    )
    service = ProviderIdentityService(store=store, catalog=FakeCatalog(ProviderCatalogOutcome("not_found")))

    snapshot = service.resolve(
        ProviderIdentityEvidence(file_path=tmp_path / "example.jar", hash_project_id="new-project")
    )

    assert snapshot.project_id == "new-project"
    assert snapshot.alias == ""


def test_transient_failure_enters_backoff_without_requery(tmp_path: Path) -> None:
    store = MemoryIdentityStore()
    catalog = FakeCatalog(ProviderCatalogOutcome("transient_failure"))
    service = ProviderIdentityService(store=store, catalog=catalog)
    evidence = ProviderIdentityEvidence(file_path=tmp_path / "example.jar", alias_hint="example")

    first = service.resolve(evidence)
    second = service.resolve(evidence)

    assert first.lifecycle == "retrying"
    assert second == first
    assert catalog.lookups == ["example"]
    assert catalog.searches == []


def test_resolution_batch_caps_catalog_items(tmp_path: Path) -> None:
    store = MemoryIdentityStore()
    catalog = FakeCatalog(ProviderCatalogOutcome("not_found"))
    service = ProviderIdentityService(store=store, catalog=catalog)
    service.begin_resolution_batch(limit=1)

    first = service.resolve(ProviderIdentityEvidence(file_path=tmp_path / "one.jar", alias_hint="one"))
    second = service.resolve(ProviderIdentityEvidence(file_path=tmp_path / "two.jar", alias_hint="two"))
    service.end_resolution_batch()

    assert first.lifecycle == "retrying"
    assert second.lifecycle == "missing"
    assert catalog.lookups == ["one"]


def test_legacy_stale_journey_retries_then_commits_fresh_and_rescans_offline(tmp_path: Path) -> None:
    file_path = tmp_path / "example.jar"
    store = MemoryIdentityStore({"platform": "modrinth", "project_id": "legacy-id", "slug": "legacy-alias"})
    catalog = FakeCatalog(ProviderCatalogOutcome("transient_failure"))
    service = ProviderIdentityService(store=store, catalog=catalog)
    evidence = ProviderIdentityEvidence(file_path=file_path, alias_hint="legacy-alias")

    retrying = service.resolve(evidence)
    catalog.outcome = ProviderCatalogOutcome(
        "found",
        project_id="canonical-id",
        alias="current-alias",
        display_name="Example",
        confidence=100,
    )
    fresh = service.resolve(evidence, force=True)
    catalog.lookups.clear()
    rescanned = ProviderIdentityService(store=store, catalog=catalog).resolve(evidence)

    assert retrying.lifecycle == "retrying"
    assert fresh.canonical is True
    assert fresh.project_id == "canonical-id"
    assert rescanned == fresh
    assert catalog.lookups == []


def test_rate_limit_is_typed_and_does_not_fall_through_to_search(monkeypatch, tmp_path: Path) -> None:
    requested_urls: list[str] = []

    def fake_response(url: str, *_args, **_kwargs) -> HTTPJSONResponse:
        requested_urls.append(url)
        return HTTPJSONResponse(429, error_kind="rate_limited")

    monkeypatch.setattr(
        HTTPClient,
        "fetch_json_response",
        fake_response,
    )
    adapter = ModrinthProviderAdapter()
    store = MemoryIdentityStore()
    service = ProviderIdentityService(store=store, catalog=adapter)

    snapshot = service.resolve(
        ProviderIdentityEvidence(
            file_path=tmp_path / "example.jar",
            alias_hint="example",
            search_terms=("Example",),
        )
    )

    assert snapshot.lifecycle == "retrying"
    assert snapshot.provenance == "catalog_rate_limited"
    assert requested_urls == ["https://api.modrinth.com/v2/project/example"]


def test_modrinth_adapter_maps_not_found_without_creating_identity(monkeypatch) -> None:
    monkeypatch.setattr(
        HTTPClient,
        "fetch_json_response",
        lambda *_args, **_kwargs: HTTPJSONResponse(404, error_kind="not_found"),
    )

    outcome = ModrinthProviderAdapter().lookup("missing-project")

    assert outcome.kind == "not_found"
    assert outcome.canonical is False
