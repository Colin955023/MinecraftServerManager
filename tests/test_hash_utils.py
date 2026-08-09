from __future__ import annotations

import hashlib
from pathlib import Path

from src.utils import HashUtils


def test_matches_known_sha256(tmp_path: Path) -> None:
    """計算結果應與標準函式庫 hashlib 的結果一致"""
    file_path = tmp_path / "sample.txt"
    content = b"Minecraft Server Manager\n"
    file_path.write_bytes(content)

    expected = hashlib.sha256(content).hexdigest()
    actual = HashUtils.compute_file_hash_sync(file_path, algorithm="sha256")

    assert actual == expected


def test_matches_known_sha512(tmp_path: Path) -> None:
    """演算法可切換，且結果同樣需與 hashlib 一致（Modrinth 主要使用 sha512）"""
    file_path = tmp_path / "sample.jar"
    content = b"\x00\x01\x02fake jar bytes" * 100
    file_path.write_bytes(content)

    expected = hashlib.sha512(content).hexdigest()
    actual = HashUtils.compute_file_hash_sync(file_path, algorithm="sha512")

    assert actual == expected


def test_unsupported_algorithm_returns_empty_string(tmp_path: Path) -> None:
    """不支援的演算法名稱應回傳空字串，而不是拋出例外"""
    file_path = tmp_path / "sample.txt"
    file_path.write_bytes(b"content")

    assert HashUtils.compute_file_hash_sync(file_path, algorithm="not-a-real-algorithm") == ""


def test_missing_file_returns_empty_string(tmp_path: Path) -> None:
    """檔案不存在時應回傳空字串，而不是拋出例外（呼叫端不必額外處理）"""
    missing_path = tmp_path / "does_not_exist.txt"

    assert HashUtils.compute_file_hash_sync(missing_path, algorithm="sha256") == ""


def test_chunked_reading_matches_single_read(tmp_path: Path) -> None:
    """使用很小的 chunk_size 分多次讀取時，結果應與一次讀完一致"""
    file_path = tmp_path / "multi_chunk.bin"
    content = bytes(range(256)) * 50
    file_path.write_bytes(content)

    hash_default_chunk = HashUtils.compute_file_hash_sync(file_path, algorithm="sha256")

    assert hash_default_chunk == hashlib.sha256(content).hexdigest()
