from __future__ import annotations

import zipfile

import pytest

import src.utils.core_utils.atomic_writer as atomic_writer_module
from src.utils import atomic_write_json, copy_dir, delete_within, read_json, safe_extract_zip


def test_atomic_write_json_roundtrip_immediate(tmp_path) -> None:
    target = tmp_path / "state.json"
    payload = {"server": "alpha", "ports": [25565, 25566], "enabled": True}

    assert atomic_write_json(target, payload) is True
    assert read_json(target) == payload


def test_atomic_write_json_if_changed_skips_rewrite_for_same_payload(tmp_path, monkeypatch) -> None:
    target = tmp_path / "state.json"
    replace_call_count = 0
    original_replace = atomic_writer_module.os.replace

    def _counting_replace(src, dst):
        nonlocal replace_call_count
        replace_call_count += 1
        return original_replace(src, dst)

    monkeypatch.setattr(atomic_writer_module.os, "replace", _counting_replace)

    assert atomic_write_json(target, {"value": 1}, skip_if_unchanged=True) is True
    assert replace_call_count == 1

    count_before_no_change = replace_call_count
    assert atomic_write_json(target, {"value": 1}, skip_if_unchanged=True) is True
    assert replace_call_count == count_before_no_change

    count_before_change = replace_call_count
    assert atomic_write_json(target, {"value": 2}, skip_if_unchanged=True) is True
    assert replace_call_count == count_before_change + 1


def test_atomic_write_json_keeps_existing_file_when_new_payload_not_serializable(tmp_path) -> None:
    target = tmp_path / "state.json"
    original = {"ok": True}

    assert atomic_write_json(target, original) is True
    assert atomic_write_json(target, {"bad": {1, 2, 3}}) is False
    assert read_json(target) == original


def test_safe_extract_zip_reports_progress(tmp_path) -> None:
    zip_path = tmp_path / "server.zip"
    extract_dir = tmp_path / "extracted"
    data_a = b"a" * 4096
    data_b = b"b" * 2048

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("mods/mod_a.jar", data_a)
        zf.writestr("mods/mod_b.jar", data_b)

    progress_events: list[tuple[int, int]] = []

    def _on_progress(done: int, total: int) -> None:
        progress_events.append((done, total))

    safe_extract_zip(zip_path, extract_dir, progress_callback=_on_progress)

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


def test_safe_extract_zip_rejects_excessive_uncompressed_size(tmp_path) -> None:
    zip_path = tmp_path / "server.zip"
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("mods/huge.jar", b"x" * 2048)

    with pytest.raises(ValueError, match="大小超過安全上限"):
        safe_extract_zip(zip_path, extract_dir, max_total_uncompressed_bytes=1024)

    assert not (extract_dir / "mods" / "huge.jar").exists()


@pytest.mark.parametrize(
    "member_name", ["../evil.txt", "mods/../evil.txt", "/absolute/evil.txt", r"..\evil.txt", "C:/evil.txt"]
)
def test_safe_extract_zip_rejects_unsafe_member_names(tmp_path, member_name: str) -> None:
    zip_path = tmp_path / "server.zip"
    extract_dir = tmp_path / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(member_name, b"evil")

    with pytest.raises(ValueError):
        safe_extract_zip(zip_path, extract_dir)

    assert not (tmp_path / "evil.txt").exists()


def test_safe_extract_zip_rejects_symlink_entry(tmp_path) -> None:
    zip_path = tmp_path / "server.zip"
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as zf:
        info = zipfile.ZipInfo("mods/evil_link.jar")
        info.external_attr = 0o120777 << 16
        zf.writestr(info, "../../../etc/passwd")

    with pytest.raises(ValueError):
        safe_extract_zip(zip_path, extract_dir)

    assert not (extract_dir / "mods").exists()


def test_safe_extract_zip_rejects_oversized_single_member(tmp_path) -> None:
    zip_path = tmp_path / "server.zip"
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("mods/big.jar", b"x" * 1000)

    with pytest.raises(ValueError, match="過大"):
        safe_extract_zip(
            zip_path,
            extract_dir,
            max_member_uncompressed_bytes=100,
            max_compression_ratio=None,
        )

    assert not (extract_dir / "mods" / "big.jar").exists()


def test_safe_extract_zip_rejects_excessive_compression_ratio(tmp_path) -> None:
    zip_path = tmp_path / "server.zip"
    extract_dir = tmp_path / "extracted"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mods/bomb.jar", b"A" * (2 * 1024 * 1024))

    with pytest.raises(ValueError, match="壓縮比例"):
        safe_extract_zip(
            zip_path,
            extract_dir,
            max_member_uncompressed_bytes=None,
            max_total_uncompressed_bytes=None,
            max_compression_ratio=200,
        )


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

    assert copy_dir(source_dir, target_dir, progress_callback=_on_progress) is True
    assert (target_dir / "mods" / "a.jar").read_bytes() == b"a"
    assert (target_dir / "config" / "b.cfg").read_bytes() == b"b"
    assert progress_events[0] == (0, 2)
    assert progress_events[-1] == (2, 2)
    assert [done for done, _total in progress_events] == sorted(done for done, _total in progress_events)


def test_delete_within_blocks_paths_outside_base(tmp_path) -> None:
    base_dir = tmp_path / "servers_root"
    base_dir.mkdir(parents=True, exist_ok=True)

    inside_dir = base_dir / "alpha"
    inside_dir.mkdir(parents=True, exist_ok=True)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir(parents=True, exist_ok=True)

    assert delete_within(base_dir, inside_dir) is True
    assert inside_dir.exists() is False
    assert delete_within(base_dir, outside_dir) is False
    assert outside_dir.exists() is True


def test_delete_within_blocks_base_directory_itself(tmp_path) -> None:
    base_dir = tmp_path / "servers_root"
    base_dir.mkdir()

    assert delete_within(base_dir, base_dir) is False
    assert base_dir.is_dir()
