"""
模組管理器

負責管理 Minecraft 伺服器的模組，提供模組列表查詢、匯出與遠端安裝協調。
本模組已瘦身：純 pass-through 方法已移除，UI 層可直接使用 scanner、installer、
resolver 屬性存取 LocalModScanner、ModFileInstaller、ModProviderResolver。
"""

from collections.abc import Callable
from html import escape
from pathlib import Path

from ...models import (
    LocalModInfo,
    ModPlatform,
    ModStatus,
)
from ...utils import (
    ModIndexManager,
    ModrinthIdentityCache,
    PathUtils,
    get_logger,
    record_and_mark,
)
from .. import (
    LocalModScanner,
    LocalProviderEnsureResult,
    ModFileInstaller,
    ModProviderResolver,
    ProviderMetadataRecord,
    ensure_local_mod_provider_record,
    resolve_platform_info_from_cache,
)

logger = get_logger().bind(component="ModManager")


class ModManager:
    """負責伺服器模組的掃描協調、列表查詢、匯出與遠端安裝。"""

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

    # ── 延遲初始化屬性（供內部與 UI 層直接使用）───────────

    @property
    def scanner(self) -> LocalModScanner:
        """本地模組掃描器（延遲建立）。"""
        scanner = self._local_mod_scanner
        if scanner is None:
            scanner = LocalModScanner(
                index_manager=self.index_manager,
                mods_path=self.mods_path,
                server_config=self.server_config,
                resolve_platform_info=self._resolve_platform_info,
                quarantine_file=self._quarantine_file,
            )
            self._local_mod_scanner = scanner
        return scanner

    @property
    def installer(self) -> ModFileInstaller:
        """模組檔案安裝器（延遲建立）。"""
        installer = self._mod_file_installer
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

    @property
    def resolver(self) -> ModProviderResolver:
        """Provider 解析器（延遲建立）。"""
        resolver = self._provider_resolver
        if resolver is None:
            resolver = ModProviderResolver(
                index_manager=self.index_manager,
                modrinth_identity_cache=self._modrinth_identity_cache,
                read_json_from_jar=LocalModScanner.read_json_from_jar,
                quarantine_file=self._quarantine_file,
            )
            self._provider_resolver = resolver
        return resolver

    # ── 內部輔助方法 ──────────────────────────────────────

    def _resolve_platform_info(
        self,
        file_path: Path,
        name: str,
        base_name: str,
        filename: str,
        cached_provider: dict[str, object] | None = None,
    ) -> tuple[ModPlatform, str, str]:
        """優先使用索引中的 provider metadata，必要時才重新偵測。"""
        return resolve_platform_info_from_cache(
            index_manager=self.index_manager,
            file_path=file_path,
            name=name,
            cached_provider=cached_provider,
            ensure_platform_provider_record=lambda cached_record: self._ensure_platform_provider_record(
                file_path=file_path,
                name=name,
                base_name=base_name,
                filename=filename,
                cached_record=cached_record,
            ),
        )

    def _ensure_platform_provider_record(
        self, *, file_path: Path, name: str, base_name: str, filename: str, cached_record: ProviderMetadataRecord
    ) -> LocalProviderEnsureResult:
        return ensure_local_mod_provider_record(
            platform_id=cached_record.project_id,
            platform_slug=cached_record.slug,
            project_name=str(name or "").strip(),
            identifier_resolver=self._resolve_modrinth_provider_record_for_scan,
            fallback_resolver=lambda: self._detect_provider_record(file_path, name, base_name, filename),
        )

    def _resolve_modrinth_provider_record_for_scan(self, identifier: str) -> ProviderMetadataRecord:
        project_id, slug = self.resolver.resolve_modrinth_project_identity(identifier)
        return ProviderMetadataRecord.from_values(platform=ModPlatform.MODRINTH.value, project_id=project_id, slug=slug)

    def _detect_provider_record(
        self, file_path: Path, name: str, base_name: str, filename: str
    ) -> ProviderMetadataRecord:
        platform, platform_id, platform_slug = self.resolver.detect_platform_info(file_path, name, base_name, filename)
        return ProviderMetadataRecord.from_values(
            platform=platform.value, project_id=platform_id, slug=platform_slug, project_name=str(name or "").strip()
        )

    def _quarantine_file(self, file_path: Path, reason: str) -> None:
        """
        標記檔案為有問題（不移動），以便 UI/人員檢查後再決定復原或移動。

        會在同一目錄下建立隱藏 marker 檔案 `.{filename}.issue.json`，包含原因與時間戳。
        """
        try:
            marked = PathUtils.mark_issue(file_path, reason)
            if marked:
                logger.info(f"已標記檔案為有問題: {file_path} ({reason})")
            else:
                logger.warning(f"建立檔案問題標記失敗: {file_path} ({reason})")
        except Exception as exc:
            record_and_mark(
                exc,
                marker_path=None,
                reason="mark_issue_failed",
                details={"file": str(file_path), "context": "_quarantine_file", "reason": reason},
            )

    # ── 公開方法 ──────────────────────────────────────────

    def get_mod_list(self, include_disabled: bool = True) -> list[LocalModInfo]:
        """獲取模組列表，可選擇是否排除已停用模組。"""
        mods = self.scanner.scan_mods(self.scanner.create_mod_info_from_file)
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
        下載遠端模組檔案並安裝到目前伺服器的 mods 目錄。

        Args:
            download_url: 遠端檔案下載網址。
            filename: 要寫入的檔名。
            progress_callback: 可選的下載進度回呼。
            expected_hash: 預期檔案雜湊，需為 SHA-256 或 SHA-512；若缺少則拒絕下載。

        Returns:
            安裝成功時回傳目標檔案路徑，失敗時回傳 None。
        """
        result = self.installer.install_remote_mod_file_result(
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
        以遠端版本覆蓋本地模組，並盡量保留原本啟用/停用狀態。

        Args:
            local_mod: 目前本地模組資訊。
            download_url: 遠端檔案下載網址。
            filename: 新版本檔名。
            progress_callback: 可選的下載進度回呼。
            expected_hash: 預期檔案雜湊，需為 SHA-256 或 SHA-512；若缺少則拒絕下載。

        Returns:
            更新成功時回傳最終檔案路徑，失敗時回傳 None。
        """
        return self.installer.replace_local_mod_file(
            local_mod=local_mod,
            download_url=download_url,
            filename=filename,
            progress_callback=progress_callback,
            expected_hash=expected_hash,
            provider=provider,
            cancel_check=cancel_check,
        )

    def export_mod_list(self, format_type: str = "text") -> str:
        """
        匯出模組列表，支援 text、json、html 格式。

        Args:
            format_type: 輸出格式，預設為 text。

        Returns:
            依指定格式輸出的模組列表字串；格式不支援時回傳空字串。
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
