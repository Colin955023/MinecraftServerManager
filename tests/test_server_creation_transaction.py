from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import src.core.server.server_creation as server_creation_module
from src.core import CreateServerJourney, ServerCRUD, ServerPropertiesStore
from src.models import LoaderInstallerArtifact, ServerConfig
from src.utils import ServerCommands, atomic_write_json


class _FakeLoader:
    def __init__(self, *, artifact: LoaderInstallerArtifact | None = None, outcome: bool = True) -> None:
        self.artifact = artifact
        self.outcome = outcome
        self.received_artifact: LoaderInstallerArtifact | None = None

    def resolve_installer_artifact(self, *_args: Any) -> LoaderInstallerArtifact | None:
        return self.artifact

    def download_server_jar_with_progress(
        self,
        _loader_type: str,
        _minecraft_version: str,
        _loader_version: str,
        download_path: str,
        _progress_callback: Any,
        cancel_check: Any,
        _user_java_path: str | None,
        *,
        installer_artifact: LoaderInstallerArtifact | None,
    ) -> bool:
        self.received_artifact = installer_artifact
        if cancel_check() or not self.outcome:
            return False
        Path(download_path).write_bytes(b"server")
        return True


def _config(name: str = "demo", *, loader_type: str = "vanilla") -> ServerConfig:
    return ServerConfig(
        name=name,
        minecraft_version="1.21.1",
        loader_type=loader_type,
        loader_version="0.16.0" if loader_type != "vanilla" else "",
        memory_max_mb=2048,
        memory_min_mb=1024,
        path="",
    )


def test_creation_commits_only_after_complete_instance_is_ready(tmp_path) -> None:
    crud = ServerCRUD(str(tmp_path))
    loader = _FakeLoader()
    service = CreateServerJourney(crud, loader)
    plan = service.plan(_config())

    result = service.execute(plan)

    assert result.completed is True
    assert result.config is crud.servers["demo"]
    final_path = tmp_path / "demo"
    assert (final_path / "server.jar").is_file()
    assert (final_path / "eula.txt").is_file()
    assert (final_path / "server.properties").is_file()
    assert (final_path / ServerCommands.MANAGED_STARTUP_SCRIPT_NAME).is_file()
    assert not (final_path / ".msm-server-creation.json").exists()
    assert not plan.staging_path.exists()


def test_progress_callback_failure_cannot_roll_back_committed_instance(tmp_path) -> None:
    crud = ServerCRUD(str(tmp_path))
    service = CreateServerJourney(crud, _FakeLoader())
    plan = service.plan(_config())

    result = service.execute(
        plan,
        progress_callback=lambda *_args: (_ for _ in ()).throw(RuntimeError("UI disposed")),
    )

    assert result.completed is True
    assert plan.final_path.is_dir()
    assert "demo" in crud.servers


def test_creation_cancellation_cleans_staging_and_does_not_register(tmp_path) -> None:
    crud = ServerCRUD(str(tmp_path))
    service = CreateServerJourney(crud, _FakeLoader())
    plan = service.plan(_config())
    checks = 0

    def cancel_during_download() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    result = service.execute(plan, cancel_check=cancel_during_download)

    assert result.status == "cancelled"
    assert result.cleanup_complete is True
    assert "demo" not in crud.servers
    assert not plan.staging_path.exists()
    assert not plan.final_path.exists()


def test_unverified_installer_requires_explicit_allow_and_reuses_plan_artifact(tmp_path) -> None:
    artifact = LoaderInstallerArtifact("https://example.invalid/installer.jar", None, None)
    crud = ServerCRUD(str(tmp_path))
    loader = _FakeLoader(artifact=artifact)
    service = CreateServerJourney(crud, loader)
    plan = service.plan(_config(loader_type="fabric"))

    refused = service.execute(plan)
    accepted = service.execute(plan, allow_unverified_installer=True)

    assert refused.status == "confirmation_required"
    assert not plan.staging_path.exists()
    assert accepted.completed is True
    assert loader.received_artifact is artifact


