"""stale metadata 重查批次策略工具。"""

from __future__ import annotations


def resolve_revalidation_batch_limits(
    *,
    default_base_limit: int,
    batch_base_limit: int | None,
    batch_min_limit: int,
    batch_max_limit: int | None,
) -> tuple[int, int, int, int]:
    """計算重查批次策略的基準/最小/最大/初始上限。

    Args:
        default_base_limit: 預設的基準批次上限。
        batch_base_limit: 使用者設定的基準批次上限。
        batch_min_limit: 允許的最小批次上限。
        batch_max_limit: 允許的最大批次上限。

    Returns:
        `(基準上限, 最小上限, 最大上限, 初始自適應上限)`。
    """

    configured_batch_base_limit = max(
        1,
        int(default_base_limit if batch_base_limit is None else batch_base_limit),
    )
    configured_batch_min_limit = max(1, int(batch_min_limit))
    configured_batch_max_limit = (
        configured_batch_base_limit
        if batch_max_limit is None
        else max(configured_batch_base_limit, int(batch_max_limit))
    )
    adaptive_revalidation_batch_limit = min(
        configured_batch_max_limit,
        max(configured_batch_min_limit, configured_batch_base_limit),
    )
    return (
        configured_batch_base_limit,
        configured_batch_min_limit,
        configured_batch_max_limit,
        adaptive_revalidation_batch_limit,
    )


def recompute_adaptive_revalidation_batch_limit(
    *,
    current_limit: int,
    attempted_count: int,
    failure_count: int,
    total_latency_ms: float,
    adaptive_enabled: bool,
    failure_high_watermark: float,
    failure_low_watermark: float,
    latency_threshold_ms: float,
    min_limit: int,
    max_limit: int,
) -> int:
    """依重查結果動態調整下一輪批次上限。

    Args:
        current_limit: 目前的批次上限。
        attempted_count: 已嘗試處理的數量。
        failure_count: 失敗數量。
        total_latency_ms: 累積延遲毫秒數。
        adaptive_enabled: 是否啟用自適應調整。
        failure_high_watermark: 失敗率升高門檻。
        failure_low_watermark: 失敗率降低門檻。
        latency_threshold_ms: 延遲門檻毫秒數。
        min_limit: 最小批次上限。
        max_limit: 最大批次上限。

    Returns:
        調整後的下一輪批次上限。
    """

    if not adaptive_enabled or attempted_count < 3:
        return current_limit

    average_latency_ms = total_latency_ms / max(1, attempted_count)
    failure_rate = failure_count / max(1, attempted_count)
    next_limit = current_limit

    if failure_rate >= max(0.0, float(failure_high_watermark)) or average_latency_ms >= max(
        1.0, float(latency_threshold_ms)
    ):
        shrink_limit = max(min_limit, int(current_limit * 0.75))
        if shrink_limit == current_limit and current_limit > min_limit:
            shrink_limit -= 1
        next_limit = shrink_limit
    elif (
        failure_rate <= max(0.0, float(failure_low_watermark))
        and average_latency_ms <= max(1.0, float(latency_threshold_ms)) * 0.6
    ):
        next_limit = min(max_limit, int(current_limit * 1.25) + 1)

    return next_limit
