"""
管理伺服器服務
負責計算伺服器狀態與產生 UI 列表更新用的資料，確保展示層與領域邏輯分離。
"""

import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core import ServerCRUD, ServerStartup
from ..models import ServerConfig
from ..utils import ServerDetectionUtils, get_logger

logger = get_logger().bind(component="ManageServerService")


@dataclass(frozen=True)
class ServerRefreshPayload:
    """背景刷新完成後交給 UI callback 的列表資料載體。"""

    signature: tuple[tuple[str, tuple[Any, ...]], ...]
    server_order: list[str]
    server_rows: dict[str, tuple[Any, ...]]


@dataclass(frozen=True)
class ServerRefreshContext:
    """開始新一輪 UI refresh 時使用的上下文。"""

    refresh_token: int
    previous_selection: str | None


@dataclass(frozen=True)
class ServerRefreshExecutionPlan:
    """refresh callback 決策結果：是否套用與對應輪次上下文。"""

    should_apply: bool
    refresh_context: ServerRefreshContext | None = None


@dataclass(frozen=True)
class ServerTreeDiffPreparation:
    """套用 Treeview diff 前的純資料差異比對結果。"""

    rows_snapshot: dict[str, tuple[Any, ...]]
    pending_update: list[tuple[str, tuple[Any, ...]]]
    pending_insert: list[tuple[str, tuple[Any, ...]]]


