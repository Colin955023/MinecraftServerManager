from __future__ import annotations

import zipfile

import pytest
import src.utils.core_utils.path_utils as path_utils_module
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


@pytest.mark.smoke
def test_safe_extract_zip_reports_progress(tmp_path) -> None:
    zip_path = tmp_path / "server.zip"
    extract_dir = tmp_path / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    data_a = b"a" * 4096
    data_b = b"b" * 2048

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("mods/mod_a.jar", data_a)
        zf.writestr("mods/mod_b.jar", data_b)

    progress_events: list[tuple[int, int]] = []

    def _on_progress(done: int, total: int) -> None:
        progress_events.append((done, total))

    PathUtils.safe_extract_zip(zip_path, extract_dir, progress_callback=_on_progress)

    expected_total = len(data_a) + len(data_b)
    assert (extract_dir / "mods" / "mod_a.jar").read_bytes() == data_a
    assert (extract_dir / "mods" / "mod_b.jar").read_bytes() == data_b
    assert progress_events
    assert progress_events[0] == (0, expected_total)
    assert progress_events[-1][0] == progress_events[-1][1]
    assert progress_events[-1][1] == expected_total

    done_values = [done for done, _total in progress_events]
    assert done_values == sorted(done_values)
    assert any(done > 0 for done in done_values[1:])
    assert all(0 <= done <= total for done, total in progress_events)
    assert all(total == expected_total for _done, total in progress_events)


@pytest.mark.smoke
def test_copy_dir_reports_progress(tmp_path) -> None:
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    (source_dir / "mods").mkdir(parents=True, exist_ok=True)
    (source_dir / "config").mkdir(parents=True, exist_ok=True)
    (source_dir / "mods" / "a.jar").write_bytes(b"a")
    (source_dir / "config" / "b.cfg").write_bytes(b"b")

    progress_events: list[tuple[int, int]] = []

    def _on_progress(done: int, total: int) -> None:
        progress_events.append((done, total))

    assert PathUtils.copy_dir(source_dir, target_dir, progress_callback=_on_progress) is True
    assert (target_dir / "mods" / "a.jar").read_bytes() == b"a"
    assert (target_dir / "config" / "b.cfg").read_bytes() == b"b"
    assert progress_events[0] == (0, 2)
    assert progress_events[-1] == (2, 2)
    assert [done for done, _total in progress_events] == sorted(done for done, _total in progress_events)


@pytest.mark.smoke
def test_delete_within_blocks_paths_outside_base(tmp_path) -> None:
    base_dir = tmp_path / "servers_root"
    base_dir.mkdir(parents=True, exist_ok=True)

    inside_dir = base_dir / "alpha"
    inside_dir.mkdir(parents=True, exist_ok=True)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir(parents=True, exist_ok=True)

    assert PathUtils.delete_within(base_dir, inside_dir) is True
    assert inside_dir.exists() is False
    assert PathUtils.delete_within(base_dir, outside_dir) is False
    assert outside_dir.exists() is True
