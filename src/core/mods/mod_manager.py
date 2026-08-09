"""
模組管理器

負責管理 Minecraft 伺服器的模組，提供啟用/停用、移除等功能
"""

from collections.abc import Callable
from html import escape
from pathlib import Path

from ...models import (
    LocalModInfo,
    LocalModMutationResult,
    ModFileOperationResult,
    ModrinthIdentityCache,
    ModStatus,
)
from ...utils import (
    ExceptionUtils,
    ModIndexManager,
    PathUtils,
    get_logger,
)
from .local_mod_scanner import LocalModScanner
from .mod_file_installer import ModFileInstaller
from .mod_provider_resolver import (
    ModProviderResolver,
)

logger = get_logger().bind(component="ModManager")


class ModManager:
    """負責伺服器模組的掃描、啟用/停用、移除等功能"""

    index_manager: ModIndexManager

    def __init__(self, server_path: str, server_config=None) -> None:
        self.server_path = Path(server_path)
        self.mods_path = self.server_path / "mods"
        self.download_staging_root = self.server_path / ".download_staging"
        self.server_config = server_config
        self._modrinth_identity_cache = ModrinthIdentityCache()
        self.mods_path.mkdir(parents=True, exist_ok=True)
        self.download_staging_root.mkdir(parents=True, exist_ok=True)
        self.index_manager: ModIndexManager = ModIndexManager(server_path)
        self.on_mod_list_changed: Callable | None = None
        self._local_mod_scanner: LocalModScanner | None = None
        self._mod_file_installer: ModFileInstaller | None = None
        self._provider_resolver: ModProviderResolver | None = None

    def scan_mods(self) -> list[LocalModInfo]:
        """
        掃描 mods 目錄中的模組檔案並建立模組資訊列表

        Returns:
            掃描後的模組資訊清單
        """
        return self._get_local_mod_scanner().scan_mods()

    def create_mod_info_from_file(self, file_path: Path) -> LocalModInfo | None:
        """
        從模組檔案建立 LocalModInfo

        Args:
            file_path: 要解析的模組 JAR 檔案路徑

        Returns:
            解析成功時回傳 LocalModInfo，失敗時回傳 None
        """
        return self._get_local_mod_scanner().create_mod_info_from_file(file_path)

    def resolve_modrinth_project_identity(self, identifier: str) -> tuple[str, str]:
        """
        將使用者輸入的 Modrinth project id 或 slug 正規化

        Args:
            identifier: 使用者輸入的 project id 或 slug

        Returns:
            tuple[str, str]: 解析後的規範（canonical）project id 與 slug
        """
        return self._get_provider_resolver().resolve_modrinth_project_identity(identifier)

    def set_mod_state_result(self, mod_id: str, enable: bool, notify_change: bool = True) -> LocalModMutationResult:
        """
        設定模組啟用或停用狀態

        Args:
            mod_id:模組的識別名稱（不含副檔名）
            enable: 是否啟用模組，True 表示啟用，False 表示停用
            notify_change: 是否在狀態變更後觸發 on_mod_list_changed 回呼，預設為 True

        Returns:
            本地模組異動結果
        """
        return self._get_mod_file_installer().set_mod_state_result(mod_id, enable, notify_change)

    def import_local_mod_file_result(self, source_path: str | Path) -> LocalModMutationResult:
        """
        匯入本地模組檔案到目前伺服器的 mods 目錄

        Args:
            source_path: 要匯入的本地模組檔案路徑

        Returns:
            匯入流程結果，供 UI 或呼叫端判斷成功與失敗原因
        """

        return self._get_mod_file_installer().import_local_mod_file_result(source_path)

    def delete_local_mods_result(self, mod_ids: list[str] | tuple[str, ...]) -> LocalModMutationResult:
        """
        刪除一或多個本地模組檔案

        Args:
            mod_ids: 要刪除的模組識別值列表

        Returns:
            刪除流程結果，包含成功數量與缺失模組資訊
        """

        return self._get_mod_file_installer().delete_local_mods_result(mod_ids)

    def get_mod_list(self, include_disabled: bool = True) -> list[LocalModInfo]:
        """
        獲取模組列表

        Args:
            include_disabled: 是否包含已停用的模組，預設為 True

        Returns:
            模組資訊列表，依檔名排序
        """
        mods = self.scan_mods()
        if include_disabled:
            return mods
        return [mod for mod in mods if mod.status == ModStatus.ENABLED]

    def install_remote_mod_file(
        self,
        *,
        download_url: str,
        filename: str,
        progress_callback: Callable[[int, int], None] | None = None,
        provider: str | None = "modrinth",
        expected_hash: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path | None:
        """
        下載遠端模組檔案並安裝到目前伺服器的 mods 目錄

        Args:
            download_url: 遠端檔案下載網址
            filename: 要寫入的檔名
            progress_callback: 可選的下載進度回呼
            provider: 提供者名稱，預設為 "modrinth"
            expected_hash: 預期檔案雜湊，需為 SHA-256 或 SHA-512；若缺少則拒絕下載
            cancel_check: 可選的取消檢查回呼，若回傳 True 則中止下載

        Returns:
            安裝成功時回傳目標檔案路徑，失敗時回傳 None
        """
        result = self._install_remote_mod_file_result(
            download_url=download_url,
            filename=filename,
            progress_callback=progress_callback,
            expected_hash=expected_hash,
            provider=provider,
            cancel_check=cancel_check,
        )
        return result.final_path if result.completed else None

    def replace_local_mod_file(
        self,
        local_mod: LocalModInfo,
        download_url: str,
        filename: str,
        progress_callback: Callable[[int, int], None] | None = None,
        expected_hash: str | None = None,
        *,
        provider: str | None = "modrinth",
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path | None:
        """
        以遠端版本覆蓋本地模組，並盡量保留原本啟用/停用狀態

        Args:
            local_mod: 目前本地模組資訊
            download_url: 遠端檔案下載網址
            filename: 新版本檔名
            progress_callback: 可選的下載進度回呼
            expected_hash: 預期檔案雜湊，需為 SHA-256 或 SHA-512；若缺少則拒絕下載
            provider: 提供者名稱，預設為 "modrinth"
            cancel_check: 可選的取消檢查回呼，若回傳 True 則中止下載

        Returns:
            更新成功時回傳最終檔案路徑，失敗時回傳 None
        """
        return self._get_mod_file_installer().replace_local_mod_file(
            local_mod=local_mod,
            download_url=download_url,
            filename=filename,
            install_remote_mod_file_result=self._install_remote_mod_file_result,
            progress_callback=progress_callback,
            expected_hash=expected_hash,
            provider=provider,
            cancel_check=cancel_check,
        )

    def export_mod_list(self, format_type: str = "text") -> str:
        """
        匯出模組列表，支援 text、json、html 格式

        Args:
            format_type: 輸出格式，預設為 text

        Returns:
            依指定格式輸出的模組列表字串；格式不支援時回傳空字串
        """
        mods = self.get_mod_list()
        if format_type == "text":
            lines = ["# 模組列表", ""]
            for mod in mods:
                status_icon = "✅" if mod.status == ModStatus.ENABLED else "❌"
                line = f"{status_icon} {mod.name} ({mod.version})"
                if mod.author:
                    line += f" - by {mod.author}"
                lines.append(line)
            return "\n".join(lines)
        if format_type == "json":
            export_data = []
            for mod in mods:
                export_data.append(
                    {
                        "name": mod.name,
                        "version": mod.version,
                        "enabled": mod.status == ModStatus.ENABLED,
                        "author": mod.author,
                        "filename": mod.filename,
                        "description": mod.description,
                        "id": mod.id,
                    }
                )
            return PathUtils.to_json_str(export_data, indent=2)
        if format_type == "html":

            def _html(value: object) -> str:
                return escape(str(value or ""), quote=True)

            html = [
                "<!DOCTYPE html>",
                '<html lang="zh-TW">',
                '<head><meta charset="UTF-8"><title>模組列表</title>',
                "<style>table{border-collapse:collapse;}th,td{border:1px solid silver;padding:6px;}th{background:whitesmoke;}</style>",
                "</head><body>",
                "<h2>模組列表</h2>",
                "<table>",
                "<tr><th>啟用</th><th>名稱</th><th>版本</th><th>作者</th><th>描述</th></tr>",
            ]
            for mod in mods:
                html.append(
                    "<tr>"
                    f"<td>{'✅' if mod.status == ModStatus.ENABLED else '❌'}</td>"
                    f"<td>{_html(mod.name)}</td>"
                    f"<td>{_html(mod.version)}</td>"
                    f"<td>{_html(mod.author)}</td>"
                    f"<td>{_html(mod.description)}</td>"
                    "</tr>"
                )
            html.append("</table></body></html>")
            return "\n".join(html)
        return ""

    def _get_local_mod_scanner(self) -> LocalModScanner:
        """延後建立本地模組掃描器，讓 `ModManager` 保持 orchestration 角色"""
        scanner = getattr(self, "_local_mod_scanner", None)
        if scanner is None:
            scanner = LocalModScanner(
                index_manager=self.index_manager,
                mods_path=self.mods_path,
                server_config=self.server_config,
                resolve_platform_info=self._get_provider_resolver().resolve_platform_info,
                quarantine_file=self._quarantine_file,
            )
            self._local_mod_scanner = scanner
        return scanner

    def _get_mod_file_installer(self) -> ModFileInstaller:
        """延後建立檔案安裝器，並同步最新的 UI 通知回呼"""
        installer = getattr(self, "_mod_file_installer", None)
        if installer is None:
            installer = ModFileInstaller(
                server_path=self.server_path,
                mods_path=self.mods_path,
                download_staging_root=self.download_staging_root,
                on_mod_list_changed=self.on_mod_list_changed,
                logger=logger,
            )
            self._mod_file_installer = installer
        installer.on_mod_list_changed = self.on_mod_list_changed
        return installer

    def _get_provider_resolver(self) -> ModProviderResolver:
        """延後建立 provider 解析器，避免 `__new__` 測試案例需要完整初始化"""
        resolver = getattr(self, "_provider_resolver", None)
        if resolver is None:
            resolver = ModProviderResolver(
                index_manager=self.index_manager,
                modrinth_identity_cache=self._modrinth_identity_cache,
                read_json_from_jar=LocalModScanner.read_json_from_jar,
                quarantine_file=self._quarantine_file,
            )
            self._provider_resolver = resolver
        return resolver

    def _install_remote_mod_file_result(
        self,
        download_url: str,
        filename: str,
        progress_callback: Callable[[int, int], None] | None = None,
        expected_hash: str | None = None,
        *,
        provider: str | None = "modrinth",
        cancel_check: Callable[[], bool] | None = None,
        notify_change: bool = True,
    ) -> ModFileOperationResult:
        return self._get_mod_file_installer().install_remote_mod_file_result(
            download_url=download_url,
            filename=filename,
            progress_callback=progress_callback,
            expected_hash=expected_hash,
            provider=provider,
            cancel_check=cancel_check,
            notify_change=notify_change,
        )

    def _quarantine_file(self, file_path: Path, reason: str) -> None:
        """
        標記檔案為有問題（不移動），以便 UI/人員檢查後再決定復原或移動

        會在同一目錄下建立隱藏 marker 檔案 `.{filename}.issue.json`，包含原因與時間戳
        """
        try:
            marked = PathUtils.mark_issue(file_path, reason)
            if marked:
                logger.info(f"已標記檔案為有問題: {file_path} ({reason})")
            else:
                logger.warning(f"建立檔案問題標記失敗: {file_path} ({reason})")
        except Exception as exc:
            ExceptionUtils.record_and_mark(
                exc,
                marker_path=None,
                reason="mark_issue_failed",
                details={"file": str(file_path), "context": "_quarantine_file", "reason": reason},
            )
