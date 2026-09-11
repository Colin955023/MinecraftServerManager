from __future__ import annotations

import struct
import zipfile

import pytest

import src.utils.core_utils.atomic_writer as atomic_writer_module
from src.utils import (
    SAFE_TEXT_FILE_MAX_BYTES,
    atomic_write_json,
    copy_dir,
    copy_file,
    copy_within,
    delete_within,
    open_bounded_zip,
    open_bounded_zip_writer,
    read_json,
    read_text_file,
    safe_extract_zip,
)


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


@pytest.mark.parametrize(
    "member_name",
    [
        "mods/payload.txt:stream",
        "CON.txt",
        "CONIN$",
        "CONOUT$",
        "COM¹.txt",
        "LPT².txt",
        "mods/NUL.dat",
        "mods/trailing-dot.",
        "mods/trailing-space ",
    ],
)
def test_safe_extract_zip_rejects_windows_unsafe_names(tmp_path, member_name: str) -> None:
    zip_path = tmp_path / "server.zip"
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(member_name, b"unsafe")

    with pytest.raises(ValueError, match="不安全的成員名稱"):
        safe_extract_zip(zip_path, extract_dir)


def test_safe_extract_zip_rejects_case_insensitive_path_collision(tmp_path) -> None:
    zip_path = tmp_path / "server.zip"
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("world/Data/file.dat", b"a")
        zf.writestr("world/data/FILE.dat", b"b")

    with pytest.raises(ValueError, match="重複或大小寫衝突"):
        safe_extract_zip(zip_path, extract_dir)


def test_safe_extract_zip_rejects_file_directory_collision(tmp_path) -> None:
    zip_path = tmp_path / "server.zip"
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("world/region", b"file")
        zf.writestr("world/region/r.0.0.mca", b"child")

    with pytest.raises(ValueError, match="檔案/目錄路徑衝突"):
        safe_extract_zip(zip_path, extract_dir)


def test_safe_extract_zip_rejects_unsupported_compression(tmp_path) -> None:
    zip_path = tmp_path / "server.zip"
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_BZIP2) as zf:
        zf.writestr("server.properties", b"motd=test")

    with pytest.raises(ValueError, match="不支援的壓縮格式"):
        safe_extract_zip(zip_path, extract_dir)


def test_safe_extract_zip_rejects_excessive_member_count(tmp_path) -> None:
    zip_path = tmp_path / "server.zip"
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a.txt", b"a")
        zf.writestr("b.txt", b"b")

    with pytest.raises(ValueError, match="成員數量超過安全上限"):
        safe_extract_zip(zip_path, extract_dir, max_members=1)


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


def test_open_bounded_zip_rejects_oversized_central_directory(tmp_path) -> None:
    zip_path = tmp_path / "large-central-directory.zip"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("entry.txt", b"content")

    with (
        pytest.raises(ValueError, match="central directory"),
        open_bounded_zip(zip_path, max_central_directory_bytes=1),
    ):
        pass


def test_open_bounded_zip_rejects_oversized_archive(tmp_path) -> None:
    zip_path = tmp_path / "large-archive.zip"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("entry.txt", b"content")

    with (
        pytest.raises(ValueError, match="ZIP 檔案大小"),
        open_bounded_zip(zip_path, max_archive_bytes=1),
    ):
        pass


def test_open_bounded_zip_rejects_forged_eocd_member_count(tmp_path) -> None:
    zip_path = tmp_path / "forged-member-count.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for index in range(2):
            archive.writestr(f"entry-{index}.txt", b"content")

    payload = bytearray(zip_path.read_bytes())
    eocd_offset = payload.rfind(b"PK\x05\x06")
    assert eocd_offset >= 0
    struct.pack_into("<H", payload, eocd_offset + 10, 0)
    zip_path.write_bytes(payload)

    with pytest.raises(ValueError, match="成員數量"), open_bounded_zip(zip_path, max_members=1):
        pass


def test_open_bounded_zip_writer_limits_members_and_output_is_readable(tmp_path) -> None:
    zip_path = tmp_path / "managed.zip"

    with open_bounded_zip_writer(zip_path, max_members=1, max_total_bytes=8, max_member_bytes=8) as writer:
        writer.writestr("data/info.txt", b"content")
        with pytest.raises(ValueError, match="成員數量"):
            writer.writestr("data/other.txt", b"more")

    with open_bounded_zip(zip_path, max_members=1) as archive:
        assert archive.read("data/info.txt") == b"content"


def test_copy_within_rejects_cross_root_source(tmp_path) -> None:
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    source = tmp_path / "outside.txt"
    source.write_bytes(b"outside")

    assert copy_within(base_dir, source, base_dir / "copied.txt") is False
    assert not (base_dir / "copied.txt").exists()


def test_copy_file_keeps_existing_destination_when_source_exceeds_limit(tmp_path) -> None:
    source = tmp_path / "source.bin"
    target = tmp_path / "target.bin"
    source.write_bytes(b"new payload")
    target.write_bytes(b"existing payload")

    assert copy_file(source, target, max_bytes=3) is False
    assert target.read_bytes() == b"existing payload"


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


def test_read_text_file_enforces_byte_limit(tmp_path) -> None:
    text_path = tmp_path / "large.txt"
    text_path.write_bytes(b"x" * (SAFE_TEXT_FILE_MAX_BYTES + 1))

    assert read_text_file(text_path, max_bytes=SAFE_TEXT_FILE_MAX_BYTES) is None


def test_read_json_enforces_default_byte_limit(tmp_path) -> None:
    json_path = tmp_path / "large.json"
    json_path.write_bytes(b'{"data":"' + b"x" * SAFE_TEXT_FILE_MAX_BYTES + b'"}')

    assert read_json(json_path) is None


def test_copy_dir_rejects_junction_entries(tmp_path, make_junction) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    make_junction(source_dir / "linked", outside)

    assert copy_dir(source_dir, tmp_path / "target") is False


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