class ManageServerService:
    """
    提供管理伺服器頁面的狀態計算與資料轉換服務。
    抽離 UI 依賴，實現純資料的狀態管理與 Diff 比對。
    """

    def __init__(
        self,
        server_crud: ServerCRUD,
        server_startup: ServerStartup,
        server_backup: Any,  # ServerBackupManager type hint might cause circular imports, so we use Any
    ):
        self.server_crud = server_crud
        self.server_startup = server_startup
        self.server_backup = server_backup

        self._last_server_data_hash: int | None = None
        self._jar_search_cache: dict[str, tuple[bool, float]] = {}
        self._jar_cache_timeout = 60

    def get_backup_status(self, server_name: str) -> str:
        """
        獲取伺服器的備份狀態文字。

        Args:
            server_name: 伺服器名稱。

        Returns:
            伺服器的備份狀態文字。
        """
        if not server_name or server_name not in self.server_crud.servers:
            return "❓ 無法檢查"
        config = self.server_crud.servers[server_name]
        if not hasattr(config, "backup_path") or not config.backup_path:
            return "⚠️ 未設定"
        if not Path(config.backup_path).exists():
            return "⚠️ 路徑失效"
        try:
            backup_world_path = str(Path(config.backup_path) / "world")
            if Path(backup_world_path).exists():
                backup_time = Path(backup_world_path).stat().st_mtime
                backup_datetime = datetime.fromtimestamp(backup_time)
                now = datetime.now()
                time_diff = now - backup_datetime
                if time_diff.total_seconds() < 0:
                    return "✅ 剛剛"
                if time_diff.days > 0:
                    time_ago = "1天前" if time_diff.days == 1 else f"{time_diff.days}天前"
                    return f"✅ {time_ago}"
                if time_diff.seconds > 3600:
                    hours = time_diff.seconds // 3600
                    return f"✅ {hours}小時前"
                minutes = time_diff.seconds // 60
                time_ago = f"{minutes}分鐘前" if minutes > 0 else "剛剛"
                return f"✅ {time_ago}"
            return "📁 已設定路徑"
        except Exception as e:
            logger.error(f"檢查備份狀態失敗: {e}\n{traceback.format_exc()}")
            return "❓ 檢查失敗"

    def _check_server_jar_exists(self, server_path: str, loader_type: str = "vanilla") -> bool:
        """檢查伺服器 JAR 檔案是否存在"""
        try:
            server_path_obj = Path(server_path)
            result = ServerDetectionUtils.find_main_jar(server_path_obj, loader_type or "vanilla")
            if result.startswith("@"):
                args_file_path = result[1:]
                return (server_path_obj / args_file_path).exists()
            jar_path = server_path_obj / result
            return jar_path.exists()
        except Exception as e:
            logger.debug(f"檢查 JAR 檔案存在失敗: {e}")
            return (Path(server_path) / "server.jar").exists()

    def get_server_status_text(self, name: str, config: ServerConfig) -> str:
        """
        獲取伺服器狀態文字。

        Args:
            name: 伺服器名稱。
            config: 伺服器配置。

        Returns:
            伺服器狀態文字。
        """
        is_running = self.server_startup.is_server_running(name)
        if is_running:
            return "🟢 運行中"
        current_time = time.time()
        cache_key = config.path
        if cache_key in self._jar_search_cache:
            cached_result, cache_time = self._jar_search_cache[cache_key]
            if current_time - cache_time < self._jar_cache_timeout:
                server_jar_exists = cached_result
            else:
                server_jar_exists = self._check_server_jar_exists(config.path, config.loader_type)
                self._jar_search_cache[cache_key] = (server_jar_exists, current_time)
        else:
            server_jar_exists = self._check_server_jar_exists(config.path, config.loader_type)
            self._jar_search_cache[cache_key] = (server_jar_exists, current_time)

        eula_exists = (Path(config.path) / "eula.txt").exists()
        eula_accepted = getattr(config, "eula_accepted", False)
        if server_jar_exists and eula_exists and eula_accepted:
            return "✅ 已就緒"
        if server_jar_exists and eula_exists and (not eula_accepted):
            return "⚠️ 需要接受 EULA"
        if server_jar_exists:
            return "❌ 缺少 EULA"

        missing = ServerDetectionUtils.get_missing_server_files(Path(config.path))
        if missing:
            return f"❌ 未就緒 (缺少: {', '.join(missing)})"
        return "❌ 未就緒"

    @staticmethod
    def _format_loader_display(loader_type: str, loader_version: str) -> str:
        """將 loader 資訊轉成列表顯示文字。"""
        normalized_type = (loader_type or "").lower()
        normalized_version = (loader_version or "").lower()
        if normalized_type == "vanilla":
            return "原版"
        if normalized_type == "unknown" or not normalized_type:
            return "未知"
        display = normalized_type.capitalize()
        if normalized_version and normalized_version != "unknown":
            return f"{display} v{loader_version}"
        return display

    @staticmethod
    def _format_minecraft_version_display(minecraft_version: str) -> str:
        """將 Minecraft 版本轉成列表顯示文字。"""
        if minecraft_version and minecraft_version.lower() != "unknown":
            return minecraft_version
        return "未知"

    def _format_server_path_for_display(self, raw_path: str) -> str:
        """將絕對路徑轉為易讀的 servers 子路徑形式。"""
        try:
            servers_root = Path(self.server_crud.servers_root).resolve()
            resolved = Path(raw_path).resolve()
            relative = resolved.relative_to(servers_root)
            return str(Path("servers") / relative)
        except Exception:
            return str(raw_path)

    @classmethod
    def _build_server_display_row(
        cls, *, name: str, config: ServerConfig, status: str, backup_status: str, display_path: str
    ) -> list[Any]:
        """將伺服器設定與動態狀態整合成列表顯示列。"""
        return [
            name,
            cls._format_minecraft_version_display(config.minecraft_version),
            cls._format_loader_display(config.loader_type, config.loader_version),
            status,
            backup_status,
            display_path,
        ]

    def _build_server_display_data(self) -> list[list[Any]]:
        """從目前狀態建立顯示用列表資料。"""
        server_data: list[list[Any]] = []
        for name, config in self.server_crud.servers.items():
            status = self.get_server_status_text(name, config)
            backup_status = self.get_backup_status(name)
            display_path = self._format_server_path_for_display(config.path)
            server_data.append(
                self._build_server_display_row(
                    name=name, config=config, status=status, backup_status=backup_status, display_path=display_path
                )
            )
        return server_data

    @staticmethod
    def _make_server_data_signature(server_data: list[list[Any]]) -> tuple[tuple[str, tuple[Any, ...]], ...]:
        """建立可比較簽章，避免每次都重建整個列表。"""
        signature: list[tuple[str, tuple[Any, ...]]] = []
        for row in server_data:
            if not row:
                continue
            name = str(row[0])
            signature.append((name, tuple(row)))
        return tuple(signature)

    @classmethod
    def _build_server_tree_payload(cls, server_data: list[list[Any]]) -> tuple[list[str], dict[str, tuple[Any, ...]]]:
        """將原始 server_data 轉成 Treeview 套用所需的順序與列資料。"""
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
        """建立刷新流程使用的簽章、順序與列資料。"""
        signature = cls._make_server_data_signature(server_data)
        server_order, server_rows = cls._build_server_tree_payload(server_data)
        return ServerRefreshPayload(signature=signature, server_order=server_order, server_rows=server_rows)

    def refresh_servers_task(self, reload_config: bool = True) -> ServerRefreshPayload:
        """
        背景任務：載入配置並獲取伺服器狀態。

        Args:
            reload_config: 是否重新載入伺服器設定。

        Returns:
            ServerRefreshPayload: 包含伺服器列表的簽章、順序與列資料。
        """
        if reload_config:
            self.server_crud.load_servers_config()
        if not self.server_crud.servers:
            return self._build_server_refresh_payload([])
        return self._build_server_refresh_payload(self._build_server_display_data())

    @staticmethod
    def _compute_server_payload_hash(payload: ServerRefreshPayload) -> int:
        """計算 payload hash，供 refresh callback 判斷是否需要套用。"""
        try:
            return hash(payload.signature)
        except Exception:
            return hash(time.time())

    def _should_apply_server_refresh(self, payload: ServerRefreshPayload) -> bool:
        """判斷 payload 是否與上次不同，並在變更時更新快取 hash。"""
        current_data_hash = self._compute_server_payload_hash(payload)
        if self._last_server_data_hash == current_data_hash:
            return False
        self._last_server_data_hash = current_data_hash
        return True

    def build_server_refresh_execution_plan(
        self, payload: ServerRefreshPayload, _current_token: int, _selected_server: str | None
    ) -> ServerRefreshExecutionPlan:
        """
        決定本次 refresh callback 是否需要進入 UI 套用階段。

        Args:
            payload: 伺服器刷新資料。
            current_token: 目前的刷新令牌。
            selected_server: 選擇的伺服器。

        Returns:
            ServerRefreshExecutionPlan: 伺服器刷新執行計畫。
        """
        if not self._should_apply_server_refresh(payload):
            return ServerRefreshExecutionPlan(should_apply=False)
        # 使用 helper 以便測試可透過 monkeypatch 覆寫
        refresh_context = self._begin_server_refresh_cycle()
        return ServerRefreshExecutionPlan(should_apply=True, refresh_context=refresh_context)

    def _begin_server_refresh_cycle(self) -> ServerRefreshContext:
        """開始一輪新的 refresh cycle，回傳預設的 context（可被測試 monkeypatch）。"""
        return ServerRefreshContext(refresh_token=0, previous_selection=None)

    def prepare_server_tree_diff(
        self,
        server_order: list[str],
        server_rows: dict[str, tuple[Any, ...]],
        server_item_by_name: dict[str, str],
        previous_snapshot: dict[str, tuple[Any, ...]],
    ) -> ServerTreeDiffPreparation:
        """
        比對資料並回傳需要更新、插入的項目，這不包含任何 UI 操作。

        Args:
            server_order: 伺服器名稱順序列表。
            server_rows: 伺服器名稱對應的列資料字典。
            server_item_by_name: 伺服器名稱對應的 Treeview item ID 字典。
            previous_snapshot: 上一次的列資料快照字典。

        Returns:
            ServerTreeDiffPreparation: 伺服器 Treeview 差異準備。
        """
        rows_snapshot: dict[str, tuple[Any, ...]] = {}
        pending_update: list[tuple[str, tuple[Any, ...]]] = []
        pending_insert: list[tuple[str, tuple[Any, ...]]] = []

        # 以純資料比對決定哪些需要更新（更新以 item_id 為主）或插入（以 name 為主）
        first_update_done = False
        for name in server_order:
            values = server_rows[name]
            item_id = server_item_by_name.get(name)
            if item_id:
                if previous_snapshot.get(name) != values:
                    # 只允許第一個變更的既有項目進行 in-place 更新，其餘視為需重新插入
                    if not first_update_done:
                        pending_update.append((item_id, values))
                        rows_snapshot[name] = values
                        first_update_done = True
                    else:
                        # 將 mapping 移除，並改以插入處理
                        server_item_by_name.pop(name, None)
                        pending_insert.append((name, values))
                else:
                    rows_snapshot[name] = values
            else:
                pending_insert.append((name, values))

        # 對傳入的 mapping 不主動新增值；若 mapping 包含不在 rows_snapshot 的鍵，呼叫端可選擇回收
        return ServerTreeDiffPreparation(
            rows_snapshot=rows_snapshot, pending_update=pending_update, pending_insert=pending_insert
        )
