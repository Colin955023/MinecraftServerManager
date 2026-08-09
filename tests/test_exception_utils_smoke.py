from __future__ import annotations

from src.utils import ExceptionUtils, PathUtils


def test_record_and_mark_without_marker_path_still_writes_runtime_issue_marker() -> None:
    try:
        raise RuntimeError("runtime marker smoke")
    except RuntimeError as exc:
        ExceptionUtils.record_and_mark(exc)

    markers = PathUtils.list_issue_markers()
    runtime_markers = [entry for entry in markers if entry.get("marker", "").endswith(".runtime_issues.issue.json")]

    assert runtime_markers
    payload = runtime_markers[0]["data"]
    assert isinstance(payload, dict)
    assert payload.get("entries")
    assert payload["entries"][-1]["exception_type"] == "RuntimeError"
