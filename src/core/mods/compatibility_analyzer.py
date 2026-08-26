"""本地模組 metadata 的純相容性提示"""

from __future__ import annotations

from typing import Any

from src.utils import is_supported_modrinth_update_loader, normalize_local_loader


def analyze_local_mod_file_compatibility(local_mod: Any, loader: str | None = None) -> list[str]:
    """
    以本地模組已知 metadata 產生輔助提示

    Args:
        local_mod: 待分析的本地模組
        loader: 目標載入器類型

    Returns:
        不阻擋流程的相容性提示
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
        and normalized_local_loader != normalized_target_loader
    ):
        advisories.append(f"{local_name} 目前本地 metadata 顯示載入器為 {local_loader}，與伺服器的 {loader} 不一致")
    if not local_version or local_version == "未知":
        advisories.append(f"{local_name} 的本地版本資訊未知，無法精準判斷是否已是最新版本")
    return advisories


__all__ = ["analyze_local_mod_file_compatibility"]
