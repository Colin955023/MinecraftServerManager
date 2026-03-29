"""
應用程式重啟工具模組
提供安全的應用程式重啟功能，支援打包執行檔與 Python 腳本模式
"""

import contextlib
import os
import sys
import threading
import time
from pathlib import Path
from . import PathUtils, SubprocessUtils, UIUtils, get_logger, shutdown_logging

logger = get_logger().bind(component="AppRestart")


class AppRestart:
    """應用程式重啟管理類別"""

    @staticmethod
    def _prefer_windowless_python(interpreter: str | None) -> str | None:
        """在 Windows 腳本模式下，若可用則優先改用 pythonw.exe 以避免跳出 console。"""
        if os.name != "nt" or not interpreter:
            return interpreter
        try:
            interpreter_path = Path(interpreter)
            if interpreter_path.name.lower() != "python.exe":
                return interpreter
            pythonw_path = interpreter_path.with_name("pythonw.exe")
            if pythonw_path.exists() and pythonw_path.is_file():
                return str(pythonw_path)
        except Exception as e:
            logger.debug(f"選擇 pythonw.exe 失敗，保留原解譯器: {e}")
        return interpreter

    @staticmethod
    def _extract_exe_candidate(executable_path: list[str]) -> str | None:
        """從執行檔路徑列表中提取第一個候選執行檔路徑"""
        try:
            if isinstance(executable_path, list) and len(executable_path) > 0:
                return executable_path[0]
        except (IndexError, TypeError, AttributeError):
            return None
        return None

    @staticmethod
    def _get_executable_info() -> tuple[list[str], bool, Path | None]:
        """取得當前應用程式的執行檔資訊，區分打包檔案與 Python 腳本模式"""
        exe_path: Path | None = None
        try:
            exe_path = Path(sys.executable) if sys.executable else None
        except Exception:
            exe_path = None
        is_frozen = False
        try:
            if exe_path is not None and exe_path.suffix.lower() == ".exe" and ("python" not in exe_path.name.lower()):
                is_frozen = True
        except Exception:
            is_frozen = False
        try:
            if not is_frozen and hasattr(sys, "_MEIPASS"):
                is_frozen = True
                if exe_path is None and getattr(sys, "executable", None):
                    with contextlib.suppress(Exception):
                        exe_path = Path(sys.executable)
            if not is_frozen and sys.argv and sys.argv[0]:
                try:
                    _argv0 = Path(sys.argv[0])
                    if _argv0.suffix.lower() == ".exe":
                        is_frozen = True
                        if exe_path is None:
                            exe_path = _argv0
                except Exception as e:
                    logger.debug(f"解析 argv[0] 為 exe 時發生例外: {e}")
        except Exception as e:
            logger.debug(f"檢查打包標記時發生例外: {e}")
        if not is_frozen:
            is_frozen = bool(getattr(sys, "frozen", False) or getattr(sys, "__compiled__", False))
        if is_frozen:
            try:
                if exe_path is not None and "python" in exe_path.name.lower():
                    alt = None
                    try:
                        if sys.argv and sys.argv[0]:
                            a = Path(sys.argv[0])
                            if a.suffix.lower() == ".exe" and a.exists():
                                alt = a
                    except Exception:
                        alt = None
                    if alt is None:
                        try:
                            fb = AppRestart._find_exe_fallback()
                            if fb is not None:
                                alt = fb
                        except Exception:
                            alt = None
                    if alt is not None:
                        exe_path = alt
            except Exception as e:
                logger.debug(f"取得執行檔資訊時發生錯誤，嘗試使用備援方案: {e}")
            exe_str = str(exe_path) if exe_path is not None else str(sys.executable) if sys.executable else ""
            return ([exe_str], True, None)
        try:
            argv0 = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
            if (
                argv0
                and argv0.exists()
                and (argv0.suffix.lower() == ".exe")
                and ("minecraftservermanager" in argv0.name.lower())
            ):
                return ([str(argv0)], True, None)
        except Exception as e:
            logger.debug(f"argv0 偵測失敗: {e}")
        script_path: Path | None = None
        try:
            candidate = Path(__file__).parent.parent / "main.py"
            if candidate.exists() and candidate.is_file():
                script_path = candidate
            else:
                found = AppRestart._find_main_in_parents(Path(__file__).parent.parent, max_levels=6)
                if found:
                    script_path = found
                else:
                    found2 = AppRestart._find_main_in_parents(Path.cwd(), max_levels=6)
                    if found2:
                        script_path = found2
        except Exception:
            script_path = None
        exe_val = str(sys.executable) if sys.executable else ""
        script_val = str(script_path) if script_path is not None else ""
        return ([exe_val, script_val], False, script_path)

    @staticmethod
    def _find_main_in_parents(start_dir: Path | str, max_levels: int = 5) -> Path | None:
        """從起始目錄向上搜尋可能包含 main.py 的候選位置。"""
        try:
            p = Path(start_dir).resolve(strict=False)
            cur = p
            for _ in range(max_levels + 1):
                candidate = cur / "src" / "main.py"
                if candidate.exists() and candidate.is_file():
                    return candidate
                candidate2 = cur / "main.py"
                if candidate2.exists() and candidate2.is_file():
                    return candidate2
                if cur.parent == cur:
                    break
                cur = cur.parent
        except Exception:
            return None
        return None

    @staticmethod
    def _find_exe_fallback() -> Path | None:
        """尋找可能的可執行檔（可攜版 exe）作為重啟備援，回傳第一個存在的 Path 或 None。"""
        try:
            candidates = [
                Path.cwd() / "MinecraftServerManager.exe",
                Path(__file__).parent.parent.parent / "MinecraftServerManager.exe",
            ]
            try:
                if sys.executable:
                    candidates.append(Path(sys.executable))
            except Exception as e:
                logger.debug("加入 sys.executable 候選項失敗: %s", e)
            try:
                if sys.argv and sys.argv[0]:
                    candidates.append(Path(sys.argv[0]))
            except Exception as e:
                logger.debug("加入 sys.argv[0] 候選項失敗: %s", e)
            cur = Path(__file__).resolve(strict=False)
            for _ in range(4):
                cur = cur.parent
                candidates.append(cur / "MinecraftServerManager.exe")
            for c in candidates:
                if c is None:
                    continue
                try:
                    if c.exists() and c.is_file() and (c.suffix.lower() == ".exe"):
                        return c
                except Exception as e:
                    logger.debug(f"檢查候選可執行檔時發生例外: {e}")
                    continue
        except Exception:
            return None
        return None

    @staticmethod
    def can_restart() -> bool:
        """檢查當前環境是否支援應用程式重啟功能"""
        try:
            executable_path, is_frozen, script_path = AppRestart._get_executable_info()
            if is_frozen:
                exe_candidate = AppRestart._extract_exe_candidate(executable_path)
                exe_exists = False
                exe_is_file = False
                exe_resolved = None
                if exe_candidate:
                    p = Path(exe_candidate)
                    try:
                        exe_resolved = p.resolve(strict=False)
                    except Exception:
                        exe_resolved = p
                    exe_exists = exe_resolved.exists()
                    exe_is_file = exe_resolved.is_file()
                supported = bool(exe_candidate and exe_exists and exe_is_file)
                if supported:
                    logger.info(f"可以重啟：在 {exe_candidate} 找到打包執行檔")
                else:
                    err_parts = [
                        "模式=打包",
                        f"執行檔候選={exe_candidate!r}",
                        f"執行檔解析後={str(exe_resolved)!r}",
                        f"存在={exe_exists}",
                        f"是檔案={exe_is_file}",
                    ]
                    logger.error("不可以重啟：打包執行檔不存在或路徑無效" + "; ".join(err_parts))
                return supported
            script_candidate = script_path
            script_exists = False
            script_is_file = False
            script_resolved = None
            if script_candidate is not None:
                try:
                    try:
                        script_resolved = script_candidate.resolve(strict=False)
                    except Exception:
                        script_resolved = script_candidate
                    script_exists = script_resolved.exists()
                    script_is_file = script_resolved.is_file()
                except Exception:
                    script_exists = False
                    script_is_file = False
            supported = bool(script_candidate is not None and script_exists and script_is_file)
            if supported:
                logger.info(f"可以重啟：腳本模式，main.py 在 {script_candidate}")
            else:
                err_parts = [
                    "模式=腳本",
                    f"腳本候選={script_candidate!r}",
                    f"解析後腳本={str(script_resolved)!r}",
                    f"存在={script_exists}",
                    f"是檔案={script_is_file}",
                ]
                logger.error("不可以重啟：找不到 main.py，無法以腳本模式重啟" + "; ".join(err_parts))
            return supported
        except Exception:
            logger.exception("檢查是否可重啟時發生例外")
            return False

    @staticmethod
    def get_restart_diagnostics() -> tuple[bool, str]:
        """回傳是否可重啟與診斷文字說明"""
        try:
            executable_path, is_frozen, script_path = AppRestart._get_executable_info()
            if is_frozen:
                exe_candidate = AppRestart._extract_exe_candidate(executable_path)
                exe_resolved = None
                exists = False
                is_file = False
                if exe_candidate:
                    p = Path(exe_candidate)
                    try:
                        exe_resolved = p.resolve(strict=False)
                    except Exception:
                        exe_resolved = p
                    exists = exe_resolved.exists()
                    is_file = exe_resolved.is_file()
                    if not exists:
                        try:
                            expanded = PathUtils.get_long_path(exe_resolved)
                            if expanded != exe_resolved:
                                exists = expanded.exists()
                                is_file = expanded.is_file()
                                exe_resolved = expanded
                        except Exception as e:
                            logger.debug("expanding exe path failed: %s", e)
                else:
                    exists = False
                    is_file = False
                supported = bool(exe_candidate and exists and is_file)
                details = f"模式=打包; 執行檔候選={exe_candidate!r}; 執行檔解析後={str(exe_resolved)!r}; 是否存在={exists}; 是否是檔案={is_file}"
                return (supported, details)
            script_resolved = None
            exists = False
            is_file = False
            if script_path is not None:
                try:
                    try:
                        script_resolved = script_path.resolve(strict=False)
                    except Exception:
                        script_resolved = script_path
                    exists = script_resolved.exists()
                    is_file = script_resolved.is_file()
                    if not exists:
                        try:
                            expanded = PathUtils.get_long_path(script_resolved)
                            if expanded != script_resolved:
                                exists = expanded.exists()
                                is_file = expanded.is_file()
                                script_resolved = expanded
                        except Exception as e:
                            logger.debug("展開腳本路徑失敗: %s", e)
                    if not exists:
                        found = AppRestart._find_main_in_parents(Path.cwd(), max_levels=6)
                        if not found and script_resolved is not None:
                            found = AppRestart._find_main_in_parents(script_resolved.parent, max_levels=6)
                        if found:
                            script_resolved = found
                            exists = True
                            is_file = True
                            details = f"模式=腳本; 腳本路徑={script_path!r}; 解析後路徑={str(script_resolved)!r}; 是否存在={exists}; 是否是檔案={is_file}; 搜尋到=True"
                            return (True, details)
                except Exception:
                    exists = False
                    is_file = False
            else:
                exists = False
                is_file = False
            supported = bool(script_path is not None and exists and is_file)
            if not supported:
                exe_fallback = AppRestart._find_exe_fallback()
                if exe_fallback:
                    details = f"模式=打包(備援); 執行檔={str(exe_fallback)!r}; 是否存在=True; 是否是檔案=True; 備註='找到可攜版 exe 備援'"
                    return (True, details)
            details = f"模式=腳本; 腳本路徑={script_path!r}; 解析後腳本={str(script_resolved)!r}; 是否存在={exists}; 是否是檔案={is_file}"
            return (supported, details)
        except Exception as e:
            logger.exception("取得重啟診斷資訊時發生例外")
            return (False, f"例外: {e}")

    @staticmethod
    def restart_application(delay: float = 1.0) -> bool:
        """重啟應用程式，支援延遲啟動和狀態檢測"""
        try:
            executable_cmd, is_frozen, script_path = AppRestart._get_executable_info()
            restart_success = threading.Event()
            restart_error = threading.Event()
            script_parent = script_path.parent if script_path is not None else None
            _ = str(script_path) if script_path is not None else None

            def delayed_restart():
                """延遲重啟函式（會在背景執行緒啟動新程式）。"""
                try:
                    time.sleep(delay)
                    if is_frozen:
                        exe_path = executable_cmd[0]
                        exe_cwd = str(Path(exe_path).parent) if exe_path else None
                        logger.debug(f"啟動執行檔: {exe_path}, cwd={exe_cwd}")
                        process = SubprocessUtils.popen_detached([exe_path], cwd=exe_cwd)
                    else:
                        target_cwd = None
                        interpreter_str: str | None = None
                        if sys.executable:
                            interpreter_str = AppRestart._prefer_windowless_python(str(sys.executable))
                        else:
                            for cand in ("python3", "python", "py"):
                                which_found = PathUtils.find_executable(cand)
                                if which_found:
                                    interpreter_str = AppRestart._prefer_windowless_python(which_found)
                                    break
                        script_ok = isinstance(script_path, Path) and script_path.exists() and script_path.is_file()
                        if script_ok:
                            if interpreter_str:
                                try:
                                    interp_name = Path(interpreter_str).name.lower()
                                except Exception:
                                    interp_name = str(interpreter_str).lower()
                                if "python" in interp_name or interp_name.startswith("py"):
                                    if isinstance(script_path, Path):
                                        use_cmd = [interpreter_str, str(script_path)]
                                        target_cwd = str(script_path.parent)
                                        logger.debug(f"以 Python 執行檔案重啟: {use_cmd}, 指令={target_cwd}")
                                    else:
                                        logger.debug("script_path 不是 Path，將回退到其他重啟方法")
                                else:
                                    exe_fb = AppRestart._find_exe_fallback()
                                    if exe_fb:
                                        use_cmd = [str(exe_fb)]
                                        target_cwd = str(exe_fb.parent)
                                        logger.debug(
                                            f"偵測到非-Python exe，改用 exe fallback 重啟: {use_cmd}, 指令={target_cwd}"
                                        )
                        else:
                            found = AppRestart._find_main_in_parents(Path.cwd(), max_levels=6)
                            if not found and script_parent is not None:
                                found = AppRestart._find_main_in_parents(script_parent, max_levels=6)
                            if found is not None:
                                runner = interpreter_str or AppRestart._prefer_windowless_python(
                                    str(sys.executable) if sys.executable else "python"
                                )
                                runner = runner or "python"
                                use_cmd = [runner, str(found)]
                                target_cwd = str(found.parent)
                                logger.debug(f"在父層找到 main.py，使用檔案重啟: {use_cmd}, 指令={target_cwd}")
                            else:
                                exe_fallback = AppRestart._find_exe_fallback()
                                if exe_fallback:
                                    use_cmd = [str(exe_fallback)]
                                    target_cwd = str(exe_fallback.parent)
                                    logger.debug(f"使用 exe fallback 重啟: {use_cmd}, 指令={target_cwd}")
                                else:
                                    runner = interpreter_str or AppRestart._prefer_windowless_python(
                                        str(sys.executable) if sys.executable else "python"
                                    )
                                    runner = runner or "python"
                                    use_cmd = [runner, "-m", "src.main"]
                                    target_cwd = str(Path.cwd())
                                    logger.debug(f"以模組方式重啟: {use_cmd}, 指令={target_cwd}")
                        process = SubprocessUtils.popen_detached(use_cmd, cwd=target_cwd)
                    time.sleep(0.5)
                    if process.poll() is None:
                        restart_success.set()
                    else:
                        restart_error.set()
                except Exception as e:
                    logger.exception(f"重啟失敗: {e}")
                    restart_error.set()

            UIUtils.run_async(delayed_restart)
            max_wait_time = delay + 2.0
            if restart_success.wait(timeout=max_wait_time):
                return True
            return not restart_error.is_set()
        except Exception as e:
            logger.exception(f"準備重啟時發生錯誤: {e}")
            return False

    @staticmethod
    def schedule_restart_and_exit(parent_window=None, delay: float = 1.0) -> None:
        """安排應用程式重啟並安全關閉當前實例，包含 GUI 視窗處理"""
        try:
            restart_initiated = AppRestart.restart_application(delay)
            if restart_initiated:
                logger.info("重啟程式已啟動，準備關閉當前應用程式")
                time.sleep(0.2)
                if parent_window:
                    try:

                        def delayed_close():
                            try:
                                parent_window.quit()
                                parent_window.destroy()
                            except Exception as e:
                                logger.exception(f"關閉視窗時發生錯誤: {e}")
                            shutdown_logging()
                            time.sleep(0.5)
                            sys.exit(0)

                        UIUtils.schedule_debounce(
                            parent_window, "_restart_close_job", 100, delayed_close, owner=parent_window
                        )
                    except Exception as e:
                        logger.exception(f"安排視窗關閉時發生錯誤: {e}")
                        try:
                            parent_window.quit()
                            parent_window.destroy()
                        except Exception as e2:
                            logger.exception(f"直接關閉視窗失敗: {e2}")
                        shutdown_logging()
                        time.sleep(0.5)
                        sys.exit(0)
                else:
                    shutdown_logging()
                    time.sleep(0.5)
                    sys.exit(0)
            else:
                logger.error("重啟失敗，程式將繼續運行")
                try:
                    _supported, details = AppRestart.get_restart_diagnostics()
                except Exception:
                    _supported, details = (False, "無法取得重啟診斷。")
                UIUtils.show_manual_restart_dialog(parent_window or None, details)
        except Exception as e:
            logger.exception(f"重啟程式失敗: {e}")
