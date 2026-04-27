from __future__ import annotations

import queue
from typing import Any, cast

from src.ui.server_monitor_window import ServerMonitorWindow


class _FakeServerManager:
    def __init__(self, output_lines: list[str] | None = None) -> None:
        self.output_lines = output_lines or []

    def read_server_output(self, *_args: Any, **_kwargs: Any) -> list[str]:
        return self.output_lines


class _FakeLabel:
    def __init__(self) -> None:
        self.text = ""

    def is_alive(self) -> bool:
        return True

    def configure(self, **kwargs: str) -> None:
        self.text = kwargs.get("text", self.text)


def _make_monitor(output_lines: list[str] | None = None) -> ServerMonitorWindow:
    monitor = object.__new__(ServerMonitorWindow)
    monitor.server_manager = _FakeServerManager(output_lines)
    monitor.server_name = "minecraft_server"
    monitor.ui_queue = queue.Queue()
    monitor_any = cast(Any, monitor)
    monitor_any.players_label = _FakeLabel()
    monitor._last_player_count = None
    monitor._last_max_players = None
    monitor._last_player_names = None
    monitor._last_ui_state = {}
    return monitor


def _players_label(monitor: ServerMonitorWindow) -> _FakeLabel:
    return cast(_FakeLabel, cast(Any, monitor).players_label)


def test_parse_player_list_line_extracts_count_and_names() -> None:
    line = "[15:45:52] [Server thread/INFO]: There are 1 of a max of 20 players online: Andy"

    assert ServerMonitorWindow._parse_player_list_line(line) == (1, 20, ("Andy",))


def test_parse_player_presence_event_extracts_join_and_left() -> None:
    join_line = "[15:45:52] [Server thread/INFO]: Andy joined the game"
    left_line = "[15:50:00] [Server thread/INFO]: Andy left the game"

    assert ServerMonitorWindow._parse_player_presence_event(join_line) == ("Andy", True)
    assert ServerMonitorWindow._parse_player_presence_event(left_line) == ("Andy", False)


def test_read_player_list_without_response_preserves_current_list() -> None:
    monitor = _make_monitor(["[15:45:52] [Server thread/INFO]: unrelated output"])
    captured: list[list[str]] = []
    monitor._last_player_names = ("Andy",)
    cast(Any, monitor).update_player_list = captured.append

    monitor.read_player_list()

    assert captured == []
    assert monitor.ui_queue.empty()


def test_presence_event_updates_list_immediately() -> None:
    monitor = _make_monitor()
    captured: list[list[str]] = []
    monitor._last_max_players = 20
    cast(Any, monitor).update_player_list = captured.append

    monitor._apply_player_presence_event("Andy", True)

    assert monitor._last_player_count == 1
    assert _players_label(monitor).text == "👥 玩家數量: 1/20"
    assert captured == [["Andy"]]


def test_read_player_list_line_queues_authoritative_snapshot() -> None:
    monitor = _make_monitor()
    captured: list[list[str]] = []
    cast(Any, monitor).update_player_list = captured.append

    monitor.read_player_list("[INFO]: There are 1 of a max of 20 players online: Andy")
    callback = monitor.ui_queue.get_nowait()
    callback()

    assert monitor._last_player_count == 1
    assert monitor._last_max_players == 20
    assert _players_label(monitor).text == "👥 玩家數量: 1/20"
    assert captured == [["Andy"]]
