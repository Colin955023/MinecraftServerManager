"""Mod 管理頁面期間的唯一 application-state writer"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any

from src.models import (
    ModListRow,
    ModManagementSnapshot,
    ModOperationScope,
    OnlineBrowseRequest,
    OperationKind,
    PendingOnlineInstall,
    ServerConfig,
)


class ModManagementSession:
    """協調 local、online、queue、selection 與 async generation"""

    def __init__(self, server: ServerConfig | None = None) -> None:
        self._lock = threading.RLock()
        self._session_id = uuid.uuid4().hex
        self._active = True
        self._server = server
        self._server_identity = self._build_server_identity(server)
        self._local_mods: list[Any] = []
        self._online_mods: list[Any] = []
        self._online_mod_index: dict[str, Any] = {}
        self._local_rows: tuple[ModListRow, ...] = ()
        self._online_rows: tuple[ModListRow, ...] = ()
        self._pending_online_installs: list[PendingOnlineInstall] = []
        self._selected_mod_ids: set[str] = set()
        self._provider_cache: dict[str, Any] = {}
        self._status_message = ""
        self._local_generation = 0
        self._online_generation = 0
        self._install_generation = 0
        self._version_generation = 0
        self._latest_online_request: OnlineBrowseRequest | None = None
        self._last_mods_dir: str | None = None
        self._last_mods_dir_mtime: float | None = None
        self._last_mods_dir_signature: tuple[tuple[str, int, int], ...] | None = None

    @staticmethod
    def _build_server_identity(server: ServerConfig | None) -> str:
        if server is None:
            return ""
        raw_path = str(getattr(server, "path", "") or "").strip()
        resolved_path = str(Path(raw_path).resolve(strict=False)) if raw_path else ""
        return "|".join(
            (
                resolved_path or str(getattr(server, "name", "") or "").strip(),
                str(getattr(server, "minecraft_version", "") or "").strip(),
                str(getattr(server, "loader_type", "") or "").strip().lower(),
                str(getattr(server, "loader_version", "") or "").strip(),
            )
        )

    @property
    def server(self) -> ServerConfig | None:
        return self._server

    def matches_server(self, server: ServerConfig | None) -> bool:
        """
        判斷工作階段是否仍屬於指定伺服器

        Args:
            server: 要比對的伺服器設定

        Returns:
            工作階段有效且 server identity 相同時為 True
        """
        return self._active and self._server_identity == self._build_server_identity(server)

    @property
    def local_mods(self) -> tuple[Any, ...]:
        with self._lock:
            return tuple(self._local_mods)

    @property
    def online_mods(self) -> tuple[Any, ...]:
        with self._lock:
            return tuple(self._online_mods)

    @property
    def pending_online_installs(self) -> tuple[PendingOnlineInstall, ...]:
        with self._lock:
            return tuple(self._pending_online_installs)

    @property
    def selected_mod_ids(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._selected_mod_ids)

    def snapshot(self) -> ModManagementSnapshot:
        """
        取得鎖內一致的不可變狀態快照

        Returns:
            目前工作階段的完整唯讀投影
        """
        with self._lock:
            return ModManagementSnapshot(
                session_id=self._session_id,
                active=self._active,
                server=self._server,
                server_identity=self._server_identity,
                local_mods=tuple(self._local_mods),
                online_mods=tuple(self._online_mods),
                local_rows=self._local_rows,
                online_rows=self._online_rows,
                pending_online_installs=tuple(self._pending_online_installs),
                selected_mod_ids=frozenset(self._selected_mod_ids),
                status_message=self._status_message,
                latest_online_request=self._latest_online_request,
            )

    def invalidate(self) -> None:
        """使工作階段與所有未完成 scope 失效並清空待安裝項目"""
        with self._lock:
            self._active = False
            self._local_generation += 1
            self._online_generation += 1
            self._install_generation += 1
            self._version_generation += 1
            self._pending_online_installs.clear()

    def begin_local_scan(self) -> ModOperationScope:
        """
        開始本地掃描

        Returns:
            可用來拒絕過期結果的本地掃描 scope
        """
        with self._lock:
            self._local_generation += 1
            return self._scope("local_scan", self._local_generation)

    def begin_online_search(self, request: OnlineBrowseRequest) -> ModOperationScope:
        """
        開始線上搜尋並記錄 request

        Args:
            request: 這一代搜尋的完整查詢條件

        Returns:
            可用來拒絕過期結果的線上搜尋 scope
        """
        with self._lock:
            self._online_generation += 1
            self._latest_online_request = request
            return self._scope("online_search", self._online_generation)

    def begin_install(self) -> ModOperationScope:
        """
        開始安裝

        Returns:
            可用來限制安裝副作用的 scope
        """
        with self._lock:
            self._install_generation += 1
            return self._scope("install", self._install_generation)

    def begin_version_load(self) -> ModOperationScope:
        """
        開始模組版本載入

        Returns:
            可用來拒絕過期版本載入結果的 scope
        """
        with self._lock:
            self._version_generation += 1
            return self._scope("version_load", self._version_generation)

    def _scope(self, kind: OperationKind, generation: int) -> ModOperationScope:
        return ModOperationScope(self._session_id, self._server_identity, kind, generation)

    def is_scope_current(self, scope: ModOperationScope) -> bool:
        """
        驗證 scope 是否仍指向目前有效世代

        Args:
            scope: 背景工作啟動時取得的操作 scope

        Returns:
            session、server、kind 與 generation 全部相符時為 True
        """
        with self._lock:
            expected_generation = {
                "local_scan": self._local_generation,
                "online_search": self._online_generation,
                "install": self._install_generation,
                "version_load": self._version_generation,
            }[scope.kind]
            return (
                self._active
                and scope.session_id == self._session_id
                and scope.server_identity == self._server_identity
                and scope.generation == expected_generation
            )

    def accept_local_results(self, scope: ModOperationScope, mods: list[Any]) -> bool:
        """
        僅接受目前世代的本地掃描結果

        Args:
            scope: 本地掃描啟動時取得的 scope
            mods: 完整本地 Mod 清單

        Returns:
            結果已成為目前狀態時為 True
        """
        with self._lock:
            if not self.is_scope_current(scope) or scope.kind != "local_scan":
                return False
            self._local_mods = list(mods)
            self._local_rows = ()
            self._provider_cache.clear()
            return True

    def accept_online_results(
        self,
        scope: ModOperationScope,
        request: OnlineBrowseRequest,
        mods: list[Any],
    ) -> bool:
        """
        僅接受目前 request 與世代的線上搜尋結果

        Args:
            scope: 線上搜尋啟動時取得的 scope
            request: 產生這批結果的查詢條件
            mods: 完整線上 Mod 清單

        Returns:
            結果已成為目前狀態時為 True
        """
        with self._lock:
            if (
                not self.is_scope_current(scope)
                or scope.kind != "online_search"
                or request != self._latest_online_request
            ):
                return False
            self._online_mods = list(mods)
            self._online_rows = ()
            self._online_mod_index = {
                str(getattr(mod, "project_id", "") or ""): mod
                for mod in mods
                if str(getattr(mod, "project_id", "") or "")
            }
            return True

    def clear_online_results(self) -> None:
        """清除線上結果、索引與最近一次搜尋 request"""
        with self._lock:
            self._online_generation += 1
            self._online_mods.clear()
            self._online_rows = ()
            self._online_mod_index.clear()
            self._latest_online_request = None

    def online_mod_at(self, index: int) -> Any | None:
        """
        依目前排序取得線上 Mod

        Args:
            index: 線上結果的零起算索引

        Returns:
            索引有效時的 Mod；否則回傳 None
        """
        with self._lock:
            return self._online_mods[index] if 0 <= index < len(self._online_mods) else None

    def online_mod_by_project_id(self, project_id: str) -> Any | None:
        """
        依 provider project ID 取得線上 Mod

        Args:
            project_id: 線上 provider 的專案 ID

        Returns:
            已索引的 Mod；不存在時回傳 None
        """
        with self._lock:
            return self._online_mod_index.get(project_id)

    def replace_local_rows(self, rows: list[ModListRow]) -> None:
        """
        以新的本地列表投影取代舊列

        Args:
            rows: Presenter 建立的完整本地列表列
        """
        with self._lock:
            if self._active:
                self._local_rows = tuple(rows)

    def replace_online_rows(self, rows: list[ModListRow]) -> None:
        """
        以新的線上列表投影取代舊列

        Args:
            rows: Presenter 建立的完整線上列表列
        """
        with self._lock:
            if self._active:
                self._online_rows = tuple(rows)

    def add_pending_install(self, pending: PendingOnlineInstall) -> None:
        """
        依 project/version key 新增或取代待安裝項目

        Args:
            pending: 已完成版本選擇的待安裝項目
        """
        with self._lock:
            key = self._pending_key(pending)
            self._pending_online_installs = [
                item for item in self._pending_online_installs if self._pending_key(item) != key
            ]
            self._pending_online_installs.append(pending)

    def remove_pending_review_keys(self, review_keys: set[str]) -> int:
        """
        依 Review root key 移除已完成或使用者選取的項目

        Args:
            review_keys: project_id::version_id 格式的 key 集合

        Returns:
            實際移除的項目數
        """
        with self._lock:
            before = len(self._pending_online_installs)
            self._pending_online_installs = [
                item for item in self._pending_online_installs if "::".join(self._pending_key(item)) not in review_keys
            ]
            return before - len(self._pending_online_installs)

    def clear_pending_installs(self) -> None:
        """清空目前工作階段的待安裝清單"""
        with self._lock:
            self._pending_online_installs.clear()

    @staticmethod
    def _pending_key(item: PendingOnlineInstall) -> tuple[str, str]:
        return (
            str(getattr(item, "project_id", "") or "").strip(),
            str(getattr(getattr(item, "version", None), "version_id", "") or "").strip(),
        )

    def replace_selection(self, mod_ids: set[str]) -> None:
        """
        以完整 Mod ID 集合取代目前選取狀態

        Args:
            mod_ids: 目前 UI 選取的 Mod ID
        """
        with self._lock:
            self._selected_mod_ids = set(mod_ids)

    def set_status(self, message: str) -> None:
        """
        更新可投影至 UI 的工作階段狀態文字

        Args:
            message: 最新狀態訊息
        """
        with self._lock:
            self._status_message = str(message)

    def get_provider_cache(self, filename: str) -> Any | None:
        """
        讀取指定檔名的 provider 增強快取

        Args:
            filename: 本地 Mod 檔名

        Returns:
            已快取的增強資料；不存在時回傳 None
        """
        with self._lock:
            return self._provider_cache.get(filename)

    def cache_provider_enhancement(self, scope: ModOperationScope, filename: str, value: Any) -> bool:
        """
        僅在本地掃描 scope 有效時寫入 provider 增強快取

        Args:
            scope: 取得增強資料時的本地掃描 scope
            filename: 本地 Mod 檔名
            value: Provider 回傳的增強資料

        Returns:
            快取已寫入時為 True
        """
        with self._lock:
            if scope.kind != "local_scan" or not self.is_scope_current(scope):
                return False
            self._provider_cache[filename] = value
            return True

    def rename_provider_cache_key(self, old_filename: str, new_filename: str) -> None:
        """
        在檔案重新命名後搬移 provider cache key

        Args:
            old_filename: 重新命名前的檔名
            new_filename: 重新命名後的檔名
        """
        with self._lock:
            if old_filename in self._provider_cache and new_filename not in self._provider_cache:
                self._provider_cache[new_filename] = self._provider_cache.pop(old_filename)

    def update_local_scan_fingerprint(
        self,
        mods_dir: str | None,
        mtime: float | None,
        signature: tuple[tuple[str, int, int], ...] | None,
    ) -> None:
        """
        記錄已接受本地掃描結果的目錄指紋

        Args:
            mods_dir: Mods 目錄 identity
            mtime: 目錄最後修改時間
            signature: 檔名、大小與時間組成的內容簽章
        """
        with self._lock:
            self._last_mods_dir = mods_dir
            self._last_mods_dir_mtime = mtime
            self._last_mods_dir_signature = signature

    def local_scan_fingerprint(
        self,
    ) -> tuple[str | None, float | None, tuple[tuple[str, int, int], ...] | None]:
        """
        取得上次已接受的本地掃描指紋

        Returns:
            Mods 目錄、mtime 與內容簽章
        """
        with self._lock:
            return self._last_mods_dir, self._last_mods_dir_mtime, self._last_mods_dir_signature


__all__ = ["ModManagementSession"]
