"""Mod Review workflow 的不可變外部契約"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any

from src.models import (
    ReviewContextStamp,
    ReviewExecutionHandoff,
    ReviewInstallStep,
    ReviewRootView,
    ReviewTaskView,
    ReviewViewSnapshot,
)


def normalize_status_value(value: Any) -> str:
    """
    將 enum 或字串狀態轉為小寫穩定值

    Args:
        value: Enum、字串或其他狀態值

    Returns:
        去除空白並轉為小寫的狀態字串
    """
    return str(getattr(value, "value", value) or "").strip().lower()


def _mod_revision_item(mod: Any) -> tuple[str, str, str, str, int, int]:
    file_path = str(getattr(mod, "file_path", "") or "").strip()
    resolved_path = str(Path(file_path).resolve(strict=False)) if file_path else ""
    size = int(getattr(mod, "file_size", 0) or 0)
    modified_ns = 0
    with suppress(OSError):
        if file_path:
            stat_result = Path(file_path).stat()
            size = stat_result.st_size
            modified_ns = stat_result.st_mtime_ns
    return (
        resolved_path or str(getattr(mod, "filename", "") or "").strip(),
        str(getattr(mod, "current_hash", "") or "").strip().lower(),
        str(getattr(mod, "version", "") or "").strip(),
        normalize_status_value(getattr(mod, "status", "")),
        size,
        modified_ns,
    )


def build_review_context_stamp(server: Any, installed_mods: list[Any]) -> ReviewContextStamp:
    """
    由伺服器與已安裝 Mod 建立執行前 context stamp

    Args:
        server: 目前伺服器設定
        installed_mods: 目前已安裝 Mod 清單

    Returns:
        可在 handoff 執行前重新比對的不可變 stamp
    """
    server_path = str(getattr(server, "path", "") or "").strip()
    server_identity = str(Path(server_path).resolve(strict=False)) if server_path else ""
    if not server_identity:
        server_identity = str(getattr(server, "name", "") or "").strip()
    return ReviewContextStamp(
        server_identity=server_identity,
        minecraft_version=str(getattr(server, "minecraft_version", "") or "").strip(),
        loader_type=str(getattr(server, "loader_type", "") or "").strip().lower(),
        loader_version=str(getattr(server, "loader_version", "") or "").strip(),
        installed_mod_revision=tuple(sorted(_mod_revision_item(mod) for mod in installed_mods)),
    )


def describe_context_mismatch(expected: ReviewContextStamp, actual: ReviewContextStamp) -> str:
    """
    描述兩個 Review context 最先出現的差異

    Args:
        expected: Review 建立時的 context
        actual: 執行前重新取得的 context

    Returns:
        使用者可讀的失效原因；完全相符時回傳空字串
    """
    if expected.server_identity != actual.server_identity:
        return "目標伺服器已變更"
    if expected.minecraft_version != actual.minecraft_version:
        return "Minecraft 版本已變更"
    if expected.loader_type != actual.loader_type or expected.loader_version != actual.loader_version:
        return "Loader context 已變更"
    if expected.installed_mod_revision != actual.installed_mod_revision:
        return "本機 Mod 清單已變更"
    return ""


__all__ = [
    "ReviewContextStamp",
    "ReviewExecutionHandoff",
    "ReviewInstallStep",
    "ReviewRootView",
    "ReviewTaskView",
    "ReviewViewSnapshot",
    "build_review_context_stamp",
    "describe_context_mismatch",
    "normalize_status_value",
]
