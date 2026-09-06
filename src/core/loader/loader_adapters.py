"""Loader 差異規格與純轉換規則"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.version import Version

from src.utils import is_fabric_compatible_version, list_bounded_directory, parse_version_safe


@dataclass(frozen=True, slots=True)
class LoaderVersion:
    """LoaderManager 對外回傳的載入器版本"""

    version: str
    url: str | None = None
    stable: bool | None = None
    mc_version: str | None = None
    game_versions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LoaderInstallerArtifact:
    """建立流程固定使用的 Loader installer 與校驗資訊"""

    url: str
    expected_hash: str | None = None
    hash_algorithm: str | None = None
    version: str = ""


@dataclass(frozen=True, slots=True)
class InstallerCommandContext:
    """提供給各 Loader installer 命令策略的必要資料"""

    java_path: str
    minecraft_version: str
    loader_version: str
    installer_path: str


@dataclass(frozen=True, slots=True)
class LoaderAdapter:
    """各 Loader 的來源、安裝器與版本規則"""

    id: str
    cache_name: str
    api_url: str | None = None
    stable_only: bool = True
    keep_latest: int | None = None
    installer_url_factory: Callable[[], str | None] | None = None
    installer_url_template: str | None = None
    installer_args: Callable[[InstallerCommandContext], list[str]] | None = None
    needs_vanilla: bool = False
    candidate_keys: Callable[[str], list[str]] | None = None
    normalize_loader_version: Callable[[str, str], str] | None = None
    parse_fallback_full_version: bool = False
    direct_download: bool = False
    filter_versions: Callable[[list[dict]], list[dict]] | None = None
    compatibility_guard: Callable[[str], bool] | None = None
    post_install_result: Callable[[Path, str], str | None] | None = None
    metadata_loader: Callable[[LoaderAdapter], Any] | None = None
    compatible_version_loader: Callable[[LoaderAdapter, str, Any], list[LoaderVersion]] | None = None


def filter_fabric_versions(items: list[dict]) -> list[dict]:
    """
    保留 Fabric 穩定版本

    Args:
        items: API 回傳的版本資料

    Returns:
        只包含穩定版本的資料列表
    """
    return [item for item in items if item.get("stable", False)]


def filter_quilt_versions(items: list[dict]) -> list[dict]:
    """
    挑選 Quilt 最新穩定版本

    Args:
        items: API 回傳的版本資料

    Returns:
        依版本與建置編號排序後的最新版本列表
    """
    stable = [item for item in items if item.get("stable", False)]
    if not stable:
        unstable_markers = ("pre", "prelease", "beta", "alpha", "snapshot", "rc")
        stable = [
            item
            for item in items
            if item.get("version") and not any(marker in str(item["version"]).lower() for marker in unstable_markers)
        ]
    stable.sort(
        key=lambda item: (
            parse_version_safe(str(item.get("version", "")), fallback=Version("0.0.0")),
            int(item.get("build", 0) or 0),
        ),
        reverse=True,
    )
    return stable[:1]


def build_neoforge_mc_version_candidates(mc_version: str) -> list[str]:
    """
    建立 NeoForge 查詢 Minecraft 版本的候選鍵

    Args:
        mc_version: Minecraft 版本字串

    Returns:
        去除重複後的版本候選鍵
    """
    normalized = str(mc_version or "").strip()
    if not normalized:
        return []

    candidates = [normalized]
    parts = normalized.split(".")
    if len(parts) >= 2:
        candidates.append(f"{parts[0]}.{parts[1]}")
    if len(parts) >= 3:
        candidates.append(".".join(parts[:3]))

    if normalized.startswith("1."):
        tail = normalized[2:]
        if tail:
            candidates.append(tail)
        tail_parts = tail.split(".") if tail else []
        if tail_parts and tail_parts[0].isdigit() and int(tail_parts[0]) >= 20:
            candidates.append(f"{tail_parts[0]}.0" if len(tail_parts) == 1 else f"{tail_parts[0]}.{tail_parts[1]}")
            if len(tail_parts) >= 2:
                candidates.append(f"{tail_parts[0]}.{tail_parts[1]}.0.0")
    elif len(parts) >= 2 and parts[0].isdigit() and int(parts[0]) >= 20:
        candidates.extend((f"1.{parts[0]}.{parts[1]}", f"1.{normalized}", f"{parts[0]}.{parts[1]}.0.0"))
        candidates.append(f"1.{parts[0]}")
    elif len(parts) >= 2 and all(part.isdigit() for part in parts[:2]):
        candidates.append(f"{parts[0]}.{parts[1]}.0.0")

    return list(dict.fromkeys(candidates))


def normalize_neoforge_loader_version(matched_key: str, loader_version: str) -> str:
    """
    依匹配到的 Minecraft 鍵補齊 NeoForge 版本前綴

    Args:
        matched_key: 實際匹配到的 Minecraft 版本鍵
        loader_version: 原始 Loader 版本

    Returns:
        可供下載使用的完整 Loader 版本
    """
    return loader_version if "." in loader_version else f"{matched_key}.{loader_version}"


def resolve_forge_install_result(base_dir: Path, loader_type: str) -> str | None:
    """
    解析 Forge 類 installer 完成後可用的啟動目標

    Args:
        base_dir: 安裝器工作的伺服器目錄
        loader_type: Loader 類型名稱

    Returns:
        可用的啟動檔名，找不到時回傳 None
    """
    if (base_dir / "run.bat").exists():
        return "run.bat"
    try:
        jar_entries = [
            entry for entry in list_bounded_directory(base_dir) if entry.is_file() and entry.suffix.lower() == ".jar"
        ]
    except OSError:
        jar_entries = []
    normalized_loader_type = loader_type.lower()
    loader_jars = [entry for entry in jar_entries if entry.name.lower().startswith(normalized_loader_type)]
    for jar in loader_jars or jar_entries:
        if normalized_loader_type in jar.name.lower() and "installer" not in jar.name.lower():
            return jar.name
    if (base_dir / "win_args.txt").exists() or (base_dir / "user_jvm_args.txt").exists():
        return "run.bat"
    return None


def resolve_installer_url(spec: LoaderAdapter, minecraft_version: str, loader_version: str) -> str | None:
    """
    依 Loader 規格產生 installer 下載網址

    Args:
        spec: Loader 的來源與下載規格
        minecraft_version: Minecraft 版本
        loader_version: Loader 版本

    Returns:
        Installer 網址，規格未提供網址時回傳 None
    """
    if spec.installer_url_factory is not None:
        return spec.installer_url_factory()
    if spec.installer_url_template is not None:
        return spec.installer_url_template.format(
            minecraft_version=minecraft_version,
            loader_version=loader_version,
        )
    return None


def build_loader_adapters(manager: Any) -> dict[str, LoaderAdapter]:
    """
    建立綁定目前 LoaderManager 的 Loader 規格

    Args:
        manager: 提供資料載入與版本解析回呼的 LoaderManager

    Returns:
        以 Loader 類型為鍵的規格字典
    """
    return {
        "vanilla": LoaderAdapter(
            id="vanilla",
            cache_name="mc_versions_cache.json",
            api_url="https://piston-meta.mojang.com/mc/game/version_manifest.json",
            direct_download=True,
            metadata_loader=manager._fetch_minecraft_versions,
            compatible_version_loader=manager._compatible_direct_versions,
        ),
        "fabric": LoaderAdapter(
            id="fabric",
            cache_name="fabric_versions_cache.json",
            api_url="https://meta.fabricmc.net/v2/versions/loader",
            needs_vanilla=True,
            metadata_loader=manager._fetch_json_versions,
            compatible_version_loader=manager._compatible_json_versions,
            filter_versions=filter_fabric_versions,
            compatibility_guard=is_fabric_compatible_version,
            installer_url_factory=manager._fabric_installer_url,
            installer_args=lambda context: [
                context.java_path,
                "-Dfile.encoding=UTF-8",
                "-Dsun.stdout.encoding=UTF-8",
                "-Dsun.stderr.encoding=UTF-8",
                "-jar",
                context.installer_path,
                "server",
                "-mcversion",
                context.minecraft_version,
                "-loader",
                context.loader_version,
                "-dir",
                "{base_dir}",
            ],
        ),
        "quilt": LoaderAdapter(
            id="quilt",
            cache_name="quilt_versions_cache.json",
            api_url="https://meta.quiltmc.org/v3/versions/loader",
            keep_latest=1,
            needs_vanilla=True,
            metadata_loader=manager._fetch_json_versions,
            compatible_version_loader=manager._compatible_json_versions,
            filter_versions=filter_quilt_versions,
            installer_url_factory=manager._quilt_installer_url,
            installer_args=lambda context: [
                context.java_path,
                "-Dfile.encoding=UTF-8",
                "-Dsun.stdout.encoding=UTF-8",
                "-Dsun.stderr.encoding=UTF-8",
                "-jar",
                context.installer_path,
                "install",
                "server",
                context.minecraft_version,
                context.loader_version,
                "--install-dir={base_dir}",
            ],
        ),
        "forge": LoaderAdapter(
            id="forge",
            cache_name="forge_versions_cache.json",
            api_url="https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml",
            metadata_loader=manager._fetch_maven_versions,
            compatible_version_loader=manager._compatible_maven_versions,
            installer_url_template=(
                "https://maven.minecraftforge.net/net/minecraftforge/forge/"
                "{minecraft_version}-{loader_version}/forge-{minecraft_version}-{loader_version}-installer.jar"
            ),
            installer_args=lambda context: [
                context.java_path,
                "-Dfile.encoding=UTF-8",
                "-Dsun.stdout.encoding=UTF-8",
                "-Dsun.stderr.encoding=UTF-8",
                "-jar",
                context.installer_path,
                "--installServer",
            ],
            post_install_result=resolve_forge_install_result,
        ),
        "neoforge": LoaderAdapter(
            id="neoforge",
            cache_name="neoforge_versions_cache.json",
            api_url="https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml",
            metadata_loader=manager._fetch_maven_versions,
            compatible_version_loader=manager._compatible_maven_versions,
            stable_only=False,
            parse_fallback_full_version=True,
            installer_url_template=(
                "https://maven.neoforged.net/releases/net/neoforged/neoforge/"
                "{loader_version}/neoforge-{loader_version}-installer.jar"
            ),
            installer_args=lambda context: [
                context.java_path,
                "-Dfile.encoding=UTF-8",
                "-Dsun.stdout.encoding=UTF-8",
                "-Dsun.stderr.encoding=UTF-8",
                "-jar",
                context.installer_path,
                "--installServer",
            ],
            post_install_result=resolve_forge_install_result,
            candidate_keys=build_neoforge_mc_version_candidates,
            normalize_loader_version=normalize_neoforge_loader_version,
        ),
    }


__all__ = ["LoaderInstallerArtifact", "LoaderVersion"]