def test_creation_cancellation_at_initial_stage_cleans_up(tmp_path) -> None:
    crud = ServerCRUD(str(tmp_path))
    service = CreateServerJourney(crud, _FakeLoader())
    plan = service.plan(_config())

    result = service.execute(plan, cancel_check=lambda: True)

    assert result.status == "cancelled"
    assert result.cleanup_complete is True
    assert "demo" not in crud.servers
    assert not plan.staging_path.exists()
    assert not plan.final_path.exists()


def test_creation_cancellation_after_download_cleans_up(tmp_path) -> None:
    crud = ServerCRUD(str(tmp_path))
    cancel_requested = False

    class _LoaderWithCancelAfterDownload(_FakeLoader):
        def download_server_jar_with_progress(self, *args, **kwargs) -> bool:
            super().download_server_jar_with_progress(*args, **kwargs)
            nonlocal cancel_requested
            cancel_requested = True
            return True

    loader = _LoaderWithCancelAfterDownload()
    service = CreateServerJourney(crud, loader)
    plan = service.plan(_config())

    result = service.execute(plan, cancel_check=lambda: cancel_requested)

    assert result.status == "cancelled"
    assert result.cleanup_complete is True
    assert not plan.staging_path.exists()
    assert not plan.final_path.exists()


def test_checksum_mismatch_failure_rolls_back(tmp_path) -> None:
    class _ChecksumMismatchLoader(_FakeLoader):
        def download_server_jar_with_progress(self, *_args, **_kwargs) -> bool:
            return False

    crud = ServerCRUD(str(tmp_path))
    service = CreateServerJourney(crud, _ChecksumMismatchLoader())
    plan = service.plan(_config(name="mismatch"))

    result = service.execute(plan)

    assert result.status == "failed"
    assert result.diagnostic_id.startswith("server-create-")
    assert result.cleanup_complete is True
    assert "mismatch" not in crud.servers
    assert not plan.staging_path.exists()
    assert not plan.final_path.exists()


def test_installer_nonzero_exit_rolls_back(tmp_path) -> None:
    class _InstallerFailedLoader(_FakeLoader):
        def download_server_jar_with_progress(self, *_args, **_kwargs) -> bool:
            return False

    crud = ServerCRUD(str(tmp_path))
    service = CreateServerJourney(crud, _InstallerFailedLoader())
    plan = service.plan(_config(name="installer-fail", loader_type="fabric"))

    result = service.execute(plan)

    assert result.status == "failed"
    assert result.diagnostic_id.startswith("server-create-")
    assert result.cleanup_complete is True
    assert "installer-fail" not in crud.servers
    assert not plan.staging_path.exists()
    assert not plan.final_path.exists()


def test_disk_space_insufficient_fails_gracefully(tmp_path, monkeypatch) -> None:
    import shutil

    crud = ServerCRUD(str(tmp_path))
    service = CreateServerJourney(crud, _FakeLoader())
    plan = service.plan(_config())

    class _FakeUsage:
        free = 100

    monkeypatch.setattr(shutil, "disk_usage", lambda _p: _FakeUsage())

    result = service.execute(plan)

    assert result.status == "failed"
    assert not plan.staging_path.exists()
    assert not plan.final_path.exists()
    assert "demo" not in crud.servers


def test_launch_script_failure_rolls_back(tmp_path, monkeypatch) -> None:
    crud = ServerCRUD(str(tmp_path))
    service = CreateServerJourney(crud, _FakeLoader())
    plan = service.plan(_config())
    monkeypatch.setattr(crud, "create_launch_script", lambda *_args, **_kwargs: False)

    result = service.execute(plan)

    assert result.status == "failed"
    assert "demo" not in crud.servers
    assert not plan.staging_path.exists()


def test_config_commit_failure_removes_moved_instance_and_registration(tmp_path, monkeypatch) -> None:
    crud = ServerCRUD(str(tmp_path))
    service = CreateServerJourney(crud, _FakeLoader())
    plan = service.plan(_config())
    monkeypatch.setattr(crud, "write_servers_config", lambda: False)

    result = service.execute(plan)

    assert result.status == "failed"
    assert result.cleanup_complete is True
    assert "demo" not in crud.servers
    assert not plan.final_path.exists()


