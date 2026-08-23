"""應用服務編排：持有 core 服務，MainWindow 只做導航與綁定"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.core import (
    LoaderManager,
    ServerBackupManager,
    ServerCRUD,
    ServerImportService,
    ServerStartup,
)


@dataclass
class ApplicationShell:
    """伺服器根目錄下的 core 服務集合"""

    servers_root: str
    loader_manager: LoaderManager
    server_crud: ServerCRUD
    server_import: ServerImportService
    server_startup: ServerStartup
    server_backup: ServerBackupManager

    @classmethod
    def create(cls, servers_root: str) -> ApplicationShell:
        """
        建立 ApplicationShell 實例

        Args:
            servers_root: 伺服器根目錄路徑

        Returns:
            建立好的 ApplicationShell 實例
        """
        crud = ServerCRUD(servers_root=servers_root)
        return cls(
            servers_root=servers_root,
            loader_manager=LoaderManager(),
            server_crud=crud,
            server_import=ServerImportService(crud),
            server_startup=ServerStartup(crud),
            server_backup=ServerBackupManager(crud),
        )

    def bind_to(self, host: Any) -> None:
        """
        將服務屬性掛到 host

        Args:
            host: 要掛載服務的物件
        """
        host.servers_root = self.servers_root
        host.loader_manager = self.loader_manager
        host.server_crud = self.server_crud
        host.server_import = self.server_import
        host.server_startup = self.server_startup
        host.server_backup = self.server_backup
        host.shell = self


__all__ = ["ApplicationShell"]
