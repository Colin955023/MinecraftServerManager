from __future__ import annotations

import src.utils.network_utils.request_retry_utils as retry_utils


def test_chunk_sequence_splits_items_into_bounded_chunks() -> None:
    assert retry_utils.chunk_sequence(["a", "b", "c", "d"], 2) == [["a", "b"], ["c", "d"]]
    assert retry_utils.chunk_sequence(["a", "b", "c"], 0) == [["a"], ["b"], ["c"]]


def test_execute_resilient_single_request_retries_until_success(monkeypatch) -> None:
    delays: list[float] = []
    monkeypatch.setattr(retry_utils, "sleep_if_needed", lambda delay_seconds: delays.append(delay_seconds))

    responses = iter(["bad", "bad", "good"])

    def request_once() -> str:
        return next(responses)

    result = retry_utils.execute_resilient_single_request(
        request_once=request_once,
        is_success=lambda value: value == "good",
        max_attempts=3,
    )

    assert result == ("good", True, 3)
    assert delays == [0.03, 0.25, 0.03, 0.5]


def test_execute_resilient_batch_requests_splits_failed_chunks(monkeypatch) -> None:
    monkeypatch.setattr(retry_utils, "sleep_if_needed", lambda _delay_seconds: None)

    def request_batch(chunk: list[str]) -> dict[str, str] | None:
        if len(chunk) > 1:
            return None
        return {chunk[0]: chunk[0]}

    payload, stats = retry_utils.execute_resilient_batch_requests(
        ["a", "b"],
        batch_size=2,
        max_attempts=1,
        request_batch=request_batch,
    )

    assert payload == {"a": "a", "b": "b"}
    assert stats == {
        "requested_items": 2,
        "requested_chunks": 1,
        "retried_chunks": 0,
        "split_chunks": 1,
        "failed_items": 0,
    }
