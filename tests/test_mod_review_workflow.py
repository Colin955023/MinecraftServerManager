from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.ui import (
    ReviewExecutionHandoff,
    ReviewInstallStep,
    build_review_context_stamp,
    describe_context_mismatch,
)


def _server(**overrides: str) -> SimpleNamespace:
    values = {
        "name": "Fabric",
        "path": "C:/servers/Fabric",
        "minecraft_version": "1.21.1",
        "loader_type": "fabric",
        "loader_version": "0.16.0",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _handoff() -> ReviewExecutionHandoff:
    return ReviewExecutionHandoff(
        mode="online_install",
        context_stamp=build_review_context_stamp(_server(), []),
        steps=(
            ReviewInstallStep(
                kind="online_root",
                root_key="sodium",
                project_name="Sodium",
                version_name="mc1.21.1",
                download_url="https://cdn.example/sodium.jar",
                filename="sodium.jar",
                expected_hash="abc",
                provider="modrinth",
            ),
        ),
        root_keys=("sodium",),
        confirmation_prompt="確認安裝",
        source_confirmation_prompt="",
        skipped_text="",
        completion_notes="",
        disabled_count=0,
        dependency_count=0,
        duplicate_dependency_count=0,
    )


def test_execution_handoff_and_steps_are_immutable() -> None:
    handoff = _handoff()

    with pytest.raises(FrozenInstanceError):
        cast(Any, handoff).mode = "local_update"
    with pytest.raises(FrozenInstanceError):
        cast(Any, handoff.steps[0]).filename = "changed.jar"


def test_context_stamp_rejects_changed_loader_context() -> None:
    expected = build_review_context_stamp(_server(), [])
    actual = build_review_context_stamp(_server(loader_version="0.17.0"), [])

    assert describe_context_mismatch(expected, actual) == "Loader context 已變更"


def test_context_stamp_rejects_changed_installed_mod_revision(tmp_path) -> None:
    mod_path = tmp_path / "sodium.jar"
    mod_path.write_bytes(b"first")
    mod = SimpleNamespace(
        file_path=str(mod_path),
        filename=mod_path.name,
        current_hash="first-hash",
        version="1.0.0",
        status="enabled",
        file_size=5,
    )
    expected = build_review_context_stamp(_server(), [mod])
    mod.current_hash = "second-hash"
    actual = build_review_context_stamp(_server(), [mod])

    assert describe_context_mismatch(expected, actual) == "本機 Mod 清單已變更"
