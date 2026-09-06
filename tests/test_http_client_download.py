from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import src.utils.network_utils.http_client as http_client_module
from src.utils import HTTPClient

# RFC 5737 TEST-NET-3：永久保留給文件／測試，不代表任何可連線的公網主機
_DOCUMENTATION_IP = "203.0.113.10"


class _SyntheticPublicAddress:
    is_global = True

    def __init__(self, value: str) -> None:
        self._value = value

    def __str__(self) -> str:
        return self._value


def _allow_documentation_ip_as_public(monkeypatch) -> None:
    real_ip_address = http_client_module.ipaddress.ip_address

    def _ip_address(value):
        if str(value) == _DOCUMENTATION_IP:
            return _SyntheticPublicAddress(_DOCUMENTATION_IP)
        return real_ip_address(value)

    monkeypatch.setattr(http_client_module.ipaddress, "ip_address", _ip_address)


def _response(payload: bytes, *, url: str = "https://example.com/server.jar") -> httpx.Response:
    request = httpx.Request("GET", url)
    return httpx.Response(
        200,
        headers={"Content-Length": str(len(payload))},
        content=payload,
        request=request,
    )


def test_download_file_without_expected_hash_skips_hashing(tmp_path, monkeypatch) -> None:
    target = tmp_path / "server.jar"
    monkeypatch.setattr(
        HTTPClient,
        "_open_stream",
        classmethod(lambda _cls, *_args, **_kwargs: _response(b"new-bytes")),
    )

    def _unexpected_hash(_algorithm: str):
        raise AssertionError("hashlib.new should not be called without an expected hash")

    monkeypatch.setattr(http_client_module.hashlib, "new", _unexpected_hash)

    result = HTTPClient.download_file("https://example.com/server.jar", str(target))
    assert result.success is True
    assert result.message == ""
    assert target.read_bytes() == b"new-bytes"


def test_download_file_reports_insufficient_disk_space(tmp_path, monkeypatch) -> None:
    target = tmp_path / "server.jar"
    monkeypatch.setattr(
        HTTPClient,
        "_open_stream",
        classmethod(lambda _cls, *_args, **_kwargs: _response(b"new-bytes")),
    )
    monkeypatch.setattr(
        http_client_module.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=10, used=9, free=1),
    )

    result = HTTPClient.download_file("https://example.com/server.jar", str(target))
    assert result.success is False
    assert "磁碟空間不足" in result.message
    assert not target.exists()
    assert list(tmp_path.glob("*.part")) == []


@pytest.mark.parametrize("content_length", [None, "1"])
def test_download_file_enforces_actual_size_limit_without_trusting_content_length(
    tmp_path: Path,
    monkeypatch,
    content_length: str | None,
) -> None:
    target = tmp_path / "server.jar"
    headers = {} if content_length is None else {"Content-Length": content_length}
    request = httpx.Request("GET", "https://example.com/server.jar")
    response = httpx.Response(200, headers=headers, content=b"123456", request=request)
    monkeypatch.setattr(
        HTTPClient,
        "_open_stream",
        classmethod(lambda _cls, *_args, **_kwargs: response),
    )

    result = HTTPClient.download_file("https://example.com/server.jar", str(target), max_bytes=5)

    assert result.success is False
    assert "大小上限" in result.message
    assert not target.exists()
    assert list(tmp_path.glob("*.part")) == []


