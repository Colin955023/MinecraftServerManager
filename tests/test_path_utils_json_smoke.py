from __future__ import annotations

import pytest
import src.utils.path_utils as path_utils_module
from src.utils import PathUtils


@pytest.mark.smoke
def test_save_json_roundtrip_immediate(tmp_path) -> None:
    target = tmp_path / "state.json"
    payload = {"server": "alpha", "ports": [25565, 25566], "enabled": True}

    assert PathUtils.save_json(target, payload) is True
    assert PathUtils.load_json(target) == payload


@pytest.mark.smoke
def test_save_json_if_changed_skips_rewrite_for_same_payload(tmp_path, monkeypatch) -> None:
    target = tmp_path / "state.json"
    replace_call_count = 0
    original_replace = path_utils_module.os.replace

    def _counting_replace(src, dst):
        nonlocal replace_call_count
        replace_call_count += 1
        return original_replace(src, dst)

    monkeypatch.setattr(path_utils_module.os, "replace", _counting_replace)

    assert PathUtils.save_json_if_changed(target, {"value": 1}) is True
    assert replace_call_count == 1

    count_before_no_change = replace_call_count
    assert PathUtils.save_json_if_changed(target, {"value": 1}) is True
    assert replace_call_count == count_before_no_change

    count_before_change = replace_call_count
    assert PathUtils.save_json_if_changed(target, {"value": 2}) is True
    assert replace_call_count == count_before_change + 1


@pytest.mark.smoke
def test_save_json_keeps_existing_file_when_new_payload_not_serializable(tmp_path) -> None:
    target = tmp_path / "state.json"
    original = {"ok": True}

    assert PathUtils.save_json(target, original) is True
    assert PathUtils.save_json(target, {"bad": {1, 2, 3}}) is False
    assert PathUtils.load_json(target) == original
