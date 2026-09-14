from pathlib import Path

from src.utils import JavaUtils, atomic_write_json, read_json
from src.utils.java_support import java_utils


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


def test_required_java_major_uses_persisted_cache_offline(monkeypatch, tmp_path: Path) -> None:
    version_cache = tmp_path / "mc_versions_cache.json"
    atomic_write_json(version_cache, [{"id": "1.21.1", "url": "https://example.invalid/1.21.1.json"}])
    monkeypatch.setattr(java_utils.RuntimePaths, "get_version_cache_dir", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(
        java_utils.HTTPClient,
        "fetch_json",
        staticmethod(lambda *_args, **_kwargs: {"javaVersion": {"majorVersion": 21}}),
    )
    JavaUtils.get_required_java_major.cache_clear()

    assert JavaUtils.get_required_java_major("1.21.1") == 21

    JavaUtils.get_required_java_major.cache_clear()
    monkeypatch.setattr(java_utils.HTTPClient, "fetch_json", staticmethod(lambda *_args, **_kwargs: None))
    assert JavaUtils.get_required_java_major("1.21.1") == 21
