"""路徑工具模組。
提供專案中的路徑處理與檔案操作輔助函式。
"""

import contextlib
import ctypes
import hashlib
import json
import os
import shutil
import threading
import time
import traceback
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar
from .atomic_writer import atomic_write_json, best_effort_fsync
from .logger import get_logger

_windll = getattr(ctypes, "windll", None)
logger = get_logger().bind(component="PathUtils")


class PathUtils:
    """路徑處理工具類別，提供專案路徑管理和安全路徑操作"""

    _json_lock_registry_lock = threading.Lock()
    _json_path_locks: ClassVar[dict[str, threading.RLock]] = {}
    _json_write_retry_count = 3
    _json_write_retry_delay_sec = 0.03

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
        except OSError:
            return str(p.absolute())

    @staticmethod
    def _get_json_path_lock(path: Path | str) -> threading.RLock:
        """取得 JSON 路徑專用鎖，避免同進程併發覆寫。"""
        key = PathUtils._normalize_lock_key(path)
        with PathUtils._json_lock_registry_lock:
            lock = PathUtils._json_path_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                PathUtils._json_path_locks[key] = lock
            return lock

    @staticmethod
    def _save_json_internal(path: Path | str, data: Any, indent: int = 2, *, skip_if_unchanged: bool = False) -> bool:
        """JSON 寫入核心：使用路徑專屬鎖後呼叫統一的 atomic_write_json。

        行為保留原本的 `skip_if_unchanged` 檢查，但實際寫入委由
        `atomic_write_json` 處理，以統一原子替換策略與 fsync 行為。
        """
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
                ok = atomic_write_json(p, data, indent=indent)
                if ok:
                    PathUtils._best_effort_sync_dir(p.parent)
                return bool(ok)
        except (OSError, TypeError, ValueError):
            return False

    @staticmethod
    def is_path_within(base_dir: Path, target_path: Path, *, strict: bool = True) -> bool:
        """檢查 `target_path` 是否位於 `base_dir` 之下。

        Args:
            base_dir: 基準目錄。
            target_path: 待檢查路徑。
            strict: 是否要求目標路徑必須存在。

        Returns:
            若目標路徑位於基準目錄之下則回傳 True，否則回傳 False。
        """
        try:
            base_resolved = base_dir.resolve(strict=True)
            target_resolved = target_path.resolve(strict=strict)
        except FileNotFoundError:
            return False
        except OSError:
            return False
        try:
            target_resolved.relative_to(base_resolved)
            return True
        except ValueError:
            return False

    @staticmethod
    def safe_extract_zip(
        zip_path: Path, dest_dir: Path, progress_callback: Callable[[int, int], None] | None = None
    ) -> None:
        """安全地解壓縮 Zip 檔案，防止 Zip Slip 漏洞。

        Args:
            zip_path: Zip 檔案路徑。
            dest_dir: 解壓縮目的地。
            progress_callback: 進度回呼，接收 `(已處理位元組數, 總位元組數)`。

        progress_callback 會收到 (已解壓位元組數, 總位元組數)。
        """
        dest_dir = dest_dir.resolve()
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.infolist()
            total_bytes = sum(max(0, int(member.file_size)) for member in members if not member.is_dir())
            extracted_bytes = 0
            if progress_callback is not None:
                progress_callback(0, total_bytes)
            for member in members:
                member_path = dest_dir / member.filename
                if not PathUtils.is_path_within(dest_dir, member_path, strict=False):
                    raise ValueError(f"Zip File attempted path traversal: {member.filename}")
                if member.is_dir():
                    member_path.mkdir(parents=True, exist_ok=True)
                    continue
                member_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member, "r") as source, open(member_path, "wb") as target:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        target.write(chunk)
                        extracted_bytes += len(chunk)
                        if progress_callback is not None and total_bytes > 0:
                            progress_callback(extracted_bytes, total_bytes)
            if progress_callback is not None:
                progress_callback(total_bytes if total_bytes > 0 else extracted_bytes, total_bytes)

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
        """安全讀取 JSON 檔案。

        Args:
            path: JSON 檔案路徑。
            default: 讀取失敗時回傳的預設值。

        Returns:
            解析後的 JSON 內容，失敗時回傳預設值。
        """
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
        """安全寫入 JSON 檔案。

        Args:
            path: JSON 檔案路徑。
            data: 要寫入的資料。
            indent: JSON 縮排層級。

        Returns:
            若寫入成功則回傳 True，否則回傳 False。
        """
        return PathUtils._save_json_internal(path, data, indent=indent, skip_if_unchanged=False)

    @staticmethod
    def save_json_if_changed(path: Path | str, data: Any, indent: int = 2) -> bool:
        """僅在內容異動時才寫入 JSON。

        Args:
            path: JSON 檔案路徑。
            data: 要寫入的資料。
            indent: JSON 縮排層級。

        Returns:
            若寫入成功或內容未變更則回傳 True，否則回傳 False。
        """
        return PathUtils._save_json_internal(path, data, indent=indent, skip_if_unchanged=True)

    @staticmethod
    def read_json_from_zip(zip_path: Path | str, internal_path: str) -> Any | None:
        """從 Zip 檔案中讀取 JSON。

        Args:
            zip_path: Zip 檔案路徑。
            internal_path: Zip 內部檔案路徑。

        Returns:
            解析後的 JSON 內容，找不到或失敗時回傳 None。
        """
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                if internal_path in zf.namelist():
                    with zf.open(internal_path) as f:
                        return json.load(f)
        except (zipfile.BadZipFile, OSError, json.JSONDecodeError) as exc:
            logger.debug(
                "從 Zip 檔案讀取 JSON 失敗",
                zip_path=str(zip_path),
                internal_path=internal_path,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return None
        return None

    @staticmethod
    def to_json_str(data: Any, indent: int | None = None) -> str:
        """將資料轉換為 JSON 字串。

        Args:
            data: 要轉換的資料。
            indent: JSON 縮排層級。

        Returns:
            JSON 字串，失敗時回傳空字串。
        """
        try:
            return json.dumps(data, indent=indent, ensure_ascii=False)
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def from_json_str(json_str: str) -> Any:
        """從 JSON 字串解析資料。

        Args:
            json_str: JSON 文字。

        Returns:
            解析後的資料，失敗時回傳 None。
        """
        try:
            return json.loads(json_str)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

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
        """讀取文字檔案，統一處理編碼和錯誤。

        Args:
            path: 文字檔案路徑。
            encoding: 文字編碼。
            errors: 編碼錯誤處理方式。

        Returns:
            讀取到的文字內容，失敗時回傳 None。
        """
        return PathUtils._file_io_operation(path, "read_text", encoding=encoding, errors=errors)

    @staticmethod
    def write_text_file(path: Path, content: str, encoding: str = "utf-8", errors: str | None = None) -> bool:
        """寫入文字檔案，統一處理編碼和錯誤。

        Args:
            path: 文字檔案路徑。
            content: 要寫入的文字內容。
            encoding: 文字編碼。
            errors: 編碼錯誤處理方式。

        Returns:
            若寫入成功則回傳 True，否則回傳 False。
        """
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding=encoding, errors=errors) as f:
                f.write(content)
                f.flush()
                best_effort_fsync(f)
            return True
        except OSError:
            return False

    @staticmethod
    def ensure_dir_exists(path: Path) -> bool:
        """確保目錄存在，不存在則建立。

        Args:
            path: 目錄路徑。

        Returns:
            若建立成功則回傳 True，否則回傳 False。
        """
        try:
            path.mkdir(parents=True, exist_ok=True)
            return True
        except OSError:
            return False

    @staticmethod
    def read_bytes_file(path: Path) -> bytes | None:
        """讀取二進位檔案。

        Args:
            path: 檔案路徑。

        Returns:
            檔案位元組內容，失敗時回傳 None。
        """
        return PathUtils._file_io_operation(path, "read_bytes")

    @staticmethod
    def calculate_checksum(path: Path, algorithm: str = "sha256") -> str | None:
        """計算檔案雜湊值（檢查碼）。

        Args:
            path: 檔案路徑。
            algorithm: 雜湊演算法名稱。

        Returns:
            小寫十六進位雜湊字串，失敗時回傳 None。
        """
        try:
            if not path.exists():
                return None
            h = hashlib.new(algorithm)
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest().lower()
        except OSError:
            return None

    @staticmethod
    def delete_path(path: Path | str) -> bool:
        """刪除檔案或目錄。

        Args:
            path: 要刪除的路徑。

        Returns:
            若刪除成功則回傳 True，否則回傳 False。
        """
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
        """移動檔案或目錄。

        Args:
            src: 來源路徑。
            dst: 目的地路徑。

        Returns:
            若移動成功則回傳 True，否則回傳 False。
        """
        try:
            if not src.exists():
                return False
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(src, dst)
            return True
        except OSError:
            return False

    @staticmethod
    def copy_file(src: Path, dst: Path) -> bool:
        """複製檔案。

        Args:
            src: 來源檔案路徑。
            dst: 目的地檔案路徑。

        Returns:
            若複製成功則回傳 True，否則回傳 False。
        """
        try:
            if not src.exists():
                return False
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return True
        except OSError:
            return False

    @staticmethod
    def copy_dir(
        src: Path,
        dst: Path,
        ignore_patterns: list[str] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> bool:
        """複製目錄。

        Args:
            src: 來源目錄。
            dst: 目的地目錄。
            ignore_patterns: 要忽略的樣式列表。
            progress_callback: 進度回呼，接收 `(已複製檔案數, 總檔案數)`。

        progress_callback 會收到 (已複製檔案數, 總檔案數)。

        Returns:
            若複製成功則回傳 True，否則回傳 False。
        """
        try:
            if not src.exists() or not src.is_dir():
                return False
            ignore = shutil.ignore_patterns(*ignore_patterns) if ignore_patterns else None

            def _walk_entries() -> list[tuple[Path, list[str], list[str]]]:
                entries: list[tuple[Path, list[str], list[str]]] = []
                for root, dirs, files in os.walk(src, topdown=True):
                    root_path = Path(root)
                    if ignore is not None:
                        ignored = set(ignore(str(root_path), [*dirs, *files]))
                        dirs[:] = [name for name in dirs if name not in ignored]
                        files = [name for name in files if name not in ignored]
                    entries.append((root_path, list(dirs), list(files)))
                return entries

            entries = _walk_entries()
            total_files = sum((len(files) for _root, _dirs, files in entries))
            copied_files = 0
            dst.mkdir(parents=True, exist_ok=True)
            if progress_callback is not None:
                progress_callback(0, total_files)
            for root_path, dirs, files in entries:
                relative_root = root_path.relative_to(src)
                target_root = dst if relative_root == Path(".") else dst / relative_root
                target_root.mkdir(parents=True, exist_ok=True)
                for dir_name in dirs:
                    (target_root / dir_name).mkdir(parents=True, exist_ok=True)
                for file_name in files:
                    shutil.copy2(root_path / file_name, target_root / file_name)
                    copied_files += 1
                    if progress_callback is not None and total_files > 0:
                        progress_callback(copied_files, total_files)
            if progress_callback is not None:
                progress_callback(copied_files, total_files)
            return True
        except OSError:
            return False

    @staticmethod
    def find_executable(name: str) -> str | None:
        """尋找執行檔路徑。

        Args:
            name: 執行檔名稱。

        Returns:
            找到時回傳完整路徑，否則回傳 None。
        """
        return shutil.which(name)

    @staticmethod
    def get_long_path(path: Path | str) -> Path:
        """將 Windows 的短路徑（8.3 格式）展開為完整長路徑。

        Args:
            path: 原始路徑。

        Returns:
            展開後的長路徑；失敗時回傳原始 Path。
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
                    return p_obj
                if needed > buf_len:
                    buf_len = needed
                    continue
                return Path(buf.value)
        except (OSError, AttributeError):
            return Path(path)

    @staticmethod
    def mark_issue(path: Path | str, reason: str, details: Any | None = None) -> bool:
        """在專案根目錄下的 `.issues/` 中建立或更新聚合的 issue marker。

                Args:
                        path: 原始檔案路徑。
                        reason: issue 原因。
                        details: 額外細節資訊。

        行為：
        - 針對同一個原始檔案（原始路徑相同）會聚合至同一份 JSON 檔，位於
          `<project>/.issues/<relative_path>/<filename>.issue.json`。
        - 若原始檔不在專案根目錄下，會放在 `<project>/.issues/external/<name>.<sha256>.issue.json`。
        - 每個 marker 檔案包含 `path` (原始路徑) 與 `entries` (issue 列表)，新的 issue 會附加到 `entries`。

        這樣可減少檔案數量，且利於集中清理、UI 掃描與 TTL 管理。

        Returns:
            若建立或更新成功則回傳 True，否則回傳 False。
        """
        try:
            p = Path(path)
            project_root = PathUtils.get_project_root()
            issues_root = project_root / ".issues"
            issues_root.mkdir(parents=True, exist_ok=True)

            # 決定聚合 marker 的路徑
            try:
                rel = p.relative_to(project_root)
                agg_dir = issues_root / rel.parent
                agg_dir.mkdir(parents=True, exist_ok=True)
                agg_marker = agg_dir / f"{rel.name}.issue.json"
            except ValueError:
                # 原始檔不在專案下，使用 external + path hash (SHA-256)
                key = hashlib.sha256(str(p).encode("utf-8")).hexdigest()
                ext_dir = issues_root / "external"
                ext_dir.mkdir(parents=True, exist_ok=True)
                agg_marker = ext_dir / f"{p.name}.{key}.issue.json"

            now = int(time.time())
            exc_type = ""
            tb_text = ""
            if isinstance(details, dict):
                exc_type = str(details.get("exception_type") or "")
                tb_text = str(details.get("traceback_summary") or "")
            elif isinstance(details, BaseException):
                exc_type = type(details).__name__
                tb = getattr(details, "__traceback__", None)
                try:
                    if tb is not None:
                        tb_text = "".join(traceback.format_exception(type(details), details, tb))
                    else:
                        tb_text = "".join(traceback.format_exception_only(type(details), details)).strip()
                except Exception:
                    tb_text = str(details)

            entry = {
                "timestamp": now,
                "reason": str(reason),
                "details": details if details is not None else "",
                "exception_type": exc_type,
                "traceback_summary": tb_text,
            }

            # 讀取既有聚合檔並 append
            lock = PathUtils._get_json_path_lock(agg_marker)
            with lock:
                existing = None
                if agg_marker.exists():
                    try:
                        with open(agg_marker, encoding="utf-8") as f:
                            existing = json.load(f)
                    except (OSError, json.JSONDecodeError):
                        existing = None
                if not existing or not isinstance(existing, dict):
                    payload = {"path": str(p), "entries": [entry], "last_updated": now}
                else:
                    entries = existing.get("entries") if isinstance(existing.get("entries"), list) else []
                    entries.append(entry)
                    existing["entries"] = entries
                    existing["last_updated"] = now
                    payload = existing

                ok = PathUtils._save_json_internal(agg_marker, payload, indent=2, skip_if_unchanged=False)
                if not ok:
                    logger.debug(f"建立或更新聚合 issue marker 失敗: {agg_marker}")
                return bool(ok)
        except Exception as e:
            logger.debug(f"建立聚合 issue marker 發生錯誤: {path} | {e}")
            return False

    @staticmethod
    def list_issue_markers(root: Path | str | None = None) -> list[dict]:
        """列出集中儲存的聚合 issue marker。

        Args:
            root: 掃描根目錄；未提供時預設為專案根目錄。

        Returns:
            由 marker 路徑與內容組成的清單。

        若 `root` 為 None，預設掃描專案根目錄下的 `.issues/`。
        回傳格式：[{"marker": "<path>", "data": {...}}, ...]
        """
        try:
            root_path = Path(root) if root is not None else PathUtils.get_project_root()
            issues_root = root_path / ".issues"
            markers: list[dict] = []
            if not issues_root.exists():
                return markers
            for p in issues_root.rglob("*.issue.json"):
                try:
                    with open(p, encoding="utf-8") as f:
                        data = json.load(f)
                except (OSError, json.JSONDecodeError):
                    data = None
                markers.append({"marker": str(p), "data": data})
            return markers
        except OSError:
            return []

    @staticmethod
    def recover_issue_marker(marker_path: Path | str, remove_marker: bool = True) -> bool:
        """嘗試從標記檔回復/清理。

        Args:
            marker_path: 標記檔或原始檔路徑。
            remove_marker: 是否在成功時刪除 marker。

        Returns:
            若成功找到並處理 marker 則回傳 True，否則回傳 False。

        - 如果標記檔存在且 remove_marker=True，會刪除該標記（因為原始檔仍保留）。
        - 若需要更進一步的自動復原（例如移動檔案），應在外層實作並在執行前徵求使用者同意。
        此方法設計為非破壞性（只移除標記），避免在自動化時造成檔案遺失。
        """
        try:
            p = Path(marker_path)
            project_root = PathUtils.get_project_root()
            issues_root = project_root / ".issues"

            # 如果傳入的是聚合 marker 檔本身
            if p.exists() and issues_root in p.parents:
                if remove_marker:
                    p.unlink()
                return True

            # 否則視為原始檔路徑，嘗試找出對應的聚合 marker，並刪除
            try:
                rel = Path(p).relative_to(project_root)
                candidate = issues_root / rel.parent / f"{rel.name}.issue.json"
            except ValueError:
                key = hashlib.sha256(str(p).encode("utf-8")).hexdigest()
                candidate = issues_root / "external" / f"{p.name}.{key}.issue.json"

            if candidate.exists():
                if remove_marker:
                    candidate.unlink()
                return True
            return False
        except OSError:
            return False

    @staticmethod
    def auto_prune_markers(root: Path | str | None = None, max_age_days: int = 365) -> list[str]:
        """針對集中式聚合 markers 執行過期清理與條目修剪。

        Args:
            root: 掃描根目錄；未提供時預設為專案根目錄。
            max_age_days: 保留天數上限。

        規則（保守）：針對每個聚合檔案，會移除 entries 中 timestamp 早於 cutoff 的項目；
        若 entries 被清空且原始檔不存在，則刪除整個聚合檔。

        Returns:
            被移除或更新的聚合檔路徑清單。
        回傳被移除的聚合檔路徑清單。
        """
        removed: list[str] = []
        try:
            root_path = Path(root) if root is not None else PathUtils.get_project_root()
            issues_root = root_path / ".issues"
            if not issues_root.exists():
                return removed
            cutoff = time.time() - max_age_days * 24 * 3600
            for p in issues_root.rglob("*.issue.json"):
                try:
                    st = p.stat()
                except OSError:
                    continue
                try:
                    with open(p, encoding="utf-8") as f:
                        data = json.load(f)
                except (OSError, json.JSONDecodeError):
                    data = None
                if not data or not isinstance(data, dict):
                    # 若檔案無法解析且已經很久沒更新，刪除
                    if st.st_mtime < cutoff:
                        try:
                            p.unlink()
                            removed.append(str(p))
                        except OSError:
                            continue
                    continue

                entries = data.get("entries") if isinstance(data.get("entries"), list) else []
                new_entries = [e for e in entries if int(e.get("timestamp", 0)) >= cutoff]
                if len(new_entries) != len(entries):
                    # 更新或刪除該聚合檔
                    if new_entries:
                        data["entries"] = new_entries
                        data["last_updated"] = int(time.time())
                        with contextlib.suppress(Exception):
                            PathUtils._save_json_internal(p, data, indent=2, skip_if_unchanged=False)
                    else:
                        # 若沒有剩餘條目，僅在原始檔不存在時刪除
                        orig = Path(data.get("path", "")) if isinstance(data.get("path"), str) else None
                        if orig is None or not orig.exists():
                            try:
                                p.unlink()
                                removed.append(str(p))
                            except OSError:
                                continue
            return removed
        except OSError:
            return removed