def test_root_change_invalidates_plan_without_touching_original_root(tmp_path) -> None:
    original_root = tmp_path / "original"
    changed_root = tmp_path / "changed"
    crud = ServerCRUD(str(original_root))
    service = CreateServerJourney(crud, _FakeLoader())
    plan = service.plan(_config())
    changed_root.mkdir()
    crud.servers_root = changed_root

    result = service.execute(plan)

    assert result.status == "failed"
    assert not plan.staging_path.exists()
    assert not plan.final_path.exists()


def test_execute_rejects_stale_final_path_before_writing_staging(tmp_path) -> None:
    crud = ServerCRUD(str(tmp_path))
    journey = CreateServerJourney(crud, _FakeLoader())
    plan = journey.plan(_config())
    plan.final_path.mkdir()
    sentinel = plan.final_path / "keep.txt"
    sentinel.write_text("existing", encoding="utf-8")

    result = journey.execute(plan)

    assert result.status == "failed"
    assert sentinel.read_text(encoding="utf-8") == "existing"
    assert not plan.staging_path.exists()
    assert "demo" not in crud.servers


def test_plan_owns_memory_domain_invariants(tmp_path) -> None:
    journey = CreateServerJourney(ServerCRUD(str(tmp_path)), _FakeLoader())
    below_minimum = _config(name="small")
    below_minimum.memory_max_mb = 512
    equal_bounds = _config(name="equal")
    equal_bounds.memory_min_mb = equal_bounds.memory_max_mb

    with pytest.raises(ValueError, match="1024"):
        journey.plan(below_minimum)
    assert journey.plan(equal_bounds).memory_min_mb == equal_bounds.memory_max_mb


def test_server_properties_write_failure_rolls_back_staging(tmp_path, monkeypatch) -> None:
    crud = ServerCRUD(str(tmp_path))
    properties = ServerPropertiesStore(crud)
    journey = CreateServerJourney(crud, _FakeLoader(), properties)
    plan = journey.plan(_config())

    def _fail_write(*_args, **_kwargs):
        raise OSError("properties write failed")

    monkeypatch.setattr(properties, "write_initial", _fail_write)
    result = journey.execute(plan)

    assert result.status == "failed"
    assert result.cleanup_complete is True
    assert not plan.staging_path.exists()
    assert "demo" not in crud.servers


def test_cleanup_failure_is_reported_without_private_journey_access(tmp_path, monkeypatch) -> None:
    crud = ServerCRUD(str(tmp_path))
    journey = CreateServerJourney(crud, _FakeLoader(outcome=False))
    plan = journey.plan(_config())
    monkeypatch.setattr(server_creation_module, "delete_within", lambda *_args, **_kwargs: False)

    result = journey.execute(plan)

    assert result.status == "failed"
    assert result.cleanup_complete is False
    assert plan.staging_path.is_dir()


def test_orphan_recovery_removes_staging_and_unregistered_final(tmp_path) -> None:
    crud = ServerCRUD(str(tmp_path))
    staging = tmp_path / ".msm-create-deadbeef.staging"
    orphan_final = tmp_path / "orphan"
    staging.mkdir()
    orphan_final.mkdir()
    atomic_write_json(staging / ".msm-server-creation.json", {"state": "staging"})
    atomic_write_json(orphan_final / ".msm-server-creation.json", {"state": "moved"})

    CreateServerJourney(crud, _FakeLoader())

    assert not staging.exists()
    assert not orphan_final.exists()


def test_orphan_recovery_preserves_registered_instance_and_removes_marker(tmp_path) -> None:
    crud = ServerCRUD(str(tmp_path))
    final_path = tmp_path / "registered"
    final_path.mkdir()
    marker = final_path / ".msm-server-creation.json"
    atomic_write_json(marker, {"state": "moved"})
    config = _config(name="registered")
    config.path = str(final_path)
    crud.servers[config.name] = config

    CreateServerJourney(crud, _FakeLoader())

    assert final_path.is_dir()
    assert not marker.exists()
