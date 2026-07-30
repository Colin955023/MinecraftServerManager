"""Metadata 提供者驗證服務。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ...models import OnlineModInfo
from ...utils import (
    recompute_adaptive_revalidation_batch_limit,
    resolve_revalidation_batch_limits,
)
from .. import (
    PROVIDER_LIFECYCLE_STALE,
    LocalProviderEnsureResult,
    ProviderMetadataRecord,
    ensure_local_mod_provider_record,
    should_attempt_provider_revalidation,
)


@dataclass(slots=True)
class ProviderRevalidationMetrics:
    """彙整 stale metadata 重查指標。"""

    configured_batch_base_limit: int
    configured_batch_min_limit: int
    configured_batch_max_limit: int
    adaptive_revalidation_batch_limit: int
    adaptive_enabled: bool
    failure_high_watermark: float
    failure_low_watermark: float
    latency_threshold_ms: float
    stale_count: int = 0
    retryable_count: int = 0
    attempted_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0
    backoff_deferred_count: int = 0
    batch_deferred_count: int = 0
    adaptive_adjustment_count: int = 0


@dataclass(slots=True)
class ProviderRevalidationOutcome:
    """單次 metadata 重查結果。"""

    ensured: LocalProviderEnsureResult
    fallback_project_info: OnlineModInfo | None
    skip_reason: str = ""


class ProviderMetadataRevalidationService:
    """封裝 stale provider metadata 的 TTL / backoff / adaptive batch 重查策略。"""

    def __init__(
        self,
        *,
        default_base_limit: int,
        batch_base_limit: int | None = None,
        batch_min_limit: int = 1,
        batch_max_limit: int | None = None,
        adaptive_enabled: bool = True,
        failure_high_watermark: float = 0.6,
        failure_low_watermark: float = 0.25,
        latency_threshold_ms: float = 800.0,
    ) -> None:
        (
            configured_batch_base_limit,
            configured_batch_min_limit,
            configured_batch_max_limit,
            adaptive_revalidation_batch_limit,
        ) = resolve_revalidation_batch_limits(
            default_base_limit=default_base_limit,
            batch_base_limit=batch_base_limit,
            batch_min_limit=batch_min_limit,
            batch_max_limit=batch_max_limit,
        )
        self.metrics = ProviderRevalidationMetrics(
            configured_batch_base_limit=configured_batch_base_limit,
            configured_batch_min_limit=configured_batch_min_limit,
            configured_batch_max_limit=configured_batch_max_limit,
            adaptive_revalidation_batch_limit=adaptive_revalidation_batch_limit,
            adaptive_enabled=adaptive_enabled,
            failure_high_watermark=failure_high_watermark,
            failure_low_watermark=failure_low_watermark,
            latency_threshold_ms=latency_threshold_ms,
        )

    def register_stale_provider(self) -> None:
        """記錄本輪遇到一筆 stale provider metadata。"""
        self.metrics.stale_count += 1

    def register_retryable_candidate(self) -> None:
        """記錄本輪新增一筆 retryable stale candidate。"""
        self.metrics.retryable_count += 1

    def revalidate(
        self,
        *,
        local_mod: Any,
        existing_project_id: str,
        existing_project_slug: str,
        identifier_resolver,
        fallback_resolver,
    ) -> ProviderRevalidationOutcome:
        """
        執行單筆 stale provider metadata 重查。

        Args:
            local_mod: 目前正在重查的本地模組物件。
            existing_project_id: 既有的 provider project id。
            existing_project_slug: 既有的 provider slug。
            identifier_resolver: 依 identifier 解析 provider metadata 的函式。
            fallback_resolver: identifier 失敗時的 fallback 解析函式。

        Returns:
            本次重查的結果，包含 ensure 結果、fallback 專案資訊與略過原因。
        """
        should_attempt, skip_reason = should_attempt_provider_revalidation(
            {
                "next_retry_not_before_epoch_ms": str(
                    getattr(local_mod, "next_retry_not_before_epoch_ms", "") or ""
                ).strip()
            },
            attempted_count=self.metrics.attempted_count,
            max_attempts=self.metrics.adaptive_revalidation_batch_limit,
        )
        if not should_attempt:
            if skip_reason == "backoff":
                self.metrics.backoff_deferred_count += 1
            elif skip_reason == "batch_limit":
                self.metrics.batch_deferred_count += 1
            return ProviderRevalidationOutcome(
                ensured=LocalProviderEnsureResult(
                    record=ProviderMetadataRecord.from_values(
                        project_name=str(getattr(local_mod, "name", "") or "").strip()
                    ),
                    source="stale_revalidation_deferred",
                    resolved=False,
                    lifecycle_state=str(getattr(local_mod, "provider_lifecycle_state", "") or "").strip().lower()
                    or PROVIDER_LIFECYCLE_STALE,
                ),
                fallback_project_info=None,
                skip_reason=skip_reason,
            )

        self.metrics.attempted_count += 1
        started_at = time.perf_counter()
        ensured = ensure_local_mod_provider_record(
            platform_id=existing_project_id,
            platform_slug=existing_project_slug,
            project_name=str(getattr(local_mod, "name", "") or "").strip(),
            identifier_resolver=identifier_resolver,
            fallback_resolver=fallback_resolver,
        )
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        self.metrics.total_latency_ms += elapsed_ms
        if ensured.record.project_id:
            self.metrics.success_count += 1
        else:
            self.metrics.failure_count += 1
        self._recompute_adaptive_batch_limit()
        return ProviderRevalidationOutcome(
            ensured=ensured,
            fallback_project_info=None,
            skip_reason="",
        )

    def _recompute_adaptive_batch_limit(self) -> None:
        next_limit = recompute_adaptive_revalidation_batch_limit(
            current_limit=self.metrics.adaptive_revalidation_batch_limit,
            attempted_count=self.metrics.attempted_count,
            failure_count=self.metrics.failure_count,
            total_latency_ms=self.metrics.total_latency_ms,
            adaptive_enabled=self.metrics.adaptive_enabled,
            failure_high_watermark=self.metrics.failure_high_watermark,
            failure_low_watermark=self.metrics.failure_low_watermark,
            latency_threshold_ms=self.metrics.latency_threshold_ms,
            min_limit=self.metrics.configured_batch_min_limit,
            max_limit=self.metrics.configured_batch_max_limit,
        )
        if next_limit != self.metrics.adaptive_revalidation_batch_limit:
            self.metrics.adaptive_revalidation_batch_limit = next_limit
            self.metrics.adaptive_adjustment_count += 1

    def build_summary_notes(self) -> list[str]:
        """
        輸出 stale metadata 重查摘要。

        Returns:
            可直接顯示於 UI 或日誌的摘要文字清單。
        """
        notes: list[str] = []
        if self.metrics.stale_count > 0:
            notes.append(
                f"其中 {self.metrics.stale_count} 個 provider metadata 已超過 freshness TTL，已改為重新識別而非直接沿用舊值。"
            )
        if self.metrics.retryable_count > 0:
            notes.append(
                f"其中 {self.metrics.retryable_count} 個過期 metadata 重查失敗，已標記為可重試並暫停自動更新。"
            )
        if self.metrics.stale_count > 0 and self.metrics.adaptive_enabled:
            notes.append(
                f"stale metadata 重查批次策略：基準 {self.metrics.configured_batch_base_limit}、區間 "
                f"{self.metrics.configured_batch_min_limit}-{self.metrics.configured_batch_max_limit}，"
                f"本輪最終上限 {self.metrics.adaptive_revalidation_batch_limit}。"
            )
        if self.metrics.attempted_count > 0:
            average_latency_ms = self.metrics.total_latency_ms / max(1, self.metrics.attempted_count)
            success_rate = self.metrics.success_count / max(1, self.metrics.attempted_count)
            notes.append(f"本輪實際執行 {self.metrics.attempted_count} 個 stale metadata 重查。")
            notes.append(
                f"重查觀測摘要：成功率 {success_rate:.0%}、平均延遲 {average_latency_ms:.0f}ms"
                + (
                    f"、自適應調整 {self.metrics.adaptive_adjustment_count} 次。"
                    if self.metrics.adaptive_enabled
                    else "。"
                )
            )
        if self.metrics.backoff_deferred_count > 0:
            notes.append(f"另有 {self.metrics.backoff_deferred_count} 個尚在退避視窗內，已延後至到期後自動重查。")
        if self.metrics.batch_deferred_count > 0:
            notes.append(
                f"另有 {self.metrics.batch_deferred_count} 個因批次上限（{self.metrics.adaptive_revalidation_batch_limit}）"
                "延後至後續檢查自動重查。"
            )
        return notes


__all__ = [
    "ProviderMetadataRevalidationService",
    "ProviderRevalidationMetrics",
    "ProviderRevalidationOutcome",
]
