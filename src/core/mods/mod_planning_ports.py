"""模組規劃所擁有的外部查詢 ports"""

from __future__ import annotations

from typing import Protocol


class LoaderManagerRulesAdapter:
    """將 LoaderManager 的相容版本結果投影給模組規劃"""

    def __init__(self, loader_manager) -> None:
        self._loader_manager = loader_manager

    def compatible_versions(self, minecraft_version: str, loader: str) -> list[str]:
        """
        取得指定 Minecraft 與載入器的相容版本

        Args:
            minecraft_version: 目標 Minecraft 版本
            loader: 目標載入器類型

        Returns:
            相容的載入器版本列表
        """
        return [
            version.version
            for version in self._loader_manager.get_compatible_loader_versions(minecraft_version, loader)
            if version.version
        ]


class LoaderRulesPort(Protocol):
    """投影模組規劃所需的本機載入器版本規則"""

    def compatible_versions(self, minecraft_version: str, loader: str) -> list[str]: ...


__all__ = ["LoaderManagerRulesAdapter", "LoaderRulesPort"]
