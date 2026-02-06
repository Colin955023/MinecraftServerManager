#!/usr/bin/env python3
"""路徑工具模組
Path Utilities Module
"""

import ctypes
import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any


class PathUtils:
    """路徑處理工具類別，提供專案路徑管理和安全路徑操作"""

    @staticmethod
    def is_path_within(base_dir: Path, target_path: Path, *, strict: bool = True) -> bool:
        """檢查 target_path 是否位於 base_dir 之下"""
        try:
            base_resolved = base_dir.resolve(strict=True)
            target_resolved = target_path.resolve(strict=strict)
        except FileNotFoundError:
            return False
        except Exception:
            return False

        try:
            target_resolved.relative_to(base_resolved)
            return True
        except ValueError:
            return False

    @staticmethod
    def safe_extract_zip(zip_path: Path, dest_dir: Path) -> None:
        """安全地解壓縮 Zip 檔案，防止 Zip Slip 漏洞"""
        dest_dir = dest_dir.resolve()
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                member_path = dest_dir / member.filename
                if not PathUtils.is_path_within(dest_dir, member_path, strict=False):
                    raise ValueError(f"Zip File attempted path traversal: {member.filename}")

                # 執行解壓縮
                # Perform extraction
                zf.extract(member, dest_dir)

    @staticmethod
    def get_project_root() -> Path:
        """獲取專案根目錄路徑"""
        return Path(__file__).parent.parent.parent

    @staticmethod
    def get_assets_path() -> Path:
        """獲取 assets 目錄路徑"""
        return PathUtils.get_project_root() / "assets"

    @staticmethod
    def load_json(path: Path | str, default: Any = None) -> Any:
        """安全讀取 JSON 檔案"""
        try:
            p = Path(path)
            if not p.exists():
                return default
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    @staticmethod
    def save_json(path: Path | str, data: Any, indent: int = 2) -> bool:
        """安全寫入 JSON 檔案"""
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = PathUtils.get_long_path(p.with_suffix(p.suffix + ".tmp"))
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=indent, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            PathUtils.move_path(tmp_path, p)
            return True
        except Exception:
            return False

    @staticmethod
    def read_json_from_zip(zip_path: Path | str, internal_path: str) -> Any | None:
        """從 Zip 檔案中讀取 JSON"""
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                if internal_path in zf.namelist():
                    with zf.open(internal_path) as f:
                        return json.load(f)
        except Exception:
            return None
        return None

    @staticmethod
    def to_json_str(data: Any, indent: int | None = None) -> str:
        """將資料轉換為 JSON 字串"""
        try:
            return json.dumps(data, indent=indent, ensure_ascii=False)
        except Exception:
            return ""

    @staticmethod
    def from_json_str(json_str: str) -> Any:
        """從 JSON 字串解析資料"""
        try:
            return json.loads(json_str)
        except Exception:
            return None

    # ====== 文件 I/O 操作（統一的內部實現） ======
    @staticmethod
    def _file_io_operation(path: Path, operation: str, **kwargs) -> Any:
        """通用的檔案 I/O 操作（內部使用）"""
        try:
            if operation == "read_text":
                if not path.exists():
                    return None
                encoding = kwargs.get("encoding", "utf-8")
                errors = kwargs.get("errors", "replace")
                return path.read_text(encoding=encoding, errors=errors)
            if operation == "write_text":
                path.parent.mkdir(parents=True, exist_ok=True)
                content = kwargs.get("content", "")
                encoding = kwargs.get("encoding", "utf-8")
                errors = kwargs.get("errors")
                path.write_text(content, encoding=encoding, errors=errors)
                return True
            if operation == "read_bytes":
                if not path.exists():
                    return None
                return path.read_bytes()
            if operation == "write_bytes":
                path.parent.mkdir(parents=True, exist_ok=True)
                content = kwargs.get("content", b"")
                path.write_bytes(content)
                return True
        except OSError:
            return None if operation.startswith("read") else False
        else:
            raise ValueError(f"Unknown operation: {operation}")

    @staticmethod
    def read_text_file(path: Path, encoding: str = "utf-8", errors: str = "replace") -> str | None:
        """讀取文字檔案，統一處理編碼和錯誤"""
        return PathUtils._file_io_operation(path, "read_text", encoding=encoding, errors=errors)

    @staticmethod
    def write_text_file(path: Path, content: str, encoding: str = "utf-8", errors: str | None = None) -> bool:
        """寫入文字檔案，統一處理編碼和錯誤"""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding=encoding, errors=errors) as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            return True
        except OSError:
            return False

    @staticmethod
    def ensure_dir_exists(path: Path) -> bool:
        """確保目錄存在，不存在則創建"""
        try:
            path.mkdir(parents=True, exist_ok=True)
            return True
        except OSError:
            return False

    @staticmethod
    def read_bytes_file(path: Path) -> bytes | None:
        """讀取二進制檔案"""
        return PathUtils._file_io_operation(path, "read_bytes")

    @staticmethod
    def calculate_checksum(path: Path, algorithm: str = "sha256") -> str | None:
        """計算檔案雜湊值 (檢查碼)"""
        try:
            if not path.exists():
                return None
            h = hashlib.new(algorithm)
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest().lower()
        except Exception:
            return None

    @staticmethod
    def delete_path(path: Path | str) -> bool:
        """刪除檔案或目錄"""
        try:
            if isinstance(path, str):
                path = Path(path)
            if not path.exists():
                return True
            if path.is_dir():
                if path == PathUtils.get_project_root():
                    return False
                shutil.rmtree(path)
            else:
                path.unlink()
            return True
        except OSError:
            return False

    @staticmethod
    def move_path(src: Path, dst: Path) -> bool:
        """移動檔案或目錄"""
        try:
            if not src.exists():
                return False
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return True
        except OSError:
            return False

    @staticmethod
    def copy_file(src: Path, dst: Path) -> bool:
        """複製檔案"""
        try:
            if not src.exists():
                return False
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return True
        except OSError:
            return False

    @staticmethod
    def copy_dir(src: Path, dst: Path, ignore_patterns: list[str] | None = None) -> bool:
        """複製目錄"""
        try:
            ignore = shutil.ignore_patterns(*ignore_patterns) if ignore_patterns else None
            shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True)
            return True
        except OSError:
            return False

    @staticmethod
    def find_executable(name: str) -> str | None:
        """尋找執行檔路徑"""
        return shutil.which(name)

    @staticmethod
    def get_long_path(path: Path | str) -> Path:
        """
        將 Windows 的短路徑（8.3 格式）展開為完整長路徑，使用 GetLongPathNameW。
        若非 Windows 平台或展開失敗，則回傳原始的 Path 物件不做修改。
        """
        try:
            p_obj = Path(path)
            p_str = str(p_obj)

            GetLongPathNameW = ctypes.windll.kernel32.GetLongPathNameW
            GetLongPathNameW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
            GetLongPathNameW.restype = ctypes.c_uint

            buf_len = 260
            while True:
                buf = ctypes.create_unicode_buffer(buf_len)
                needed = GetLongPathNameW(p_str, buf, buf_len)
                if needed == 0:
                    # 失敗時回傳原始路徑
                    return p_obj
                if needed > buf_len:
                    # 緩衝區不足，調整後重試
                    buf_len = needed
                    continue
                # 成功取得長路徑
                return Path(buf.value)
        except Exception:
            return Path(path)
