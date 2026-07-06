from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import src.utils.network_utils.http_utils as http_utils_module
from src.utils import HTTPUtils


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        for index in range(0, len(self._payload), chunk_size):
            yield self._payload[index : index + chunk_size]


class _FakeSession:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def get(self, *_args, **_kwargs) -> _FakeResponse:
        return _FakeResponse(self.payload)


class _TimeoutSession:
    def get(self, *_args, **_kwargs):
        raise http_utils_module.requests.exceptions.Timeout("timed out")


def test_download_file_without_expected_hash_skips_hashing(tmp_path, monkeypatch) -> None:
    target = tmp_path / "server.jar"
    monkeypatch.setattr(http_utils_module._rate_limiter, "wait", lambda _domain: None)
    monkeypatch.setattr(HTTPUtils, "_get_session", classmethod(lambda _cls: _FakeSession(b"new-bytes")))

    def _unexpected_hash(_algorithm: str):
        raise AssertionError("hashlib.new should not be called without an expected hash")

    monkeypatch.setattr(http_utils_module.hashlib, "new", _unexpected_hash)

    assert HTTPUtils.download_file("https://example.com/server.jar", str(target)) is True
    assert target.read_bytes() == b"new-bytes"


def test_download_file_reports_insufficient_disk_space(tmp_path, monkeypatch) -> None:
    target = tmp_path / "server.jar"
    failure_messages: list[str] = []
    monkeypatch.setattr(http_utils_module._rate_limiter, "wait", lambda _domain: None)
    monkeypatch.setattr(HTTPUtils, "_get_session", classmethod(lambda _cls: _FakeSession(b"new-bytes")))
    monkeypatch.setattr(
        http_utils_module.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=10, used=9, free=1),
    )

    assert (
        HTTPUtils.download_file(
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
    monkeypatch.setattr(http_utils_module._rate_limiter, "wait", lambda _domain: None)
    monkeypatch.setattr(HTTPUtils, "_get_session", classmethod(lambda _cls: _TimeoutSession()))

    assert (
        HTTPUtils.download_file(
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
        HTTPUtils.download_file(
            "not-a-url",
            str(target),
            failure_message_callback=failure_messages.append,
        )
        is False
    )
    assert failure_messages == ["URL 參數無效"]


def test_download_file_keeps_existing_target_when_replace_fails(tmp_path, monkeypatch) -> None:
    target = tmp_path / "server.jar"
    target.write_bytes(b"old-bytes")
    monkeypatch.setattr(http_utils_module._rate_limiter, "wait", lambda _domain: None)
    monkeypatch.setattr(HTTPUtils, "_get_session", classmethod(lambda _cls: _FakeSession(b"new-bytes")))

    def _fail_replace(_self: Path, _target: Path) -> Path:
        raise OSError("target locked")

    monkeypatch.setattr(Path, "replace", _fail_replace)

    assert HTTPUtils.download_file("https://example.com/server.jar", str(target)) is False
    assert target.read_bytes() == b"old-bytes"
