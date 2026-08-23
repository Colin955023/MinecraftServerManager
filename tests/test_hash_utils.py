from __future__ import annotations

import hashlib
from pathlib import Path

from src.utils import HashUtils


def test_matches_known_sha256(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    content = b"Minecraft Server Manager\n"
    file_path.write_bytes(content)

    expected = hashlib.sha256(content).hexdigest()
    actual = HashUtils.compute_file_hash_sync(file_path, algorithm="sha256")

    assert actual == expected


def test_matches_known_sha512(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.jar"
    content = b"\x00\x01\x02fake jar bytes" * 100
    file_path.write_bytes(content)

    expected = hashlib.sha512(content).hexdigest()
    actual = HashUtils.compute_file_hash_sync(file_path, algorithm="sha512")

    assert actual == expected


def test_unsupported_algorithm_returns_empty_string(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_bytes(b"content")

    assert HashUtils.compute_file_hash_sync(file_path, algorithm="not-a-real-algorithm") == ""


def test_missing_file_returns_empty_string(tmp_path: Path) -> None:
    missing_path = tmp_path / "does_not_exist.txt"

    assert HashUtils.compute_file_hash_sync(missing_path, algorithm="sha256") == ""


def test_chunked_reading_matches_single_read(tmp_path: Path) -> None:
    file_path = tmp_path / "multi_chunk.bin"
    content = bytes(range(256)) * 50
    file_path.write_bytes(content)

    hash_default_chunk = HashUtils.compute_file_hash_sync(file_path, algorithm="sha256")

    assert hash_default_chunk == hashlib.sha256(content).hexdigest()


def test_compute_file_hash_cache_invalidates_when_file_changes(tmp_path) -> None:
    file_path = tmp_path / "mutable.bin"
    file_path.write_bytes(b"first")
    first = HashUtils.compute_file_hash(file_path, algorithm="sha256", use_cache=True)

    file_path.write_bytes(b"second-content")
    second = HashUtils.compute_file_hash(file_path, algorithm="sha256", use_cache=True)

    assert first
    assert second
    assert first != second
    assert second == HashUtils.compute_file_hash_sync(file_path, algorithm="sha256")
