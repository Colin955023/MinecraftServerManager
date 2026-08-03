from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ...models import LoaderVersion

if TYPE_CHECKING:
    from .loader_manager import OperationResult


class BaseLoaderAdapter(ABC):
    """
    載入器適配器的基礎介面。
    每種載入器 (Vanilla, Fabric, Forge, Quilt, NeoForge) 都應實作此介面，
    負責處理專屬的版本解析、快取、以及安裝器參數。
    """

    @abstractmethod
    def get_id(self) -> str:
        """回傳 loader 的識別碼，例如 'fabric', 'forge' 等。"""

    @abstractmethod
    def preload_versions(self) -> OperationResult | None:
        """
        從網路 API 抓取版本資訊並寫入快取。
        如果成功，可回傳 OperationResult(True, ...)，若失敗則回傳 OperationResult(False, ...)。
        部分舊實作可能僅回傳 None。
        """

    @abstractmethod
    def get_compatible_versions(self, mc_version: str) -> list[LoaderVersion]:
        """從快取讀取並回傳與指定 Minecraft 版本相容的載入器版本清單。"""

    @abstractmethod
    def get_installer_download_url(self, minecraft_version: str, loader_version: str) -> str | None:
        """取得安裝器的下載網址。Vanilla 若無安裝器可回傳 None。"""

    @abstractmethod
    def get_installer_args(
        self, java_path: str, minecraft_version: str, loader_version: str, download_path: str, installer_path: str
    ) -> list[str]:
        """取得執行安裝器時的命令列參數。"""

    @abstractmethod
    def needs_vanilla_jar(self) -> bool:
        """是否需要在安裝載入器時，事先下載 Vanilla 的 server.jar。"""

    @abstractmethod
    def is_installer_required(self) -> bool:
        """是否需要下載並執行 installer。例如 Vanilla 不需要。"""
