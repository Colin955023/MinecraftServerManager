from __future__ import annotations

import pytest

from src.utils import (
    PROVIDER_REVALIDATION_BATCH_MAX_PER_RUN,
    ProviderMetadataRecord,
    cache_provider_metadata_record,
    compute_provider_revalidation_backoff_seconds,
    ensure_local_mod_provider_record,
    is_provider_revalidation_retry_due,
    register_provider_revalidation_failure,
    register_provider_revalidation_success,
    should_attempt_provider_revalidation,
)


class _StubIndexManager:
    def __init__(self, cached_provider: dict[str, object] | None = None) -> None:
        self._cached_provider = dict(cached_provider or {})
        self.cached_payloads: list[dict[str, object]] = []

    def get_cached_provider_metadata(self, _file_path):
        return dict(self._cached_provider)

    def cache_provider_metadata(self, _file_path, payload: dict[str, object], *, merge: bool = True) -> None:
        del merge
        self.cached_payloads.append(dict(payload))


@pytest.mark.smoke
def test_ensure_local_mod_provider_record_uses_cached_pair_without_resolver() -> None:
    result = ensure_local_mod_provider_record(
        platform_id="AANobbMI",
        platform_slug="sodium",
        project_name="Sodium",
    )

    assert result.source == "cached_provider"
    assert result.resolved is True
    assert result.record.project_id == "AANobbMI"
    assert result.record.slug == "sodium"


@pytest.mark.smoke
def test_ensure_local_mod_provider_record_prefers_identifier_resolver_over_fallback() -> None:
    calls = {"identifier": 0, "fallback": 0}

    def _identifier_resolver(identifier: str) -> ProviderMetadataRecord:
        calls["identifier"] += 1
        assert identifier == "AANobbMI"
        return ProviderMetadataRecord.from_values(
            project_id="AANobbMI",
            slug="sodium",
            project_name="Sodium",
        )

    def _fallback_resolver() -> ProviderMetadataRecord | None:
        calls["fallback"] += 1
        return ProviderMetadataRecord.from_values(
            project_id="fallback",
            slug="fallback",
            project_name="Fallback",
        )

    result = ensure_local_mod_provider_record(
        platform_id="AANobbMI",
        platform_slug="",
        project_name="Sodium",
        identifier_resolver=_identifier_resolver,
        fallback_resolver=_fallback_resolver,
    )

    assert result.source == "cached_provider"
    assert result.resolved is True
    assert result.record.project_id == "AANobbMI"
    assert result.record.slug == "sodium"
    assert calls == {"identifier": 1, "fallback": 0}


@pytest.mark.smoke
def test_ensure_local_mod_provider_record_uses_fallback_when_cached_identifier_absent() -> None:
    calls = {"fallback": 0}

    def _fallback_resolver() -> ProviderMetadataRecord | None:
        calls["fallback"] += 1
        return ProviderMetadataRecord.from_values(
            project_id="P7dR8mSH",
            slug="fabric-api",
            project_name="Fabric API",
        )

    result = ensure_local_mod_provider_record(
        platform_id="",
        platform_slug="",
        project_name="Fabric API",
        fallback_resolver=_fallback_resolver,
    )

    assert result.source == "lookup"
    assert result.resolved is True
    assert result.record.project_id == "P7dR8mSH"
    assert result.record.slug == "fabric-api"
    assert calls["fallback"] == 1


@pytest.mark.smoke
def test_register_provider_revalidation_failure_sets_retrying_backoff() -> None:
    payload = register_provider_revalidation_failure(
        {"project_id": "P7dR8mSH", "slug": "fabric-api", "stale_revalidation_failures": "1"},
        now_epoch_ms=1_000,
    )

    assert payload["stale_revalidation_failures"] == "2"
    assert payload["lifecycle_state"] == "retrying"
    assert payload["next_retry_not_before_epoch_ms"] == "121000"
    assert payload["last_revalidation_failed_at_epoch_ms"] == "1000"


