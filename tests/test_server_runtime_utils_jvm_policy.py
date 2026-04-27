from __future__ import annotations

from pathlib import Path

import pytest
import src.utils.server_utils.server_runtime_utils as runtime_utils_module
from src.models import ServerConfig
from src.utils import JvmOptionPolicy, ServerCommands


@pytest.mark.smoke
def test_jvm_policy_recommends_g1gc_for_memory_above_4gb() -> None:
    assert JvmOptionPolicy.recommend_gc_args(memory_max_mb=4097) == ["-XX:+UseG1GC"]


@pytest.mark.smoke
def test_jvm_policy_recommends_zgc_for_low_latency_java_17() -> None:
    assert JvmOptionPolicy.recommend_gc_args(
        memory_max_mb=2048,
        java_major=17,
        performance_profile="low_latency",
    ) == ["-XX:+UseZGC"]


@pytest.mark.smoke
def test_jvm_policy_keeps_existing_gc_option() -> None:
    assert (
        JvmOptionPolicy.recommend_gc_args(
            memory_max_mb=8192,
            java_major=21,
            performance_profile="low_latency",
            existing_args=["-XX:+UseShenandoahGC"],
        )
        == []
    )


@pytest.mark.smoke
def test_build_java_command_includes_recommended_gc(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    server_jar = tmp_path / "server.jar"
    server_jar.write_bytes(b"jar")
    config = ServerConfig(
        name="alpha",
        minecraft_version="1.21.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=8192,
        path=str(tmp_path),
    )

    monkeypatch.setattr(
        runtime_utils_module.JavaUtils, "get_best_java_path", staticmethod(lambda *_args, **_kwargs: None)
    )

    command = ServerCommands.build_java_command(config, return_list=True)

    assert command[:2] == ["java", "-XX:+UseG1GC"]
    assert "-Xmx8192M" in command
