from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx

import src.utils.network_utils.http_client as http_client_module
from src.utils import HTTPClient


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

    assert HTTPClient.download_file("https://example.com/server.jar", str(target)) is True
    assert target.read_bytes() == b"new-bytes"


def test_download_file_reports_insufficient_disk_space(tmp_path, monkeypatch) -> None:
    target = tmp_path / "server.jar"
    failure_messages: list[str] = []
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

    assert (
        HTTPClient.download_file(
            "https://example.com/server.jar",
            str(target),
            failure_message_callback=failure_messages.append,
        )
        is False
    )
    assert failure_messages and "磁碟空間不足" in failure_messages[0]
    assert not target.exists()
    assert list(tmp_path.glob("*.part")) == []


def test_download_file_reports_timeout_reason(tmp_path, monkeypatch) -> None:
    target = tmp_path / "server.jar"
    failure_messages: list[str] = []

    def _timeout(*_args, **_kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(HTTPClient, "_open_stream", classmethod(lambda _cls, *a, **kw: _timeout(*a, **kw)))

    assert (
        HTTPClient.download_file(
            "https://example.com/server.jar",
            str(target),
            failure_message_callback=failure_messages.append,
        )
        is False
    )
    assert failure_messages and "逾時" in failure_messages[0]


def test_download_file_reports_invalid_url_reason(tmp_path) -> None:
    target = tmp_path / "server.jar"
    failure_messages: list[str] = []

    assert (
        HTTPClient.download_file(
            "not-a-url",
            str(target),
            failure_message_callback=failure_messages.append,
        )
        is False
    )
    assert failure_messages == ["URL 參數無效或不符合 HTTPS 安全策略"]


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

    assert HTTPClient.download_file("https://example.com/server.jar", str(target)) is False
    assert target.read_bytes() == b"old-bytes"


def test_http_client_rejects_insecure_and_private_urls() -> None:
    assert HTTPClient._is_valid_url("http://example.com/file") is False
    assert HTTPClient._is_valid_url("https://localhost/file") is False
    assert HTTPClient._is_valid_url("https://127.0.0.1/file") is False
    assert HTTPClient._is_valid_url("https://192.168.1.1/file") is False
    assert HTTPClient._is_valid_url("https://example.com/file") is True


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
