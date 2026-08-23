"""檔案原子寫入工具測試模組"""

import json

from src.utils import atomic_write_bytes, atomic_write_json, atomic_write_text


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
