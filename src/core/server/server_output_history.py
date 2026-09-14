"""伺服器歷史輸出的安全尾端讀取"""

from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from src.utils import SAFE_TEXT_FILE_MAX_BYTES, open_regular_file


@dataclass(frozen=True, slots=True)
class ServerOutputHistory:
    """伺服器歷史輸出的不可變快照"""

    lines: tuple[str, ...] = ()
    truncated: bool = False
    sequence: int = 0


def read_server_output_history(
    log_file: Path,
    *,
    allowed_root: Path,
    max_lines: int = 2500,
    max_bytes: int = SAFE_TEXT_FILE_MAX_BYTES,
) -> ServerOutputHistory:
    """
    從一般檔案尾端讀取受限制的伺服器歷史輸出

    Args:
        log_file: 日誌檔案
        allowed_root: 日誌必須位於其中的伺服器根目錄
        max_lines: 最多回傳的非空行數
        max_bytes: 最多從檔案尾端讀取的位元組數

    Returns:
        歷史輸出快照
    """
    bounded_bytes = min(SAFE_TEXT_FILE_MAX_BYTES, max(64 * 1024, int(max_bytes)))
    bounded_lines = max(200, int(max_lines))
    source = open_regular_file(log_file, allowed_root=allowed_root)
    with source:
        file_size = os.fstat(source.fileno()).st_size
        read_size = min(file_size, bounded_bytes)
        start = file_size - read_size
        source.seek(start)
        payload = source.read(read_size)
    text = payload.decode("utf-8", errors="ignore") if payload else ""
    lines = text.splitlines()
    if start > 0 and lines:
        lines = lines[1:]
    compact_iter = (line for line in lines if line.strip())
    recent_lines = deque(compact_iter, maxlen=bounded_lines + 1)
    has_more = len(recent_lines) > bounded_lines
    if has_more:
        recent_lines.popleft()
    truncated = start > 0 or has_more
    return ServerOutputHistory(lines=tuple(recent_lines), truncated=truncated)


__all__ = ["ServerOutputHistory", "read_server_output_history"]
