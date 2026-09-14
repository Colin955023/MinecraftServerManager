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


def test_preload_all_java_requirements_fetches_and_sorts_descending(monkeypatch, tmp_path: Path) -> None:
    version_cache = tmp_path / "mc_versions_cache.json"
    atomic_write_json(
        version_cache,
        [
            {"id": "1.16.5", "type": "release", "url": "https://example.invalid/1.16.5.json"},
            {"id": "26.2", "type": "release", "url": "https://example.invalid/26.2.json"},
            {"id": "1.21.1", "type": "release", "url": "https://example.invalid/1.21.1.json"},
            {"id": "1.20.1", "type": "release", "url": "https://example.invalid/1.20.1.json"},
        ],
    )
    monkeypatch.setattr(java_utils.RuntimePaths, "get_version_cache_dir", staticmethod(lambda: tmp_path))

    def fake_fetch(url: str, **_kwargs):
        if "26.2" in url:
            return {"javaVersion": {"majorVersion": 25}}
        if "1.21.1" in url:
            return {"javaVersion": {"majorVersion": 21}}
        if "1.20.1" in url:
            return {"javaVersion": {"majorVersion": 17}}
        if "1.16.5" in url:
            return {"javaVersion": {"majorVersion": 8}}
        return None

    monkeypatch.setattr(java_utils.HTTPClient, "fetch_json", staticmethod(fake_fetch))
    results = JavaUtils.preload_all_java_requirements(force=True)

    expected_order = ["26.2", "1.21.1", "1.20.1", "1.16.5"]
    assert list(results.keys()) == expected_order
    assert results["26.2"] == 25
    assert results["1.16.5"] == 8

    cache_file = tmp_path / JavaUtils.JAVA_REQUIREMENTS_CACHE_FILE_NAME
    cached_on_disk = read_json(cache_file)
    assert list(cached_on_disk.keys()) == expected_order


def test_get_required_java_major_adds_new_version_and_sorts(monkeypatch, tmp_path: Path) -> None:
    cache_file = tmp_path / JavaUtils.JAVA_REQUIREMENTS_CACHE_FILE_NAME
    atomic_write_json(cache_file, {"1.20.1": 17, "1.16.5": 8})
    version_cache = tmp_path / "mc_versions_cache.json"
    atomic_write_json(
        version_cache,
        [
            {"id": "26.2", "url": "https://example.invalid/26.2.json"},
            {"id": "1.20.1", "url": "https://example.invalid/1.20.1.json"},
            {"id": "1.16.5", "url": "https://example.invalid/1.16.5.json"},
        ],
    )
    monkeypatch.setattr(java_utils.RuntimePaths, "get_version_cache_dir", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(
        java_utils.HTTPClient,
        "fetch_json",
        staticmethod(lambda url, **_kwargs: {"javaVersion": {"majorVersion": 25}} if "26.2" in url else None),
    )
    JavaUtils.get_required_java_major.cache_clear()

    # 現有快取直接回傳
    assert JavaUtils.get_required_java_major("1.20.1") == 17

    # 遇到未收錄之新版本 26.2，單獨抓取並依照版本由新到舊排序
    JavaUtils.get_required_java_major.cache_clear()
    assert JavaUtils.get_required_java_major("26.2") == 25

    cached_on_disk = read_json(cache_file)
    assert list(cached_on_disk.keys()) == ["26.2", "1.20.1", "1.16.5"]


def test_requirements_cache_cleans_extra_and_invalid_entries(monkeypatch, tmp_path: Path) -> None:
    cache_file = tmp_path / JavaUtils.JAVA_REQUIREMENTS_CACHE_FILE_NAME
    dirty_data = {
        "extra_key": "some_value",
        "candidates": [{"path": "C:\\javaw.exe", "major": 17}],
        "settings": {"auto": True},
        "invalid_version_xyz": 17,
        "1.21.1": 21,
        "1.20.1": 17,
        "1.16.5": "8",
        "1.12.2": -1,
        "1.19.4": True,
        "not-a-version": 8,
    }
    atomic_write_json(cache_file, dirty_data)

    version_cache = tmp_path / "mc_versions_cache.json"
    atomic_write_json(
        version_cache,
        [
            {"id": "1.21.1", "url": "https://example.invalid/1.21.1.json"},
            {"id": "1.20.1", "url": "https://example.invalid/1.20.1.json"},
        ],
    )
    monkeypatch.setattr(java_utils.RuntimePaths, "get_version_cache_dir", staticmethod(lambda: tmp_path))

    JavaUtils.get_required_java_major.cache_clear()
    assert JavaUtils.get_required_java_major("1.21.1") == 21

    # 驗證磁碟上的快取檔案已自動剔除所有多餘與不合法項目
    cleaned_on_disk = read_json(cache_file)
    assert cleaned_on_disk == {"1.21.1": 21, "1.20.1": 17}
    assert list(cleaned_on_disk.keys()) == ["1.21.1", "1.20.1"]
