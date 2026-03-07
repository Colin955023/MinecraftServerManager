from __future__ import annotations

import pytest
from src.utils import ServerPropertiesHelper


@pytest.mark.smoke
def test_load_properties_parses_escaped_delimiters(tmp_path) -> None:
    props_file = tmp_path / "server.properties"
    props_file.write_text(
        "# Minecraft server properties\nmotd=Hello\\: World\nresource-pack-prompt=\\=Welcome\nserver-ip=\\ 127.0.0.1\n",
        encoding="utf-8",
    )

    loaded = ServerPropertiesHelper.load_properties(props_file)
    assert loaded["motd"] == "Hello: World"
    assert loaded["resource-pack-prompt"] == "=Welcome"
    assert loaded["server-ip"] == " 127.0.0.1"


@pytest.mark.smoke
def test_save_properties_round_trip_preserves_values(tmp_path) -> None:
    props_file = tmp_path / "server.properties"
    original = {
        "motd": "Hello: Survival",
        "resource-pack-prompt": "=Please accept",
        "level-name": "我的世界",
    }

    ServerPropertiesHelper.save_properties(props_file, original)
    reloaded = ServerPropertiesHelper.load_properties(props_file)

    assert reloaded["motd"] == original["motd"]
    assert reloaded["resource-pack-prompt"] == original["resource-pack-prompt"]
    assert reloaded["level-name"] == original["level-name"]
