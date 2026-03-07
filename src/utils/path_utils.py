#!/usr/bin/env python3
"""路徑工具模組
Path Utilities Module
"""

import ctypes
import hashlib
import json
import os
import shutil
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, ClassVar

from .logger import get_logger

_windll = getattr(ctypes, "windll", None)
logger = get_logger().bind(component="PathUtils")


class PathUtils:
    """路徑處理工具類別，提供專案路徑管理和安全路徑操作"""

    _json_lock_registry_lock = threading.Lock()
    _json_path_locks: ClassVar[dict[str, threading.Lock]] = {}
    _json_write_retry_count = 3
    _json_write_retry_delay_sec = 0.03

    @staticmethod
    def _best_effort_fsync(file_obj: Any) -> None:
        """盡力同步檔案內容到磁碟；不支援時忽略錯誤。"""
        try:
            os.fsync(file_obj.fileno())
        except (AttributeError, OSError, ValueError):
            return

    @staticmethod
    def _best_effort_sync_dir(path: Path) -> None:
        """盡力同步目錄 metadata；不支援時忽略錯誤。"""
        try:
            fd = os.open(str(path), os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            return
        finally:
            os.close(fd)

    @staticmethod
    def _normalize_lock_key(path: Path | str) -> str:
        """將路徑正規化為鎖的 key，確保同一路徑共用同一把鎖。"""
        p = Path(path)
        try:
            return str(p.resolve())
        except Exception:
            return str(p.absolute())

    @staticmethod
    def _get_json_path_lock(path: Path | str) -> threading.Lock:
        """取得 JSON 路徑專用鎖，避免同進程併發覆寫。"""
        key = PathUtils._normalize_lock_key(path)
        with PathUtils._json_lock_registry_lock:
            lock = PathUtils._json_path_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                PathUtils._json_path_locks[key] = lock
            return lock

    @staticmethod
    def _save_json_internal(path: Path | str, data: Any, indent: int = 2, *, skip_if_unchanged: bool = False) -> bool:
        """JSON 寫入核心：序列化、路徑鎖、原子替換與重試。"""
        try:
            payload = json.dumps(data, indent=indent, ensure_ascii=False)
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            lock = PathUtils._get_json_path_lock(p)

            with lock:
                if skip_if_unchanged and p.exists():
                    try:
                        if p.read_text(encoding="utf-8") == payload:
                            return True
                    except OSError as e:
                        logger.debug(f"讀取既有 JSON 失敗，將改為覆寫流程: {p} | {e}")

                for attempt in range(PathUtils._json_write_retry_count):
                    tmp_name = f"{p.name}.{os.getpid()}.{threading.get_ident()}.{attempt}.tmp"
                    tmp_path = PathUtils.get_long_path(p.with_name(tmp_name))
                    try:
                        with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
                            f.write(payload)
                            f.flush()
                            PathUtils._best_effort_fsync(f)

                        os.replace(tmp_path, p)
                        PathUtils._best_effort_sync_dir(p.parent)
                        return True
                    except OSError:
                        if attempt + 1 >= PathUtils._json_write_retry_count:
                            return False
                        time.sleep(PathUtils._json_write_retry_delay_sec * (attempt + 1))
                    finally:
                        try:
                            if tmp_path.exists():
                                tmp_path.unlink()
                        except OSError as e:
                            logger.debug(f"清理臨時 JSON 檔失敗: {tmp_path} | {e}")

            return False
        except Exception:
            return False

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

                if member.is_dir():
                    member_path.mkdir(parents=True, exist_ok=True)
                    continue

                member_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member, "r") as source, open(member_path, "wb") as target:
                    shutil.copyfileobj(source, target)

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
        return PathUtils._save_json_internal(path, data, indent=indent, skip_if_unchanged=False)

    @staticmethod
    def save_json_if_changed(path: Path | str, data: Any, indent: int = 2) -> bool:
        """僅在內容異動時才寫入 JSON（同樣使用原子寫入流程）。"""
        return PathUtils._save_json_internal(path, data, indent=indent, skip_if_unchanged=True)

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
                PathUtils._best_effort_fsync(f)
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
        展開失敗時回傳原始 Path。
        """
        try:
            p_obj = Path(path)
            p_str = str(p_obj)

            if _windll is None:
                return p_obj

            GetLongPathNameW = _windll.kernel32.GetLongPathNameW
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
