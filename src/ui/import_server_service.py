"""
匯入伺服器服務模組
負責處理伺服器 ZIP 檔或資料夾之匯入與解壓縮邏輯。
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from ..utils import get_logger

logger = get_logger().bind(component="ImportServerService")


class ImportServerService:
    """匯入伺服器服務，處理解壓與複製作業。"""

    @staticmethod
    def _strip_single_top_dir(members: list[str]) -> str | None:
        """檢查壓縮檔內是否只有單一頂層目錄，若是則回傳該目錄名稱（含尾綴 /）。"""
        if not members:
            return None
        first = members[0]
        if first.endswith("/") and all(m.startswith(first) for m in members):
            return first
        return None

    @staticmethod
    def import_server(
        source: str | Path,
        servers_root: str | Path,
        *,
        allow_overwrite: bool = False,
        custom_name: str | None = None,
    ) -> Path:
        """
        執行匯入伺服器檔案或資料夾。

        Args:
            source: 來源檔案 (.zip) 或資料夾路徑。
            servers_root: 伺服器根目錄。
            allow_overwrite: 是否允許覆蓋已存在的目標目錄。
            custom_name: 指定匯入後的新資料夾名稱。

        Returns:
            匯入後的伺服器目標資料夾 Path。

        Raises:
            FileExistsError: 當目標目錄已存在且 allow_overwrite 為 False 時。
        """
        root = Path(servers_root)
        root.mkdir(parents=True, exist_ok=True)
        source_path = Path(source)
        name = custom_name if custom_name else (source_path.stem if source_path.is_file() else source_path.name)
        target = root / name

        if target.exists() and not allow_overwrite:
            raise FileExistsError(f"伺服器目錄已存在：{target}")

        if source_path.is_file():
            with zipfile.ZipFile(source_path) as archive:
                members = archive.namelist()
                top_dir = ImportServerService._strip_single_top_dir(members)
                if top_dir:
                    # 壓縮檔內含單一根目錄，剝離該層級直接解壓到 target
                    prefix_len = len(top_dir)
                    for zinfo in archive.infolist():
                        arc_name = zinfo.filename[prefix_len:]
                        if arc_name:  # 忽略最外層空資料夾本身
                            zinfo.filename = arc_name
                            archive.extract(zinfo, target)
                else:
                    archive.extractall(target)
        else:
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source_path, target)

        logger.info(f"成功匯入伺服器至：{target}")
        return target
