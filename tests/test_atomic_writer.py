import json
from src.utils import atomic_write_json


def test_atomic_write_json_creates_file(tmp_path):
    payload = {"a": 1, "b": "测试"}
    target = tmp_path / "test_index.json"
    ok = atomic_write_json(target, payload)
    assert ok is True
    assert target.exists()
    with open(target, encoding="utf-8") as f:
        data = json.load(f)
    assert data == payload


def test_atomic_write_json_overwrite(tmp_path):
    payload1 = {"x": 1}
    payload2 = {"x": 2}
    target = tmp_path / "test_index.json"
    assert atomic_write_json(target, payload1)
    assert atomic_write_json(target, payload2)
    with open(target, encoding="utf-8") as f:
        data = json.load(f)
    assert data == payload2
