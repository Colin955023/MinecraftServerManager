"""Loader installer 行程執行與輸出收集"""

from __future__ import annotations

import locale
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from src.models import ProgressEvent
from src.utils import SubprocessUtils, SystemUtils, get_logger

logger = get_logger().bind(component="LoaderInstaller")
_MAX_RUNTIME_SECONDS = 15 * 60
_MAX_OUTPUT_LINES = 2000
_MAX_LINE_BYTES = 16 * 1024
_PERCENT_PATTERN = re.compile(r"(?<!\d)(100|\d{1,2})(?:\.\d+)?\s*%")
_FRACTION_PATTERN = re.compile(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)")


class InstallerProgressTracker:
    """
    將沒有正式百分比的 Java installer 文字輸出轉為單調遞增的估算進度

    Forge 類 installer 的 headless callback 與 Fabric 類 installer 主要輸出 stage/message
    因此優先採用明確百分比或分數，其餘使用已知階段與輸出密度估算
    """

    def __init__(self, loader_type: str) -> None:
        self.loader_type = loader_type
        self._progress = 0.0
        self._library_lines = 0
        self._last_normalized = ""

    def update(self, text: str) -> ProgressEvent:
        """
        解析單行 installer 輸出並回傳可判定進度

        Args:
            text: Java installer 的單行標準輸出

        Returns:
            total_units 固定為 100 的單調遞增事件
        """
        parsed = parse_installer_progress(self.loader_type, text)
        explicit = parsed.phase_percent
        if explicit is not None:
            self._progress = max(self._progress, min(99.0, explicit))
        else:
            self._progress = max(self._progress, self._estimate(text))
        completed = min(99, max(1, int(self._progress)))
        display_text = text if len(text) <= 80 else text[:77] + "..."
        return ProgressEvent(
            "installer",
            f"正在執行 {self.loader_type} 安裝: {display_text}",
            completed,
            100,
        )

    def _estimate(self, text: str) -> float:
        normalized = " ".join(text.casefold().split())
        if not normalized:
            return self._progress
        if normalized == self._last_normalized:
            return self._progress
        self._last_normalized = normalized

        success_markers = (
            "successfully installed",
            "installation complete",
            "install complete",
            "finished successfully",
            "server installed",
        )
        if any(marker in normalized for marker in success_markers):
            return 98.0

        if any(marker in normalized for marker in ("patching", "merging", "writing patched", "remapping")):
            return max(self._progress, 84.0)

        if any(
            marker in normalized
            for marker in (
                "running processor",
                "executing processor",
                "building processors",
                "processing ",
                "processors:",
            )
        ):
            return max(self._progress, 68.0)

        if "library" in normalized or "libraries" in normalized:
            self._library_lines += 1
            density_progress = min(64.0, 34.0 + self._library_lines / 4.0)
            if any(marker in normalized for marker in ("download", "downloading", "considering", "installing")):
                return max(self._progress, density_progress)
            return max(self._progress, 30.0)

        if "minecraft server" in normalized:
            return max(self._progress, 20.0 if "download" in normalized else 15.0)

        if "installing" in normalized and any(
            marker in normalized for marker in ("server", "fabric loader", "quilt loader", "forge", "neoforge")
        ):
            return max(self._progress, 10.0)

        if "installer" in normalized or normalized.startswith(("jvm info:", "current time:")):
            return max(self._progress, min(8.0, self._progress + 1.0))

        if self._progress < 30.0:
            return min(30.0, self._progress + 1.0)
        if self._progress < 68.0:
            return min(68.0, self._progress + 0.5)
        return min(94.0, self._progress + 0.25)


def parse_installer_progress(loader_type: str, text: str) -> ProgressEvent:
    """
    將 Loader installer 輸出轉成可判定或不定進度事件

    Args:
        loader_type: Loader 名稱
        text: 安裝器輸出文字

    Returns:
        具百分比、分數或不定進度的事件
    """
    message = f"正在執行 {loader_type} 安裝: {text}"
    if match := _PERCENT_PATTERN.search(text):
        percent = min(100, int(float(match.group(1))))
        return ProgressEvent("installer", message, percent, 100)
    if match := _FRACTION_PATTERN.search(text):
        completed, total = int(match.group(1)), int(match.group(2))
        if total > 0 and completed <= total:
            return ProgressEvent("installer", message, completed, total)
    return ProgressEvent("installer", message)


def _decode_stream_line(raw: bytes) -> str:
    if not raw:
        return ""
    with suppress(UnicodeDecodeError):
        return raw.decode("utf-8")
    for encoding in ("cp950", "big5", "gbk", "cp936", locale.getpreferredencoding(False)):
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError, LookupError:
            continue
    return raw.decode("utf-8", errors="replace")


