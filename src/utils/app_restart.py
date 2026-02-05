#!/usr/bin/env python3
"""
應用程式重啟工具模組
提供安全的應用程式重啟功能，支援打包執行檔與 Python 腳本模式
"""

import contextlib
import sys
import threading
import time
from pathlib import Path

from . import PathUtils, SubprocessUtils, UIUtils, get_logger

logger = get_logger().bind(component="AppRestart")


class AppRestart:
    """應用程式重啟管理類別"""

    @staticmethod
    def _get_executable_info() -> tuple[list[str], bool, Path | None]:
        """取得當前應用程式的執行檔資訊，區分打包檔案與 Python 腳本模式"""
        # 優先透過 sys.executable 判斷是否為打包執行檔
        exe_path: Path | None = None
        try:
            exe_path = Path(sys.executable) if sys.executable else None
        except Exception:
            exe_path = None

        # 如果 sys.executable 是 .exe 且明顯不是 python.exe，則視為打包執行檔
        is_frozen = False
        try:
            if exe_path is not None and exe_path.suffix.lower() == ".exe" and "python" not in exe_path.name.lower():
                is_frozen = True
        except Exception:
            is_frozen = False

        # 嘗試透過常見打包器的指標補強判斷
        try:
            # PyInstaller 會設置 _MEIPASS，若存在則視為已打包
            if not is_frozen and hasattr(sys, "_MEIPASS"):
                is_frozen = True
                if exe_path is None and getattr(sys, "executable", None):
                    with contextlib.suppress(Exception):
                        exe_path = Path(sys.executable)

            # 若 argv[0] 明顯為 .exe，則也視為打包，並優先採用它作為執行檔路徑
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

            exe_str = str(exe_path) if exe_path is not None else (str(sys.executable) if sys.executable else "")
            return [exe_str], True, None

        # 非打包模式，嘗試透過 sys.argv[0] 判斷腳本路徑
        try:
            argv0 = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
            if (
                argv0
                and argv0.exists()
                and argv0.suffix.lower() == ".exe"
                and "minecraftservermanager" in argv0.name.lower()
            ):
                return [str(argv0)], True, None
        except Exception as e:
            logger.debug(f"argv0 偵測失敗: {e}")

        # 嘗試尋找 main.py 腳本位置
        script_path: Path | None = None
        try:
            candidate = Path(__file__).parent.parent / "main.py"
            if candidate.exists() and candidate.is_file():
                script_path = candidate
            else:
                # 嘗試向上尋找 main.py
                found = AppRestart._find_main_in_parents(Path(__file__).parent.parent, max_levels=6)
                if found:
                    script_path = found
                else:
                    # 最後嘗試從當前工作目錄向上尋找 main.py
                    found2 = AppRestart._find_main_in_parents(Path.cwd(), max_levels=6)
                    if found2:
                        script_path = found2
        except Exception:
            script_path = None

        # 回傳腳本模式資訊
        exe_val = str(sys.executable) if sys.executable else ""
        script_val = str(script_path) if script_path is not None else ""
        return [exe_val, script_val], False, script_path

    @staticmethod
    def _find_main_in_parents(start_dir: Path | str, max_levels: int = 5) -> Path | None:
        """從起始目錄向上搜尋可能包含 main.py 的候選位置。"""
        try:
            p = Path(start_dir).resolve(strict=False)
            # 檢查自身及向上 max_levels 層
            cur = p
            for _ in range(max_levels + 1):
                # 檢查 src/main.py
                candidate = cur / "src" / "main.py"
                if candidate.exists() and candidate.is_file():
                    return candidate
                # 檢查 main.py
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

            # 嘗試加入 sys.executable 與 sys.argv[0] 作為候選
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

            # 嘗試從目前檔案位置向上尋找
            cur = Path(__file__).resolve(strict=False)
            for _ in range(4):
                cur = cur.parent
                candidates.append(cur / "MinecraftServerManager.exe")

            for c in candidates:
                if c is None:
                    continue
                try:
                    if c.exists() and c.is_file() and c.suffix.lower() == ".exe":
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
                # executable_path 是 list，取第一個（執行檔路徑）
                exe_candidate = None
                try:
                    if isinstance(executable_path, list) and len(executable_path) > 0:
                        exe_candidate = executable_path[0]
                except Exception:
                    exe_candidate = None

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

            # 直接檢查腳本路徑是否存在
            script_candidate = script_path
            script_exists = False
            script_is_file = False
            script_resolved = None
            if script_candidate is not None:
                try:
                    # 使用 resolve(strict=False) 取得可比較的路徑（避免在不存在時拋出例外）
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
                exe_candidate = None
                try:
                    if isinstance(executable_path, list) and len(executable_path) > 0:
                        exe_candidate = executable_path[0]
                except Exception:
                    exe_candidate = None

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
                return supported, details

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
                    # 如果仍然找不到，嘗試從目前工作目錄或 script_path 的父層向上搜尋可能的 main.py
                    if not exists:
                        found = AppRestart._find_main_in_parents(Path.cwd(), max_levels=6)
                        if not found and script_resolved is not None:
                            # 從 script_path 預期位置向上搜尋
                            found = AppRestart._find_main_in_parents(script_resolved.parent, max_levels=6)
                        if found:
                            script_resolved = found
                            exists = True
                            is_file = True
                            # 記錄額外的搜尋資訊到診斷字串
                            details = f"模式=腳本; 腳本路徑={script_path!r}; 解析後路徑={str(script_resolved)!r}; 是否存在={exists}; 是否是檔案={is_file}; 搜尋到=True"
                            return True, details
                except Exception:
                    exists = False
                    is_file = False
            else:
                exists = False
                is_file = False

            supported = bool(script_path is not None and exists and is_file)
            # 若 script 無法使用，嘗試偵測同一目錄或當前工作目錄是否存在可執行檔 (可攜版 exe)
            if not supported:
                exe_fallback = AppRestart._find_exe_fallback()
                if exe_fallback:
                    details = f"模式=打包(備援); 執行檔={str(exe_fallback)!r}; 是否存在=True; 是否是檔案=True; 備註='找到可攜版 exe 備援'"
                    return True, details

            details = f"模式=腳本; 腳本路徑={script_path!r}; 解析後腳本={str(script_resolved)!r}; 是否存在={exists}; 是否是檔案={is_file}"
            return supported, details

        except Exception as e:
            logger.exception("取得重啟診斷資訊時發生例外")
            return False, f"例外: {e}"

    @staticmethod
    def restart_application(delay: float = 1.0) -> bool:
        """重啟應用程式，支援延遲啟動和狀態檢測"""
        try:
            executable_cmd, is_frozen, script_path = AppRestart._get_executable_info()

            # 使用事件來同步重啟狀態
            restart_success = threading.Event()
            restart_error = threading.Event()

            # 預先計算安全的區域變數，避免巢狀函式直接存取 Optional 的屬性
            script_parent = script_path.parent if script_path is not None else None
            _ = str(script_path) if script_path is not None else None

            def delayed_restart():
                """延遲重啟函式（會在背景執行緒啟動新程式）。"""
                try:
                    time.sleep(delay)
                    # Windows 平台隱藏命令提示字元視窗（若不可用則回退為 0）
                    creation_flags = SubprocessUtils.CREATE_NO_WINDOW

                    if is_frozen:
                        # 對於打包檔案，直接執行可執行檔，並把工作目錄設為執行檔所在資料夾
                        exe_path = executable_cmd[0]
                        exe_cwd = str(Path(exe_path).parent) if exe_path else None
                        logger.debug(f"啟動執行檔: {exe_path}, cwd={exe_cwd}")
                        process = SubprocessUtils.popen_checked(
                            [exe_path],
                            cwd=exe_cwd,
                            stdin=SubprocessUtils.DEVNULL,
                            creationflags=creation_flags,
                        )
                    else:
                        # 非打包（腳本）模式：建立安全的命令列表（所有元素皆為字串）
                        target_cwd = None

                        # 決定要使用的 Python 解譯器字串，優先使用 sys.executable，否則嘗試 PATH 中的常見名稱
                        interpreter_str: str | None = None
                        if sys.executable:
                            interpreter_str = str(sys.executable)
                        else:
                            for cand in ("python3", "python", "py"):
                                which_found = PathUtils.find_executable(cand)
                                if which_found:
                                    interpreter_str = which_found
                                    break

                            # 若有有效的 script_path，優先直接以解譯器執行該檔案
                        script_ok = isinstance(script_path, Path) and script_path.exists() and script_path.is_file()
                        if script_ok:
                            # 不要將非 Python 的 exe 視為解譯器（例如已打包的 exe）
                            if interpreter_str:
                                try:
                                    interp_name = Path(interpreter_str).name.lower()
                                except Exception:
                                    interp_name = str(interpreter_str).lower()

                                if "python" in interp_name or interp_name.startswith("py"):
                                    # help type checker: ensure script_path is Path
                                    if isinstance(script_path, Path):
                                        use_cmd = [interpreter_str, str(script_path)]
                                        target_cwd = str(script_path.parent)
                                        logger.debug(f"以 Python 執行檔案重啟: {use_cmd}, 指令={target_cwd}")
                                    else:
                                        logger.debug("script_path 不是 Path，將回退到其他重啟方法")
                                else:
                                    # interpreter_str 指向非 Python 的執行檔（可能是打包的 exe）
                                    # 此時優先改用 exe 備援而非嘗試以該執行檔執行腳本
                                    exe_fb = AppRestart._find_exe_fallback()
                                    if exe_fb:
                                        use_cmd = [str(exe_fb)]
                                        target_cwd = str(exe_fb.parent)
                                        logger.debug(
                                            f"偵測到非-Python exe，改用 exe fallback 重啟: {use_cmd}, 指令={target_cwd}"
                                        )
                        else:
                            # 嘗試在父層目錄中尋找 main.py
                            found = AppRestart._find_main_in_parents(Path.cwd(), max_levels=6)
                            if not found and script_parent is not None:
                                found = AppRestart._find_main_in_parents(script_parent, max_levels=6)

                            if found is not None:
                                # 若存在 interpreter_str 則使用，否則回退到 sys.executable 或 'python'
                                runner = interpreter_str or (str(sys.executable) if sys.executable else "python")
                                use_cmd = [runner, str(found)]
                                target_cwd = str(found.parent)
                                logger.debug(f"在父層找到 main.py，使用檔案重啟: {use_cmd}, 指令={target_cwd}")
                            else:
                                # Try executable fallback (portable exe)
                                exe_fallback = AppRestart._find_exe_fallback()
                                if exe_fallback:
                                    use_cmd = [str(exe_fallback)]
                                    target_cwd = str(exe_fallback.parent)
                                    logger.debug(f"使用 exe fallback 重啟: {use_cmd}, 指令={target_cwd}")
                                else:
                                    # 最後備援：透過解譯器以模組方式啟動
                                    runner = interpreter_str or (str(sys.executable) if sys.executable else "python")
                                    use_cmd = [runner, "-m", "src.main"]
                                    target_cwd = str(Path.cwd())
                                    logger.debug(f"以模組方式重啟: {use_cmd}, 指令={target_cwd}")

                        process = SubprocessUtils.popen_checked(
                            use_cmd, cwd=target_cwd, stdin=SubprocessUtils.DEVNULL, creationflags=creation_flags
                        )

                    # 等待短暫時間以確認新程式已啟動
                    time.sleep(0.5)

                    # 檢查新程式是否仍在運行中
                    if process.poll() is None:
                        restart_success.set()
                    else:
                        restart_error.set()

                except Exception as e:
                    logger.exception(f"重啟失敗: {e}")
                    restart_error.set()

            # 在背景執行緒中執行延遲重啟（設定為 daemon，程式退出時不會被阻提）
            UIUtils.run_async(delayed_restart)

            # 等待重啟結果，最多等待 delay + 2 秒
            max_wait_time = delay + 2.0
            if restart_success.wait(timeout=max_wait_time):
                return True
            # 如果發生錯誤則返回 False，否則（超時）返回 True
            return not restart_error.is_set()

        except Exception as e:
            logger.exception(f"準備重啟時發生錯誤: {e}")
            return False

    @staticmethod
    def schedule_restart_and_exit(parent_window=None, delay: float = 1.0) -> None:
        """安排應用程式重啟並安全關閉當前實例，包含 GUI 視窗處理"""
        try:
            # 首先嘗試啟動重啟程式
            restart_initiated = AppRestart.restart_application(delay)
            if restart_initiated:
                logger.info("重啟程式已啟動，準備關閉當前應用程式")

                # 給重啟程式一些時間來準備
                time.sleep(0.2)

                # 關閉當前應用程式
                if parent_window:
                    try:
                        # 使用 after 方法延遲關閉，確保 UI 操作完成
                        def delayed_close():
                            try:
                                parent_window.quit()  # 停止主事件迴圈
                                parent_window.destroy()  # 銷毀視窗
                            except Exception as e:
                                logger.exception(f"關閉視窗時發生錯誤: {e}")

                            # 延遲退出以確保新程式有時間啟動
                            time.sleep(0.5)
                            sys.exit(0)

                        # 在主線程中安排延遲關閉
                        parent_window.after(100, delayed_close)

                    except Exception as e:
                        logger.exception(f"安排視窗關閉時發生錯誤: {e}")
                        # 如果無法使用 after 方法，直接關閉
                        try:
                            parent_window.quit()
                            parent_window.destroy()
                        except Exception as e2:
                            logger.exception(f"直接關閉視窗失敗: {e2}")
                        time.sleep(0.5)
                        sys.exit(0)
                else:
                    # 沒有父視窗，直接延遲退出
                    time.sleep(0.5)
                    sys.exit(0)
            else:
                logger.error("重啟失敗，程式將繼續運行")
                # 顯示完整診斷與手動重啟指示給使用者（在 UI 上）
                try:
                    _supported, details = AppRestart.get_restart_diagnostics()
                except Exception:
                    _supported, details = False, "無法取得重啟診斷。"

                    UIUtils.show_manual_restart_dialog(parent_window or None, details)

        except Exception as e:
            logger.exception(f"重啟程式失敗: {e}")
