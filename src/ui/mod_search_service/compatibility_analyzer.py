"""Mod 相容性分析。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...core import LoaderManager
from ...models import OnlineModVersion, ResolvedDependencyReference
from ...utils import (
    collect_installed_mod_identifiers,
    collect_installed_mod_versions,
    dependency_maybe_installed_by_filename,
    is_supported_modrinth_update_loader,
    normalize_identifier,
    normalize_local_loader,
    resolve_dependency_reference,
)
from .constants import logger
from .models import OnlineModCompatibilityReport
from .modrinth_service import fetch_modrinth_project_name, get_mod_version_details


def resolve_dependency_reference_with_provider_context(
    dependency: dict[str, Any],
    dependency_names: dict[str, str],
    *,
    version_details_cache: dict[str, tuple[str, OnlineModVersion | None]] | None = None,
    get_mod_version_details_fn: Callable[[str], tuple[str, OnlineModVersion | None]] | None = None,
    fetch_project_name_fn: Callable[[str], str | None] | None = None,
) -> ResolvedDependencyReference:
    """補上 provider 查詢能力後解析單筆依賴參照。

    Args:
        dependency: 原始依賴描述資料。
        dependency_names: 依賴名稱對照表。
        version_details_cache: 版本詳情快取，避免重複查詢。
        get_mod_version_details_fn: 由呼叫端注入的版本詳情查詢函式。
        fetch_project_name_fn: 由呼叫端注入的專案名稱查詢函式。

    Returns:
        已補齊 provider 上下文的依賴解析結果。
    """
    return resolve_dependency_reference(
        dependency,
        dependency_names,
        version_details_cache=version_details_cache,
        get_mod_version_details=get_mod_version_details_fn or get_mod_version_details,
        fetch_project_name=fetch_project_name_fn or fetch_modrinth_project_name,
    )


def _check_loader_version_rule(
    minecraft_version: str | None, loader: str | None, loader_version: str | None
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    notes: list[str] = []
    normalized_minecraft_version = str(minecraft_version or "").strip()
    normalized_loader = normalize_identifier(loader)
    normalized_loader_version = normalize_identifier(loader_version)
    if not normalized_minecraft_version or not normalized_loader or (not normalized_loader_version):
        return (warnings, notes)
    try:
        compatible_versions = LoaderManager().get_compatible_loader_versions(
            normalized_minecraft_version, normalized_loader
        )
    except Exception as e:
        logger.warning(f"讀取 {normalized_loader} 載入器規則失敗: {e}")
        return (warnings, notes)
    available_versions = {normalize_identifier(version.version) for version in compatible_versions if version.version}
    if not available_versions:
        notes.append(
            f"目前找不到 {normalized_loader} 對 Minecraft {normalized_minecraft_version} 的本地規則快取，因此無法額外驗證 loader 版本 {loader_version}。"
        )
        return (warnings, notes)
    if normalized_loader_version in available_versions:
        notes.append(
            f"已使用內建 {normalized_loader.capitalize()} 規則確認 loader 版本 {loader_version} 適用於 Minecraft {normalized_minecraft_version}。"
        )
    else:
        warnings.append(
            f"目前伺服器設定的 {normalized_loader.capitalize()} loader 版本 {loader_version} 不在 Minecraft {normalized_minecraft_version} 的已知可用清單內，系統將維持安全檢查模式。"
        )
    return (warnings, notes)


def analyze_mod_version_compatibility(
    version: OnlineModVersion,
    project_id: str = "",
    project_name: str = "",
    minecraft_version: str | None = None,
    loader: str | None = None,
    loader_version: str | None = None,
    installed_mods: list[Any] | None = None,
    dependency_names: dict[str, str] | None = None,
    get_mod_version_details_fn: Callable[[str], tuple[str, OnlineModVersion | None]] | None = None,
    fetch_project_name_fn: Callable[[str], str | None] | None = None,
) -> OnlineModCompatibilityReport:
    """根據目前伺服器與已安裝模組分析可用版本的相容性。

    Args:
        version: Modrinth 版本資訊。
        project_id: 模組 project id。
        project_name: 模組名稱。
        minecraft_version: 目標 Minecraft 版本。
        loader: 目標載入器類型。
        loader_version: 目標載入器版本。
        installed_mods: 已安裝模組清單。
        dependency_names: 依賴名稱對照表。
        get_mod_version_details_fn: 由呼叫端注入的版本詳情查詢函式。
        fetch_project_name_fn: 由呼叫端注入的專案名稱查詢函式。

    Returns:
        相容性分析報告。
    """
    report = OnlineModCompatibilityReport()
    dependency_name_map = dependency_names or {}
    normalized_minecraft_version = normalize_identifier(minecraft_version)
    normalized_loader = normalize_local_loader(loader)
    compatible_loaders = {normalized_loader} if normalized_loader else set()
    version_game_versions = {normalize_identifier(entry) for entry in version.game_versions if entry}
    version_loaders = {normalize_identifier(entry) for entry in version.loaders if entry}
    if (
        normalized_minecraft_version
        and version_game_versions
        and (normalized_minecraft_version not in version_game_versions)
    ):
        report.hard_errors.append(
            f"此版本支援的 Minecraft 版本為 {', '.join(version.game_versions)}，不符合目前伺服器的 {minecraft_version}。"
        )
    if compatible_loaders and version_loaders and compatible_loaders.isdisjoint(version_loaders):
        report.hard_errors.append(f"此版本支援的載入器為 {', '.join(version.loaders)}，不符合目前伺服器的 {loader}。")
    if not version.primary_file:
        report.hard_errors.append("此版本沒有可下載的 JAR 檔案。")
    rule_warnings, rule_notes = _check_loader_version_rule(minecraft_version, loader, loader_version)
    report.warnings.extend(rule_warnings)
    report.notes.extend(rule_notes)
    installed_project_ids, installed_identifiers = collect_installed_mod_identifiers(installed_mods)
    installed_versions_by_project = collect_installed_mod_versions(installed_mods)
    version_details_cache: dict[str, tuple[str, OnlineModVersion | None]] = {}
    normalized_project_id = normalize_identifier(project_id)
    if normalized_project_id and normalized_project_id in installed_project_ids:
        existing_name = project_name or normalized_project_id
        report.already_installed.append(existing_name)
        report.warnings.append(f"目前伺服器已安裝 {existing_name}，系統會以安全策略避免重複安裝。")
    for dependency in version.dependencies:
        if not isinstance(dependency, dict):
            continue
        dependency_type = normalize_identifier(str(dependency.get("dependency_type", "required") or "required"))
        resolved_dependency = resolve_dependency_reference_with_provider_context(
            dependency,
            dependency_name_map,
            version_details_cache=version_details_cache,
            get_mod_version_details_fn=get_mod_version_details_fn,
            fetch_project_name_fn=fetch_project_name_fn,
        )
        dependency_project_id = resolved_dependency.compare_project_id
        dependency_label = resolved_dependency.label
        normalized_label = normalize_identifier(dependency_label)
        is_installed = False
        has_required_version = True
        if (dependency_project_id and dependency_project_id in installed_project_ids) or (
            normalized_label and normalized_label in installed_identifiers
        ):
            is_installed = True
        maybe_installed = False
        if not is_installed:
            maybe_installed = dependency_maybe_installed_by_filename(resolved_dependency, installed_mods)
        required_version = normalize_identifier(
            getattr(resolved_dependency.version, "version_number", "") or resolved_dependency.version_name
        )
        installed_versions = sorted(installed_versions_by_project.get(dependency_project_id, set()))
        if is_installed and required_version:
            has_required_version = required_version in installed_versions
        if dependency_type == "required" and is_installed and required_version and (not has_required_version):
            installed_version_text = ", ".join(installed_versions) if installed_versions else "未知版本"
            mismatch_message = f"{dependency_label} 目前已安裝，但版本為 {installed_version_text}，與需求版本 {resolved_dependency.version_name or required_version} 不符。"
            report.installed_version_mismatches.append(mismatch_message)
            report.warnings.append(mismatch_message)
            report.missing_required_dependencies.append(dependency_label)
            continue
        if dependency_type == "required":
            if not is_installed:
                report.missing_required_dependencies.append(dependency_label)
                if maybe_installed:
                    report.notes.append(f"{dependency_label} 可能已存在本地相近檔名，系統已先採安全略過策略。")
                    report.warnings.append(f"必要依賴可能已存在但尚未能以 metadata 精確識別：{dependency_label}")
                else:
                    report.warnings.append(f"缺少必要依賴：{dependency_label}")
        elif dependency_type == "optional":
            if not is_installed:
                report.optional_dependencies.append(dependency_label)
        elif dependency_type == "incompatible":
            if is_installed:
                report.incompatible_installed.append(dependency_label)
                incompatible_message = f"偵測到已安裝的不相容模組：{dependency_label}"
                report.hard_errors.append(incompatible_message)
                report.warnings.append(incompatible_message)
        elif dependency_type == "embedded":
            report.embedded_dependencies.append(dependency_label)
        elif not is_installed:
            report.notes.append(f"依賴 {dependency_label} 的類型為 {dependency_type}，系統已先採安全保守策略。")
    return report


def analyze_local_mod_file_compatibility(local_mod: Any, loader: str | None = None) -> list[str]:
    """以本地模組已知 metadata 產生輔助提示。

    Args:
        local_mod: 本地模組物件。
        loader: 目標載入器類型。

    Returns:
        提示與警告清單。

    本地 jar 解析出的 Minecraft 版本常已失去 range 語意，只適合作為提示，
    不適合直接當成更新可行性的判定依據。
    """
    advisories: list[str] = []
    if not is_supported_modrinth_update_loader(loader):
        return advisories
    local_name = str(getattr(local_mod, "name", "") or getattr(local_mod, "filename", "模組")).strip() or "模組"
    local_loader = str(getattr(local_mod, "loader_type", "") or "").strip()
    local_version = str(getattr(local_mod, "version", "") or "").strip()
    normalized_local_loader = normalize_local_loader(local_loader)
    normalized_target_loader = normalize_local_loader(loader)
    if (
        normalized_local_loader
        and normalized_local_loader not in {"", "未知", "unknown"}
        and normalized_target_loader
        and (normalized_local_loader != normalized_target_loader)
    ):
        advisories.append(f"{local_name} 目前本地 metadata 顯示載入器為 {local_loader}，與伺服器的 {loader} 不一致。")
    if not local_version or local_version == "未知":
        advisories.append(f"{local_name} 的本地版本資訊未知，無法精準判斷是否已是最新版本。")
    return advisories


__all__ = [
    "OnlineModCompatibilityReport",
    "analyze_local_mod_file_compatibility",
    "analyze_mod_version_compatibility",
]