def _cleanup_process(process, base_dir: Path, managed_process) -> None:
    if process is None:
        return
    try:
        if managed_process is not None and (process.poll() is None or bool(getattr(process, "cancelled", False))):
            SystemUtils.kill_process_tree(managed_process)
        elif process.poll() is None:
            process.kill()
    except Exception as e:
        logger.warning(f"終止安裝器行程樹失敗: {e}")
    try:
        SystemUtils.kill_java_processes_in_path(base_dir)
    except Exception as e:
        logger.warning(f"清理安裝器 Java 行程失敗: {e}")
    with suppress(Exception):
        SystemUtils.unregister_managed_process(base_dir, managed_process)


def run_installer_process(
    *,
    installer_args: list[str],
    base_dir: Path,
    loader_type: str,
    progress_callback: Callable[[ProgressEvent], None] | None,
    cancel_check: Callable[[], bool],
    fail_callback: Callable[[str], bool],
    post_install_result: Callable[[Path, str], str | None] | None = None,
) -> bool | str:
    """
    執行 installer，管理輸出、取消、逾時與行程清理

    Args:
        installer_args: 要傳給安裝器程序的命令列參數
        base_dir: 安裝器工作的伺服器目錄
        loader_type: Loader 類型名稱
        progress_callback: 接收安裝器輸出狀態的回呼
        cancel_check: 判斷是否已要求取消的回呼
        fail_callback: 將失敗訊息轉成外部結果的回呼
        post_install_result: 安裝成功後解析啟動目標的回呼

    Returns:
        成功時回傳 True，取消時回傳 False，或回呼提供的結果
    """
    process = None
    managed_process = None
    try:
        process = SubprocessUtils.create_no_window_process(installer_args, cwd=str(base_dir))
        managed_process = SystemUtils.register_managed_process(base_dir, int(process.pid))
        output_lines: deque[str] = deque(maxlen=_MAX_OUTPUT_LINES)
        error_lines: deque[str] = deque(maxlen=_MAX_OUTPUT_LINES)
        progress_tracker = InstallerProgressTracker(loader_type)

        def read_stream(stream, sink: deque[str], is_err: bool = False) -> None:
            try:
                while True:
                    try:
                        line = stream.readline(_MAX_LINE_BYTES + 1)
                    except TypeError:
                        line = stream.readline()
                    if not line:
                        break
                    text = _decode_stream_line(line[:_MAX_LINE_BYTES]).strip()
                    if len(line) > _MAX_LINE_BYTES:
                        text += "…[已截斷]"
                    if not text:
                        continue
                    sink.append(text)
                    if is_err:
                        logger.warning(f"[{loader_type} stderr] {text}")
                    else:
                        if progress_callback and not cancel_check():
                            progress_callback(progress_tracker.update(text))
            except Exception as e:
                logger.debug(f"讀取安裝程序輸出例外: {e}")
            finally:
                with suppress(Exception):
                    stream.close()

        t_out = threading.Thread(target=read_stream, args=(process.stdout, output_lines, False), daemon=True)
        t_err = threading.Thread(target=read_stream, args=(process.stderr, error_lines, True), daemon=True)
        t_out.start()
        t_err.start()

        deadline = time.monotonic() + _MAX_RUNTIME_SECONDS
        while process.poll() is None:
            if cancel_check():
                process.cancelled = True
                _cleanup_process(process, base_dir, managed_process)
                t_out.join(timeout=2.0)
                t_err.join(timeout=2.0)
                return False
            if time.monotonic() >= deadline:
                process.cancelled = True
                _cleanup_process(process, base_dir, managed_process)
                t_out.join(timeout=2.0)
                t_err.join(timeout=2.0)
                return fail_callback(f"{loader_type} 安裝程序執行逾時，已終止程序")
            time.sleep(0.3)

        t_out.join(timeout=2.0)
        t_err.join(timeout=2.0)
        if process.returncode != 0:
            out_str = "\n".join(list(output_lines)[-50:])
            err_str = "\n".join(list(error_lines)[-50:])
            logger.error(
                f"{loader_type} 安裝程序失敗 (代碼 {process.returncode})\nSTDOUT: {out_str}\nSTDERR: {err_str}"
            )
            _cleanup_process(process, base_dir, managed_process)
            failure_detail = next(
                (line for line in reversed(error_lines) if "Caused by:" in line),
                error_lines[-1] if error_lines else "",
            )
            message = f"{loader_type} 安裝程序執行失敗"
            return fail_callback(f"{message}: {failure_detail}" if failure_detail else message)

        with suppress(Exception):
            SystemUtils.unregister_managed_process(base_dir, managed_process)
        if progress_callback:
            progress_callback(ProgressEvent("installer_cleanup", "安裝成功，正在清理暫存檔案...", 1, 1))
        if post_install_result is not None:
            result = post_install_result(base_dir, loader_type)
            if result is not None:
                return result
            return fail_callback(f"{loader_type} 安裝完成但找不到啟動腳本 (run.bat)")
        return True
    except Exception as e:
        logger.exception(f"執行 {loader_type} 安裝器時發生錯誤: {e}")
        _cleanup_process(process, base_dir, managed_process)
        return fail_callback(f"執行 {loader_type} 安裝器時發生錯誤：{e}")


__all__ = ["run_installer_process"]