@pytest.mark.smoke
def test_register_provider_revalidation_failure_sets_invalidated_after_threshold() -> None:
    payload = register_provider_revalidation_failure(
        {"project_id": "P7dR8mSH", "slug": "fabric-api", "stale_revalidation_failures": "3"},
        now_epoch_ms=2_000,
    )

    assert payload["stale_revalidation_failures"] == "4"
    assert payload["lifecycle_state"] == "invalidated"


@pytest.mark.smoke
def test_register_provider_revalidation_failure_ignores_manual_override_field() -> None:
    payload = register_provider_revalidation_failure(
        {
            "project_id": "P7dR8mSH",
            "slug": "fabric-api",
            "manual_override": True,
            "stale_revalidation_failures": "1",
        },
        now_epoch_ms=2_000,
    )

    assert payload["lifecycle_state"] == "retrying"
    assert payload["stale_revalidation_failures"] == "2"


@pytest.mark.smoke
def test_register_provider_revalidation_success_resets_backoff_fields() -> None:
    payload = register_provider_revalidation_success(
        {
            "project_id": "P7dR8mSH",
            "slug": "fabric-api",
            "stale_revalidation_failures": "4",
            "lifecycle_state": "invalidated",
            "next_retry_not_before_epoch_ms": "999999",
            "last_revalidation_failed_at_epoch_ms": "888888",
        },
        now_epoch_ms=5_000,
    )

    assert payload["stale_revalidation_failures"] == "0"
    assert payload["lifecycle_state"] == "fresh"
    assert payload["next_retry_not_before_epoch_ms"] == "0"
    assert payload["last_revalidation_failed_at_epoch_ms"] == "0"
    assert payload["resolved_at_epoch_ms"] == "5000"


@pytest.mark.smoke
def test_cache_provider_metadata_record_always_writes_latest_auto_resolve_payload() -> None:
    index = _StubIndexManager(cached_provider={"manual_override": True, "project_id": "MANUAL1", "slug": "foo"})

    cache_provider_metadata_record(
        index,
        "C:/mods/fabric-api.jar",
        ProviderMetadataRecord.from_values(project_id="AUTO1", slug="fabric-api"),
        metadata_source="scan_detect",
    )

    assert len(index.cached_payloads) == 1
    assert index.cached_payloads[0]["project_id"] == "AUTO1"


@pytest.mark.smoke
def test_is_provider_revalidation_retry_due_follows_retry_window() -> None:
    raw = {"next_retry_not_before_epoch_ms": "2000"}

    assert is_provider_revalidation_retry_due(raw, now_epoch_ms=1_000) is False
    assert is_provider_revalidation_retry_due(raw, now_epoch_ms=2_000) is True


@pytest.mark.smoke
def test_compute_provider_revalidation_backoff_seconds_uses_exponential_growth_with_cap() -> None:
    assert compute_provider_revalidation_backoff_seconds(1) == 60
    assert compute_provider_revalidation_backoff_seconds(2) == 120
    assert compute_provider_revalidation_backoff_seconds(10) == 1800


@pytest.mark.smoke
def test_should_attempt_provider_revalidation_returns_false_when_retry_not_due() -> None:
    should_attempt, reason = should_attempt_provider_revalidation(
        {"next_retry_not_before_epoch_ms": "2000"},
        attempted_count=0,
        now_epoch_ms=1000,
    )

    assert should_attempt is False
    assert reason == "backoff"


@pytest.mark.smoke
def test_should_attempt_provider_revalidation_returns_false_when_batch_limit_reached() -> None:
    should_attempt, reason = should_attempt_provider_revalidation(
        {"next_retry_not_before_epoch_ms": "0"},
        attempted_count=PROVIDER_REVALIDATION_BATCH_MAX_PER_RUN,
        now_epoch_ms=1000,
    )

    assert should_attempt is False
    assert reason == "batch_limit"


@pytest.mark.smoke
def test_should_attempt_provider_revalidation_returns_true_when_due_and_within_batch() -> None:
    should_attempt, reason = should_attempt_provider_revalidation(
        {"next_retry_not_before_epoch_ms": "1000"},
        attempted_count=1,
        now_epoch_ms=1000,
    )

    assert should_attempt is True
    assert reason == "due"
