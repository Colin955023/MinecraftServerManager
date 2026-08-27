"""
管理伺服器服務
負責計算伺服器狀態與產生 UI 列表更新用的資料，確保展示層與領域邏輯分離
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core import ServerInspector, ServerRuntime
from src.models import ServerConfig, ServerInspectionIntent
from src.utils import format_bytes, get_logger

logger = get_logger().bind(component="ManageServerService")


@dataclass(frozen=True)
class ServerRefreshPayload:
    """背景刷新完成後交給 UI callback 的列表資料"""

    signature: tuple[tuple[str, tuple[Any, ...]], ...]
    server_order: list[str]
    server_rows: dict[str, tuple[Any, ...]]


@dataclass(frozen=True)
class ServerProjection:
    """單輪伺服器狀態的不可變投影"""

    generation: int
    server_order: tuple[str, ...]
    server_rows: dict[str, tuple[Any, ...]]
    selected_server: str | None


@dataclass(frozen=True)
class ServerRenderPlan:
    """管理頁依可觀察差異產生的 render 指令"""

    projection: ServerProjection
    has_changes: bool


class ManageServerService:
    """
    提供管理伺服器頁面的狀態計算與資料轉換服務
    抽離 UI 依賴，實現純資料的狀態管理與 Diff 比對
    """

    def __init__(
        self,
        server_crud: Any,
        server_runtime: ServerRuntime,
        server_backup: Any,
        server_inspector: ServerInspector,
    ) -> None:
        self.server_crud = server_crud
        self.server_runtime = server_runtime
        self.server_backup = server_backup
        self.server_inspector = server_inspector

        self._last_accepted_projection: ServerProjection | None = None
        self._current_generation: int = 0
        self._generation_lock = threading.Lock()

    def clear_cache(self) -> None:
        """清除最後接受的伺服器列表投影"""
        self._last_accepted_projection = None

    def begin_refresh(self, *, reload_config: bool = False) -> int:
        """
        開始一輪新的刷新，回傳單調遞增 generation

        Args:
            reload_config: 是否重新載入伺服器設定檔

        Returns:
            單調遞增的 generation 整數，供後續 accept_projection 使用
        """
        with self._generation_lock:
            self._current_generation += 1
            generation = self._current_generation
        if reload_config:
            self.server_crud.load_servers_config()
        return generation

    def collect_facts(self, _generation: int = 0) -> ServerRefreshPayload:
        """
        在背景執行：蒐集所有伺服器事實，回傳不可變 payload

        Args:
            _generation: 這輪刷新所屬的generation，僅供背景執行使用，UI callback 不應依賴此值

        Returns:
            不可變的 ServerRefreshPayload
        """
        if not self.server_crud.servers:
            return self._build_server_refresh_payload([])
        return self._build_server_refresh_payload(self._build_server_display_data())

    def accept_projection(
        self,
        generation: int,
        payload: ServerRefreshPayload,
        current_selection: str | None,
    ) -> ServerRenderPlan | None:
        """
        接受投影：拒絕過期 generation，與最後 accepted projection 直接比較

        Args:
            generation: 這輪刷新所屬的 generation
            payload: 這輪刷新所產生的 ServerRefreshPayload
            current_selection: 目前選取的伺服器

        Returns:
            ServerRenderPlan 或 None
        """
        with self._generation_lock:
            if generation < self._current_generation:
                return None

        retained_selection: str | None = None
        if current_selection and current_selection in payload.server_rows:
            retained_selection = current_selection

        new_projection = ServerProjection(
            generation=generation,
            server_order=tuple(payload.server_order),
            server_rows=dict(payload.server_rows),
            selected_server=retained_selection,
        )

        last = self._last_accepted_projection
        has_changes = (
            last is None
            or last.server_order != new_projection.server_order
            or last.server_rows != new_projection.server_rows
        )

        self._last_accepted_projection = new_projection

        if not has_changes:
            return ServerRenderPlan(projection=new_projection, has_changes=False)

        return ServerRenderPlan(projection=new_projection, has_changes=True)

    @staticmethod
    def _format_loader_display(loader_type: str, loader_version: str, minecraft_version: str = "") -> str:
        """將 loader 資訊轉成列表顯示文字"""
        normalized_type = (loader_type or "").lower()
        normalized_version = (loader_version or "").lower()
        if normalized_type == "vanilla":
            if minecraft_version and minecraft_version.lower() != "unknown":
                return minecraft_version
            return "原版"
        if normalized_type == "unknown" or not normalized_type:
            return "未知"
        display = normalized_type.capitalize()
        if normalized_version and normalized_version != "unknown":
            return f"{display} v{loader_version}"
        return display

    @staticmethod
    def _format_minecraft_version_display(minecraft_version: str) -> str:
        """將 Minecraft 版本轉成列表顯示文字"""
        if minecraft_version and minecraft_version.lower() != "unknown":
            return minecraft_version
        return "未知"

    @staticmethod
    def _get_server_size(path: str) -> str:
        """計算伺服器目錄下所有檔案的總大小（包含 world 以外的內容）。"""
        total_bytes = 0
        try:
            server_path = Path(path)
            if not server_path.is_dir():
                return format_bytes(0)
            for file_path in server_path.rglob("*"):
                try:
                    if file_path.is_file():
                        total_bytes += max(0, file_path.stat().st_size)
                except (OSError, ValueError) as exc:
                    logger.warning(f"讀取伺服器檔案大小失敗，略過 {file_path}: {exc}")
        except (OSError, ValueError) as exc:
            logger.warning(f"掃描伺服器大小失敗 {path}: {exc}")
        return format_bytes(total_bytes)

    @classmethod
    def _build_server_display_row(
        cls,
        *,
        name: str,
        config: ServerConfig,
        status: str,
        server_size: str,
        backup_status: str,
        display_path: str,
    ) -> list[Any]:
        """將伺服器設定與動態狀態整合成列表顯示列"""
        return [
            name,
            cls._format_minecraft_version_display(config.minecraft_version),
            cls._format_loader_display(config.loader_type, config.loader_version, config.minecraft_version),
            status,
            server_size,
            backup_status,
            display_path,
        ]

    @staticmethod
    def _make_server_data_signature(server_data: list[list[Any]]) -> tuple[tuple[str, tuple[Any, ...]], ...]:
        """建立可比較簽章，避免每次都重建整個列表"""
        signature: list[tuple[str, tuple[Any, ...]]] = []
        for row in server_data:
            if not row:
                continue
            name = str(row[0])
            signature.append((name, tuple(row)))
        return tuple(signature)

    @classmethod
    def _build_server_tree_payload(cls, server_data: list[list[Any]]) -> tuple[list[str], dict[str, tuple[Any, ...]]]:
        """將原始 server_data 轉成 Treeview 套用所需的順序與列資料"""
        server_order: list[str] = []
        server_rows: dict[str, tuple[Any, ...]] = {}
        for row in server_data:
            if not row:
                continue
            name = str(row[0])
            server_order.append(name)
            server_rows[name] = tuple(row)
        return (server_order, server_rows)

    @classmethod
    def _build_server_refresh_payload(cls, server_data: list[list[Any]]) -> ServerRefreshPayload:
        """建立刷新流程使用的簽章、順序與列資料"""
        signature = cls._make_server_data_signature(server_data)
        server_order, server_rows = cls._build_server_tree_payload(server_data)
        return ServerRefreshPayload(signature=signature, server_order=server_order, server_rows=server_rows)

    def get_backup_status(self, server_name: str) -> str:
        """
        取得伺服器的備份狀態文字

        Args:
            server_name: 伺服器名稱

        Returns:
            備份狀態文字
        """
        if not server_name or server_name not in self.server_crud.servers:
            return "❓ 無法檢查"
        try:
            backups = self.server_backup.list_backups(server_name)
            if not backups:
                return "⚠️ 無備份"
            latest = backups[0]
            backup_datetime = latest.get("datetime")
            if backup_datetime is None:
                return "✅ 有備份"
            now = datetime.now()
            time_diff = now - backup_datetime
            if time_diff.total_seconds() < 0:
                return "✅ 剛剛"
            if time_diff.days > 0:
                time_ago = "1 天前" if time_diff.days == 1 else f"{time_diff.days} 天前"
                return f"✅ {time_ago}"
            if time_diff.seconds > 3600:
                hours = time_diff.seconds // 3600
                return f"✅ {hours} 小時前"
            minutes = time_diff.seconds // 60
            time_ago = f"{minutes} 分鐘前" if minutes > 0 else "剛剛"
            return f"✅ {time_ago}"
        except Exception as e:
            logger.error(f"檢查備份狀態失敗: {e}")
            return "❓ 檢查失敗"

    def get_server_status_text(self, name: str, config: ServerConfig) -> str:
        """
        取得伺服器狀態文字

        Args:
            name: 伺服器名稱
            config: 伺服器設定

        Returns:
            伺服器狀態文字
        """
        is_running = self.server_runtime.observe(name).is_running
        if is_running:
            return "🟢 執行中"
        inspection = self.server_inspector.inspect(
            config.path,
            ServerInspectionIntent(
                purpose="status",
                expected_loader_type=config.loader_type,
                expected_minecraft_version=config.minecraft_version,
                expected_loader_version=config.loader_version,
            ),
        )
        if inspection.status_ready:
            return "✅ 已就緒"
        if inspection.launchable and inspection.eula_state == "rejected":
            return "⚠️ 需要接受 EULA"
        if inspection.launchable and inspection.eula_state == "missing":
            return "❌ 缺少 EULA"
        if inspection.missing_files:
            return f"❌ 未就緒 (缺少: {', '.join(inspection.missing_files)})"
        if inspection.error:
            return f"❌ 未就緒 ({inspection.error})"
        return "❌ 未就緒"

    def _format_server_path_for_display(self, raw_path: str) -> str:
        """將絕對路徑轉為易讀的 servers 子路徑形式"""
        try:
            servers_root = Path(self.server_crud.servers_root).resolve()
            resolved = Path(raw_path).resolve()
            relative = resolved.relative_to(servers_root)
            return str(Path("servers") / relative)
        except Exception:
            return str(raw_path)

    def _build_server_display_data(self) -> list[list[Any]]:
        """從目前狀態建立顯示用列表資料"""
        server_data: list[list[Any]] = []
        for name, config in self.server_crud.servers.items():
            status = self.get_server_status_text(name, config)
            server_size = self._get_server_size(config.path)
            backup_status = self.get_backup_status(name)
            display_path = self._format_server_path_for_display(config.path)
            server_data.append(
                self._build_server_display_row(
                    name=name,
                    config=config,
                    status=status,
                    server_size=server_size,
                    backup_status=backup_status,
                    display_path=display_path,
                )
            )
        return server_data


__all__ = ["ManageServerService"]
