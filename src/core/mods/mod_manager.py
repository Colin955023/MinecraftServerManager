"""
模組管理器

負責管理 Minecraft 伺服器的模組，提供啟用/停用、移除等功能
"""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from src.models import (
    LocalModInfo,
    ModStatus,
)
from src.utils import (
    ModIndexManager,
    get_logger,
    serialize_json,
)

from .local_mod_scanner import LocalModScanner
from .mod_file_installer import ModFileInstaller
from .modrinth_provider_adapter import ModrinthProviderAdapter
from .provider_identity import ModIndexProviderIdentityStore, ProviderCatalogPort, ProviderIdentityService

logger = get_logger().bind(component="ModManager")

_XLSX_INVALID_XML_CHARS = dict.fromkeys((*range(0x09), 0x0B, 0x0C, *range(0x0E, 0x20)))
_XLSX_INVALID_SHEET_NAME_CHARS = str.maketrans(dict.fromkeys("[]:*?/\\", "_"))


def _normalize_xlsx_sheet_name(sheet_name: str) -> str:
    """清理 Excel 工作表名稱與 XML 1.0 不允許的字元"""
    normalized = str(sheet_name or "Sheet1").translate(_XLSX_INVALID_XML_CHARS)
    normalized = normalized.translate(_XLSX_INVALID_SHEET_NAME_CHARS).strip("'")[:31]
    return normalized or "Sheet1"


def _build_xlsx(rows: list[list[object]], *, sheet_name: str = "Sheet1") -> bytes:
    """使用標準函式庫建立單工作表 XLSX"""
    sheet_rows: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells: list[str] = []
        for column_index, value in enumerate(row, start=1):
            column_name = ""
            number = column_index
            while number:
                number, remainder = divmod(number - 1, 26)
                column_name = chr(65 + remainder) + column_name
            text = ("" if value is None else str(value)).translate(_XLSX_INVALID_XML_CHARS)
            cells.append(
                f'<c r="{column_name}{row_index}" t="inlineStr"><is><t xml:space="preserve">'
                f"{escape(text, quote=False)}</t></is></c>"
            )
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(sheet_rows)}</sheetData></worksheet>"
    )
    safe_sheet_name = escape(_normalize_xlsx_sheet_name(sheet_name), quote=True)
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{safe_sheet_name}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )

    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as workbook:
        workbook.writestr("[Content_Types].xml", content_types)
        workbook.writestr("_rels/.rels", root_rels)
        workbook.writestr("xl/workbook.xml", workbook_xml)
        workbook.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        workbook.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return output.getvalue()


class ModManager:
    """負責伺服器模組的掃描、啟用/停用、移除等功能"""

    index_manager: ModIndexManager

    def __init__(
        self,
        server_path: str,
        server_config=None,
        *,
        provider_catalog: ProviderCatalogPort | None = None,
    ) -> None:
        self.server_path = Path(server_path)
        self.mods_path = self.server_path / "mods"
        self.download_staging_root = self.server_path / ".download_staging"
        self.server_config = server_config
        self.mods_path.mkdir(parents=True, exist_ok=True)
        self.download_staging_root.mkdir(parents=True, exist_ok=True)
        self.index_manager: ModIndexManager = ModIndexManager(server_path)
        self.provider_identity_service = ProviderIdentityService(
            store=ModIndexProviderIdentityStore(self.index_manager),
            catalog=provider_catalog or ModrinthProviderAdapter(),
        )
        self.local_mod_scanner = LocalModScanner(
            index_manager=self.index_manager,
            mods_path=self.mods_path,
            server_config=self.server_config,
            provider_identity_service=self.provider_identity_service,
            quarantine_file=self._quarantine_file,
        )
        self.mod_file_installer = ModFileInstaller(
            server_path=self.server_path,
            mods_path=self.mods_path,
            download_staging_root=self.download_staging_root,
            on_mod_list_changed=None,
            logger=logger,
        )

    def get_mod_list(self, include_disabled: bool = True) -> list[LocalModInfo]:
        """
        取得模組列表

        Args:
            include_disabled: 是否包含已停用的模組，預設為 True

        Returns:
            模組資訊列表，依檔名排序
        """
        mods = self.local_mod_scanner.scan_mods()
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
        result = self.mod_file_installer.install_remote_mod_file_result(
            download_url=download_url,
            filename=filename,
            progress_callback=progress_callback,
            expected_hash=expected_hash,
            provider=provider,
            cancel_check=cancel_check,
        )
        return result.final_path if result.completed else None

    def export_mod_list(self, format_type: str = "text") -> str | bytes:
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
            return serialize_json(export_data, indent=2)
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
                "<tr><th>啟用</th><th>名稱</th><th>版本</th><th>作者</th><th>檔案名稱</th><th>模組ID</th><th>描述</th></tr>",
            ]
            for mod in mods:
                html.append(
                    "<tr>"
                    f"<td>{'✅' if mod.status == ModStatus.ENABLED else '❌'}</td>"
                    f"<td>{_html(mod.name)}</td>"
                    f"<td>{_html(mod.version)}</td>"
                    f"<td>{_html(mod.author)}</td>"
                    f"<td>{_html(mod.filename)}</td>"
                    f"<td>{_html(mod.id)}</td>"
                    f"<td>{_html(mod.description)}</td>"
                    "</tr>"
                )
            html.append("</table></body></html>")
            return "\n".join(html)
        if format_type == "xlsx":
            rows: list[list[object]] = [["啟用狀態", "模組名稱", "版本", "作者", "檔案名稱", "模組ID", "描述"]]
            rows.extend(
                [
                    "是" if mod.status == ModStatus.ENABLED else "否",
                    mod.name or "",
                    mod.version or "",
                    mod.author or "",
                    mod.filename or "",
                    mod.id or "",
                    mod.description or "",
                ]
                for mod in mods
            )
            return _build_xlsx(rows, sheet_name="模組列表")
        return ""

    def _quarantine_file(self, file_path: Path, reason: str) -> None:
        """標記檔案為有問題（不移動），以便 UI/人員檢查後再決定復原或移動"""
        try:
            marked = self.index_manager.mark_issue(file_path, reason)
            if marked:
                logger.info(f"已標記檔案為有問題: {file_path} ({reason})")
            else:
                logger.warning(f"建立檔案問題標記失敗: {file_path} ({reason})")
        except Exception as e:
            logger.exception(f"標記檔案為有問題時發生未預期錯誤: {file_path}\n{e}")

    def clear_mod_index(self) -> None:
        """清空模組快取索引"""
        if hasattr(self, "index_manager") and self.index_manager:
            self.index_manager.clear_index()


__all__ = ["ModManager"]
