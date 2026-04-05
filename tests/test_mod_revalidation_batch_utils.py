from __future__ import annotations

from src.utils import (
    recompute_adaptive_revalidation_batch_limit,
    resolve_revalidation_batch_limits,
)


def test_resolve_revalidation_batch_limits_handles_defaults() -> None:
    configured_base, configured_min, configured_max, adaptive_limit = resolve_revalidation_batch_limits(
        default_base_limit=8,
        batch_base_limit=None,
        batch_min_limit=1,
        batch_max_limit=None,
    )

    assert configured_base == 8
    assert configured_min == 1
    assert configured_max == 8
    assert adaptive_limit == 8


def test_resolve_revalidation_batch_limits_clamps_and_expands_max() -> None:
    configured_base, configured_min, configured_max, adaptive_limit = resolve_revalidation_batch_limits(
        default_base_limit=8,
        batch_base_limit=6,
        batch_min_limit=10,
        batch_max_limit=7,
    )

    assert configured_base == 6
    assert configured_min == 10
    assert configured_max == 7
    assert adaptive_limit == 7


def test_recompute_adaptive_revalidation_batch_limit_shrinks_on_high_failure() -> None:
    next_limit = recompute_adaptive_revalidation_batch_limit(
        current_limit=8,
        attempted_count=4,
        failure_count=3,
        total_latency_ms=1000.0,
        adaptive_enabled=True,
        failure_high_watermark=0.6,
        failure_low_watermark=0.25,
        latency_threshold_ms=800.0,
        min_limit=2,
        max_limit=12,
    )

    assert next_limit == 6


def test_recompute_adaptive_revalidation_batch_limit_grows_on_stable_fast_result() -> None:
    next_limit = recompute_adaptive_revalidation_batch_limit(
        current_limit=8,
        attempted_count=4,
        failure_count=0,
        total_latency_ms=800.0,
        adaptive_enabled=True,
        failure_high_watermark=0.6,
        failure_low_watermark=0.25,
        latency_threshold_ms=800.0,
        min_limit=1,
        max_limit=12,
    )

    assert next_limit == 11


def test_recompute_adaptive_revalidation_batch_limit_keeps_when_sample_too_small() -> None:
    next_limit = recompute_adaptive_revalidation_batch_limit(
        current_limit=8,
        attempted_count=2,
        failure_count=0,
        total_latency_ms=50.0,
        adaptive_enabled=True,
        failure_high_watermark=0.6,
        failure_low_watermark=0.25,
        latency_threshold_ms=800.0,
        min_limit=1,
        max_limit=12,
    )

    assert next_limit == 8