def test_download_file_accepts_payload_at_size_limit_without_content_length(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "server.jar"
    request = httpx.Request("GET", "https://example.com/server.jar")
    response = httpx.Response(200, content=b"12345", request=request)
    monkeypatch.setattr(
        HTTPClient,
        "_open_stream",
        classmethod(lambda _cls, *_args, **_kwargs: response),
    )

    result = HTTPClient.download_file("https://example.com/server.jar", str(target), max_bytes=5)

    assert result.success is True
    assert target.read_bytes() == b"12345"


def test_download_file_cleans_temp_file_when_progress_callback_raises(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "server.jar"
    monkeypatch.setattr(
        HTTPClient,
        "_open_stream",
        classmethod(lambda _cls, *_args, **_kwargs: _response(b"new-bytes")),
    )

    def fail_progress(_downloaded: int, _total: int) -> None:
        raise RuntimeError("progress callback failed")

    with pytest.raises(RuntimeError, match="progress callback failed"):
        HTTPClient.download_file(
            "https://example.com/server.jar",
            str(target),
            progress_callback=fail_progress,
        )

    assert not target.exists()
    assert list(tmp_path.glob("*.part")) == []


def test_download_file_reports_timeout_reason(tmp_path, monkeypatch) -> None:
    target = tmp_path / "server.jar"

    def _timeout(*_args, **_kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(HTTPClient, "_open_stream", classmethod(lambda _cls, *a, **kw: _timeout(*a, **kw)))
    monkeypatch.setattr(http_client_module.time, "sleep", lambda _delay: None)

    result = HTTPClient.download_file("https://example.com/server.jar", str(target))
    assert result.success is False
    assert "逾時" in result.message


def test_download_file_owns_retry_budget_without_nested_stream_retries(tmp_path, monkeypatch) -> None:
    target = tmp_path / "server.jar"
    calls: list[bool] = []

    def _timeout(_cls, *_args, **kwargs):
        retry = kwargs.get("retry")
        assert isinstance(retry, bool)
        calls.append(retry)
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(HTTPClient, "_open_stream", classmethod(_timeout))
    monkeypatch.setattr(http_client_module.time, "sleep", lambda _delay: None)

    result = HTTPClient.download_file("https://example.com/server.jar", str(target))

    assert result.success is False
    assert calls == [False] * (HTTPClient.RETRY_TOTAL + 1)
    assert list(tmp_path.glob("*.part")) == []


def test_download_file_retries_retryable_http_status_with_single_budget(tmp_path, monkeypatch) -> None:
    target = tmp_path / "server.jar"
    request = httpx.Request("GET", "https://example.com/server.jar")
    responses = iter(
        [
            httpx.Response(503, request=request),
            _response(b"new-bytes"),
        ]
    )
    retry_flags: list[bool] = []

    def _open(_cls, *_args, **kwargs):
        retry = kwargs.get("retry")
        assert isinstance(retry, bool)
        retry_flags.append(retry)
        return next(responses)

    monkeypatch.setattr(HTTPClient, "_open_stream", classmethod(_open))
    monkeypatch.setattr(http_client_module.time, "sleep", lambda _delay: None)

    result = HTTPClient.download_file("https://example.com/server.jar", str(target))

    assert result.success is True
    assert target.read_bytes() == b"new-bytes"
    assert retry_flags == [False, False]


def test_download_file_fails_closed_when_secure_temp_creation_fails(tmp_path, monkeypatch) -> None:
    target = tmp_path / "server.jar"

    def fail_temp_creation(*_args, **_kwargs):
        raise OSError("temp unavailable")

    monkeypatch.setattr(http_client_module.tempfile, "NamedTemporaryFile", fail_temp_creation)
    monkeypatch.setattr(
        HTTPClient,
        "_open_stream",
        classmethod(lambda _cls, *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不應開始下載"))),
    )

    result = HTTPClient.download_file("https://example.com/server.jar", str(target))

    assert result.success is False
    assert result.message == "無法建立安全下載暫存檔"
    assert not target.exists()
    assert list(tmp_path.glob("*.part")) == []


def test_download_file_reports_invalid_url_reason(tmp_path) -> None:
    target = tmp_path / "server.jar"
    result = HTTPClient.download_file("not-a-url", str(target))
    assert result.success is False
    assert result.message == "URL 參數無效或不符合 HTTPS 安全策略"


def test_download_file_keeps_existing_target_when_replace_fails(tmp_path, monkeypatch) -> None:
    target = tmp_path / "server.jar"
    target.write_bytes(b"old-bytes")
    monkeypatch.setattr(
        HTTPClient,
        "_open_stream",
        classmethod(lambda _cls, *_args, **_kwargs: _response(b"new-bytes")),
    )

    def _fail_replace(_self: Path, _target: Path) -> Path:
        raise OSError("target locked")

    monkeypatch.setattr(Path, "replace", _fail_replace)

    result = HTTPClient.download_file("https://example.com/server.jar", str(target))
    assert result.success is False
    assert target.read_bytes() == b"old-bytes"


def test_http_client_rejects_insecure_and_private_urls_without_dns_lookup(monkeypatch) -> None:
    def _unexpected_dns(*_args, **_kwargs):
        raise AssertionError("靜態 URL policy 不應執行 DNS")

    monkeypatch.setattr(http_client_module.socket, "getaddrinfo", _unexpected_dns)

    assert HTTPClient._is_valid_url("http://example.com/file") is False
    assert HTTPClient._is_valid_url("https://localhost/file") is False
    assert HTTPClient._is_valid_url("https://127.0.0.1/file") is False
    assert HTTPClient._is_valid_url("https://192.168.1.1/file") is False
    assert HTTPClient._is_valid_url("https://example.com/file") is True


def test_http_client_rejects_hostname_resolving_to_private_address(monkeypatch) -> None:
    monkeypatch.setattr(
        http_client_module.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("192.168.1.10", 443))],
    )

    with pytest.raises(http_client_module.NetworkSecurityError, match="非公開位址"):
        HTTPClient._validated_url_and_address("https://download.example/file")


def test_http_client_accepts_hostname_resolving_only_to_public_addresses(monkeypatch) -> None:
    _allow_documentation_ip_as_public(monkeypatch)
    monkeypatch.setattr(
        http_client_module.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", (_DOCUMENTATION_IP, 443))],
    )

    parsed, pinned_address = HTTPClient._validated_url_and_address("https://download.example/file")

    assert str(parsed) == "https://download.example/file"
    assert pinned_address == _DOCUMENTATION_IP


def test_http_transport_uses_validated_ip_with_original_host_and_sni(monkeypatch) -> None:
    _allow_documentation_ip_as_public(monkeypatch)
    monkeypatch.setattr(
        http_client_module.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", (_DOCUMENTATION_IP, 443))],
    )
    captured: dict[str, httpx.Request] = {}

    def _fake_handle(_transport, request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, content=b"ok", request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _fake_handle)
    transport = http_client_module._PinnedHTTPTransport(verify=False, trust_env=False)
    request = httpx.Request(
        "GET",
        "https://download.example/file",
        extensions={http_client_module._PINNED_ADDRESS_EXTENSION: _DOCUMENTATION_IP},
    )

    response = transport.handle_request(request)

    assert str(captured["request"].url) == f"https://{_DOCUMENTATION_IP}/file"
    assert captured["request"].headers["Host"] == "download.example"
    assert captured["request"].extensions["sni_hostname"] == "download.example"
    assert response.request is request
    response.close()
    transport.close()


def test_http_transport_isolates_connection_pools_by_original_origin(monkeypatch) -> None:
    _allow_documentation_ip_as_public(monkeypatch)
    handled: list[tuple[int, str, str, str]] = []

    def _fake_handle(inner_transport, request: httpx.Request) -> httpx.Response:
        handled.append(
            (
                id(inner_transport),
                str(request.url),
                request.headers["Host"],
                str(request.extensions["sni_hostname"]),
            )
        )
        return httpx.Response(200, content=b"ok", request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _fake_handle)
    transport = http_client_module._PinnedHTTPTransport(verify=False, trust_env=False, http2=True)

    requests = [
        httpx.Request(
            "GET",
            "https://a.example/file",
            extensions={http_client_module._PINNED_ADDRESS_EXTENSION: _DOCUMENTATION_IP},
        ),
        httpx.Request(
            "GET",
            "https://b.example/file",
            extensions={http_client_module._PINNED_ADDRESS_EXTENSION: _DOCUMENTATION_IP},
        ),
        httpx.Request(
            "GET",
            "https://a.example/other",
            extensions={http_client_module._PINNED_ADDRESS_EXTENSION: _DOCUMENTATION_IP},
        ),
    ]

    responses = [transport.handle_request(request) for request in requests]
    try:
        assert handled[0][0] == handled[2][0]
        assert handled[0][0] != handled[1][0]
        assert [entry[1] for entry in handled] == [
            f"https://{_DOCUMENTATION_IP}/file",
            f"https://{_DOCUMENTATION_IP}/file",
            f"https://{_DOCUMENTATION_IP}/other",
        ]
        assert [entry[2] for entry in handled] == ["a.example", "b.example", "a.example"]
        assert [entry[3] for entry in handled] == ["a.example", "b.example", "a.example"]
    finally:
        for response in responses:
            response.close()
        transport.close()


def test_fetch_bytes_resolves_hostname_once_per_request_attempt(monkeypatch) -> None:
    _allow_documentation_ip_as_public(monkeypatch)
    dns_calls = 0

    def _fake_dns(*_args, **_kwargs):
        nonlocal dns_calls
        dns_calls += 1
        return [(2, 1, 6, "", (_DOCUMENTATION_IP, 443))]

    def _fake_handle(_transport, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"ok", request=request)

    HTTPClient.close()
    monkeypatch.setattr(http_client_module.socket, "getaddrinfo", _fake_dns)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _fake_handle)
    try:
        assert HTTPClient.fetch_bytes("https://download.example/file") == b"ok"
        assert dns_calls == 1
    finally:
        HTTPClient.close()


def test_cross_origin_redirect_strips_sensitive_headers() -> None:
    headers = {
        "Authorization": "Bearer secret",
        "Cookie": "session=secret",
        "Proxy-Authorization": "proxy-secret",
        "Accept": "application/json",
    }
    result = HTTPClient._redirect_headers(
        headers,
        "https://api.example.com/file",
        "https://cdn.example.net/file",
    )
    assert result == {"Accept": "application/json"}


def test_safe_url_for_log_removes_query_fragment_and_credentials() -> None:
    safe = HTTPClient._safe_url_for_log(
        "https://user:secret@example.com/path/file?token=secret#fragment"  # pragma: allowlist secret
    )
    assert safe == "https://example.com/path/file"
