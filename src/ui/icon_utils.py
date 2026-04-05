"""視窗圖示工具。"""

from __future__ import annotations

import contextlib
import tkinter as tk

from ..utils import PathUtils, get_logger

logger = get_logger().bind(component="IconUtils")


class IconUtils:
    """集中處理視窗圖示的延遲綁定與重試。"""

    @staticmethod
    def set_window_icon(window, delay_ms=200) -> None:
        """設定視窗 icon，並在不同生命週期時機補設，避免被 CTk/系統主題覆寫。

        Args:
            window: 要設定圖示的視窗。
            delay_ms: 延遲重試的毫秒數。
        """
        icon_path = PathUtils.get_assets_path() / "icon.ico"
        if not icon_path.exists():
            logger.warning(f"圖示檔案不存在 - {icon_path}")
            return
        icon_str = str(icon_path)

        def _apply_icon() -> None:
            try:
                if not window.winfo_exists():
                    return
                try:
                    window.iconbitmap(default=icon_str)
                except tk.TclError as e:
                    logger.debug(f"無法設定預設視窗圖示，將略過此步驟 - {e}")
                window.iconbitmap(icon_str)
                window._msm_icon_set = True
                with contextlib.suppress(Exception):
                    window.after_idle(window.update_idletasks)
            except (tk.TclError, AttributeError, RuntimeError) as e:
                logger.warning(f"設定視窗圖示暫時性錯誤: {e}")
            except Exception:
                logger.exception("設定視窗圖示失敗")

        def _on_window_state_change(_event=None) -> None:
            with contextlib.suppress(Exception):
                window.after_idle(_apply_icon)

        try:
            if hasattr(window, "after") and hasattr(window, "winfo_exists"):
                with contextlib.suppress(Exception):
                    window.after(0, _apply_icon)
                with contextlib.suppress(Exception):
                    window.after(delay_ms, _apply_icon)
                with contextlib.suppress(Exception):
                    window.after(delay_ms + 120, _apply_icon)
                with contextlib.suppress(Exception):
                    window.after(delay_ms + 500, _apply_icon)
                if not getattr(window, "_msm_icon_event_bound", False):
                    with contextlib.suppress(Exception):
                        window.bind("<Map>", _on_window_state_change, add="+")
                    with contextlib.suppress(Exception):
                        window.bind("<FocusIn>", _on_window_state_change, add="+")
                    window._msm_icon_event_bound = True
            else:
                _apply_icon()
        except Exception as e:
            logger.warning(f"無法延遲執行圖示綁定: {e}")
            _apply_icon()


__all__ = ["IconUtils"]
