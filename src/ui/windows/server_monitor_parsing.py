"""伺服器監控的純文字解析"""

from __future__ import annotations

import re

_ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_PLAYER_LIST_PATTERN = re.compile(
    r"There are\s+(\d+)(?:\s+(?:of a max(?: of)?|/)\s+(\d+))?\s+players online:?\s*(.*)$",
    re.IGNORECASE,
)
_PLAYER_JOIN_PATTERN = re.compile(
    r"\b([A-Za-z0-9_]{1,16})\s+(?:joined the game|logged in with entity id)\b", re.IGNORECASE
)
_PLAYER_LEAVE_PATTERN = re.compile(r"\b([A-Za-z0-9_]{1,16})\s+(?:left the game|lost connection)\b", re.IGNORECASE)


def get_status_text(is_running: bool) -> tuple[str, str]:
    """將執行狀態轉成監控視窗文字與色彩"""
    return ("🟢 狀態: 執行中", "green") if is_running else ("🔴 狀態: 已停止", "red")


def clean_text(line: str) -> str:
    """
    移除 ANSI 控制碼並清理行首尾空白

    Args:
        line: 原始日誌行

    Returns:
        清理後的文字
    """
    return _ANSI_ESCAPE_PATTERN.sub("", line).strip()


def parse_player_list_line(line: str) -> tuple[int, int, tuple[str, ...]] | None:
    """
    解析伺服器列出的線上玩家數量與名稱

    Args:
        line: 原始日誌行

    Returns:
        玩家數量、上限與名稱，無法解析時回傳 None
    """
    clean = clean_text(line)
    marker_index = clean.find("There are ")
    if marker_index != -1:
        clean = clean[marker_index:]
    match = _PLAYER_LIST_PATTERN.search(clean)
    if not match:
        return None
    current_players = int(match.group(1))
    max_players = int(match.group(2)) if match.group(2) else current_players
    player_names = tuple(name.strip() for name in (match.group(3) or "").split(",") if name.strip())
    return current_players, max_players, player_names


def parse_player_presence_event(line: str) -> tuple[str, bool] | None:
    """
    解析玩家加入或離開事件

    Args:
        line: 原始日誌行

    Returns:
        玩家名稱與是否加入，無法解析時回傳 None
    """
    clean = clean_text(line)
    message = clean.rsplit("]:", 1)[-1].strip() if "]:" in clean else clean
    match_join = _PLAYER_JOIN_PATTERN.search(message)
    if match_join:
        return match_join.group(1), True
    match_leave = _PLAYER_LEAVE_PATTERN.search(message)
    if match_leave:
        return match_leave.group(1), False
    return None


def find_latest_player_line(lines: list[str]) -> str | None:
    """
    找出最近一筆玩家列表日誌

    Args:
        lines: 按時間排序的日誌行

    Returns:
        最近的玩家列表行，找不到時回傳 None
    """
    return next((line for line in reversed(lines) if parse_player_list_line(line)), None)


__all__ = [
    "clean_text",
    "find_latest_player_line",
    "get_status_text",
    "parse_player_list_line",
    "parse_player_presence_event",
]
