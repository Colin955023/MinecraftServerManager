from __future__ import annotations

import httpx
import pytest

import src.utils.network_utils.http_client as http_client_module
from src.utils import HTTPClient

_TEST_URL = "https://example.com/data.json"


def _response(status_code: int, *, content: bytes = b"", retry_after: str | None = None) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after is not None else None
    return httpx.Response(
        status_code,
        request=httpx.Request("GET", _TEST_URL),
        headers=headers,
        content=content,
    )


def test_fetch_json_response_retries_retryable_status_through_shared_state_machine(monkeypatch) -> None:
    responses = [
        _response(503, retry_after="0"),
        _response(200, content=b'{"ok":true}'),
    ]
    calls = 0

    def _send(_cls, *_args, **_kwargs):
        nonlocal calls
        calls += 1
        return responses.pop(0)

    monkeypatch.setattr(HTTPClient, "_is_valid_url", classmethod(lambda _cls, _url: True))
    monkeypatch.setattr(HTTPClient, "_send_stream_once", classmethod(_send))
    monkeypatch.setattr(http_client_module.time, "sleep", lambda _seconds: None)

    result = HTTPClient.fetch_json_response(_TEST_URL)

    assert calls == 2
    assert result.status_code == 200
    assert result.payload == {"ok": True}
    assert result.error_kind == ""


def test_fetch_json_response_retries_transport_error_raised_while_consuming_response(monkeypatch) -> None:
    calls = 0
    reads = 0

    def _send(_cls, *_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _response(200, content=b'{"ok":true}')

    def _read_limited(_cls, response: httpx.Response, _max_bytes: int) -> bytes:
        nonlocal reads
        reads += 1
        if reads == 1:
            raise httpx.ReadTimeout("stream timeout", request=response.request)
        return b'{"ok":true}'

    monkeypatch.setattr(HTTPClient, "_is_valid_url", classmethod(lambda _cls, _url: True))
    monkeypatch.setattr(HTTPClient, "_send_stream_once", classmethod(_send))
    monkeypatch.setattr(HTTPClient, "_read_limited", classmethod(_read_limited))
    monkeypatch.setattr(http_client_module.time, "sleep", lambda _seconds: None)

    result = HTTPClient.fetch_json_response(_TEST_URL)

    assert calls == 2
    assert reads == 2
    assert result.status_code == 200
    assert result.payload == {"ok": True}


def test_suppressed_retry_status_returns_without_consuming_retry_budget(monkeypatch) -> None:
    calls = 0

    def _send(_cls, *_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _response(429, retry_after="0")

    monkeypatch.setattr(HTTPClient, "_send_stream_once", classmethod(_send))
    monkeypatch.setattr(http_client_module.time, "sleep", lambda _seconds: None)

    result = HTTPClient._read_content_with_retry(
        "GET",
        _TEST_URL,
        timeout=10,
        max_bytes=1024,
        suppress_status_codes={429},
    )

    assert result is None
    assert calls == 1


def test_non_idempotent_post_does_not_retry_retryable_status(monkeypatch) -> None:
    calls = 0

    def _send(_cls, *_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _response(503, retry_after="0")

    monkeypatch.setattr(HTTPClient, "_send_stream_once", classmethod(_send))
    monkeypatch.setattr(http_client_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        HTTPClient._read_content_with_retry("POST", _TEST_URL, timeout=10, max_bytes=1024)

    assert exc_info.value.response.status_code == 503
    assert calls == 1
