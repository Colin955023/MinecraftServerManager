"""檔案原子寫入工具測試模組"""

import json

import src.utils.core_utils.atomic_writer as atomic_writer_module
from src.utils import atomic_replace_file_within, atomic_write_bytes, atomic_write_json, atomic_write_text


def test_atomic_write_json_creates_file(tmp_path):
    payload = {"a": 1, "b": "測試"}
    target = tmp_path / "test_index.json"
    ok = atomic_write_json(target, payload)
    assert ok is True
    assert target.exists()
    with target.open(encoding="utf-8") as f:
        data = json.load(f)
    assert data == payload


def test_atomic_write_json_overwrite(tmp_path):
    payload1 = {"x": 1}
    payload2 = {"x": 2}
    target = tmp_path / "test_index.json"
    assert atomic_write_json(target, payload1)
    assert atomic_write_json(target, payload2)
    with target.open(encoding="utf-8") as f:
        data = json.load(f)
    assert data == payload2


def test_atomic_write_text_overwrite(tmp_path):
    target = tmp_path / "start_server.bat"
    assert atomic_write_text(target, "echo first\n", encoding="utf-8") is True
    assert atomic_write_text(target, "echo second\n", encoding="utf-8") is True
    assert target.read_text(encoding="utf-8") == "echo second\n"


def test_atomic_write_bytes_overwrite(tmp_path):
    target = tmp_path / "server.jar"
    assert atomic_write_bytes(target, b"first") is True
    assert atomic_write_bytes(target, b"second") is True
    assert target.read_bytes() == b"second"


def test_atomic_write_fails_closed_when_secure_temp_creation_fails(tmp_path, monkeypatch):
    target = tmp_path / "server.properties"
    target.write_text("motd=old\n", encoding="utf-8")

    def fail_temp_creation(*_args, **_kwargs):
        raise OSError("temp unavailable")

    monkeypatch.setattr(atomic_writer_module.tempfile, "NamedTemporaryFile", fail_temp_creation)
    monkeypatch.setattr(atomic_writer_module.time, "sleep", lambda _seconds: None)

    assert atomic_write_text(target, "motd=new\n") is False
    assert target.read_text(encoding="utf-8") == "motd=old\n"
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_replace_file_within_replaces_target(tmp_path):
    source = tmp_path / "staging" / "server.jar"
    target = tmp_path / "mods" / "server.jar"
    source.parent.mkdir()
    source.write_bytes(b"new")
    target.parent.mkdir()
    target.write_bytes(b"old")

    assert atomic_replace_file_within(tmp_path, source, target) is True
    assert not source.exists()
    assert target.read_bytes() == b"new"


def test_atomic_replace_file_within_rejects_target_outside_base(tmp_path):
    base_dir = tmp_path / "server"
    source = base_dir / "staging" / "server.jar"
    target = tmp_path / "outside.jar"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"new")

    assert atomic_replace_file_within(base_dir, source, target) is False
    assert source.read_bytes() == b"new"
    assert not target.exists()


def test_atomic_write_rejects_reparse_parent(tmp_path):
    safe_dir = tmp_path / "safe"
    outside_dir = tmp_path / "outside"
    safe_dir.mkdir()
    outside_dir.mkdir()
    linked_dir = safe_dir / "linked"
    try:
        linked_dir.symlink_to(outside_dir, target_is_directory=True)
    except OSError:
        return

    assert atomic_write_text(linked_dir / "state.json", "unsafe") is False
    assert not (outside_dir / "state.json").exists()
