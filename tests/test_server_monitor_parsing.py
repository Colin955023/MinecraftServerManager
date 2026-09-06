from __future__ import annotations

from src.ui.windows.server_monitor_parsing import (
    find_latest_player_line,
    parse_player_presence_event,
)


def test_find_latest_player_line_uses_latest_authoritative_snapshot() -> None:
    lines = ["There are 0 of a max of 20 players online:", "There are 1 of a max of 20 players online: Andy"]
    assert find_latest_player_line(lines) == lines[-1]


def test_presence_parser_accepts_join_and_leave_messages() -> None:
    assert parse_player_presence_event("[INFO]: Andy joined the game") == ("Andy", True)
    assert parse_player_presence_event("[INFO]: Andy lost connection") == ("Andy", False)
