"""請求重試與批次拆分工具。"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


def chunk_sequence(values: list[str], chunk_size: int) -> list[list[str]]:
    """將序列切成固定大小的區塊。

    Args:
        values: 要拆分的字串清單。
        chunk_size: 每個區塊的大小。

    Returns:
        依 chunk_size 拆分後的區塊清單。
    """
    normalized_size = max(1, int(chunk_size))
    return [values[index : index + normalized_size] for index in range(0, len(values), normalized_size)]


def sleep_if_needed(delay_seconds: float) -> None:
    """在需要時暫停執行。

    Args:
        delay_seconds: 要暫停的秒數。
    """
    if delay_seconds <= 0:
        return
    time.sleep(delay_seconds)


def execute_resilient_single_request(
    *,
    request_once: Callable[[], Any],
    is_success: Callable[[Any], bool],
    max_attempts: int,
    throttle_seconds: float = 0.03,
    retry_backoff_base_seconds: float = 0.25,
    retry_backoff_max_seconds: float = 1.5,
) -> tuple[Any, bool, int]:
    """以退避與節流重試單一請求。

    Args:
        request_once: 單次請求函式。
        is_success: 判斷回應是否成功的函式。
        max_attempts: 最大嘗試次數。
        throttle_seconds: 每次重試前的節流秒數。
        retry_backoff_base_seconds: 指數退避的基準秒數。
        retry_backoff_max_seconds: 指數退避的上限秒數。

    Returns:
        三元組 (最後回應, 是否成功, 嘗試次數)。
    """
    attempts = max(1, int(max_attempts))
    last_response: Any = None
    for attempt_index in range(attempts):
        if attempt_index > 0:
            backoff_seconds = min(
                max(0.0, float(retry_backoff_max_seconds)),
                max(0.0, float(retry_backoff_base_seconds)) * 2 ** (attempt_index - 1),
            )
            sleep_if_needed(backoff_seconds)
        last_response = request_once()
        if is_success(last_response):
            return (last_response, True, attempt_index + 1)
        if attempt_index + 1 < attempts:
            sleep_if_needed(max(0.0, float(throttle_seconds)))
    return (last_response, False, attempts)


def execute_resilient_batch_requests(
    items: list[str],
    *,
    batch_size: int,
    max_attempts: int,
    request_batch: Callable[[list[str]], dict[str, Any] | None],
    throttle_seconds: float = 0.03,
    retry_backoff_base_seconds: float = 0.25,
    retry_backoff_max_seconds: float = 1.5,
) -> tuple[dict[str, Any], dict[str, int]]:
    """以分塊、重試與必要時二分拆解的方式執行批次請求。

    Args:
        items: 要處理的項目清單。
        batch_size: 每批請求的項目數。
        max_attempts: 每個批次的最大嘗試次數。
        request_batch: 處理單一批次的函式。
        throttle_seconds: 每次請求之間的節流秒數。
        retry_backoff_base_seconds: 指數退避的基準秒數。
        retry_backoff_max_seconds: 指數退避的上限秒數。

    Returns:
        合併後的 payload 與統計資料。
    """
    pending_chunks = chunk_sequence(list(items), batch_size)
    stats = {
        "requested_items": len(items),
        "requested_chunks": len(pending_chunks),
        "retried_chunks": 0,
        "split_chunks": 0,
        "failed_items": 0,
    }
    merged_payload: dict[str, Any] = {}
    while pending_chunks:
        chunk = pending_chunks.pop(0)
        chunk_payload: dict[str, Any] | None = None
        attempts = max(1, int(max_attempts))
        for attempt_index in range(attempts):
            if attempt_index > 0:
                stats["retried_chunks"] += 1
                backoff_seconds = min(
                    max(0.0, float(retry_backoff_max_seconds)),
                    max(0.0, float(retry_backoff_base_seconds)) * 2 ** (attempt_index - 1),
                )
                sleep_if_needed(backoff_seconds)
            chunk_payload = request_batch(chunk)
            if chunk_payload is not None:
                break
            if attempt_index + 1 < attempts:
                sleep_if_needed(max(0.0, float(throttle_seconds)))
        if chunk_payload is not None:
            merged_payload.update(chunk_payload)
            if pending_chunks:
                sleep_if_needed(max(0.0, float(throttle_seconds)))
            continue
        if len(chunk) > 1:
            split_mid = len(chunk) // 2
            left = chunk[:split_mid]
            right = chunk[split_mid:]
            if right:
                pending_chunks.insert(0, right)
            if left:
                pending_chunks.insert(0, left)
            stats["split_chunks"] += 1
            if pending_chunks:
                sleep_if_needed(max(0.0, float(throttle_seconds)))
            continue
        stats["failed_items"] += 1
        if pending_chunks:
            sleep_if_needed(max(0.0, float(throttle_seconds)))
    return (merged_payload, stats)


__all__ = [
    "chunk_sequence",
    "execute_resilient_batch_requests",
    "execute_resilient_single_request",
    "sleep_if_needed",
]
