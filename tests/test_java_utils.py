from pathlib import Path

from src.utils import JavaUtils, read_json


def test_validate_java_candidates_removes_unusable_entries_and_updates_cache(monkeypatch, tmp_path: Path) -> None:
    valid_java = tmp_path / "valid-javaw.exe"
    valid_java.write_bytes(b"valid")
    missing_java = tmp_path / "missing-javaw.exe"
    cache_path = tmp_path / "java_candidates_cache.json"

    monkeypatch.setattr(
        JavaUtils,
        "get_all_local_java_candidates",
        staticmethod(lambda: [(str(valid_java), 17), (str(missing_java), 21)]),
    )
    monkeypatch.setattr(
        JavaUtils,
        "_resolve_java_candidate",
        staticmethod(lambda path: (str(path), 17) if path == valid_java else None),
    )
    monkeypatch.setattr(JavaUtils, "_get_java_cache_path", staticmethod(lambda: cache_path))
    monkeypatch.setattr(JavaUtils, "_cached_java_candidates", None)

    assert JavaUtils.validate_java_candidates() == [(str(valid_java), 17)]
    assert JavaUtils._cached_java_candidates == [(str(valid_java), 17)]
    assert read_json(cache_path) == {"candidates": [{"path": str(valid_java), "major": 17}]}
