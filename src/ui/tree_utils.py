"""Treeview 與 Listbox 相關工具。"""

from __future__ import annotations

import tkinter
import tkinter.font as tkfont
import tkinter.ttk as ttk
from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from ..utils import Colors, FontSize, get_logger
from .font_manager import FontManager

logger = get_logger().bind(component="TreeUtils")


class TreeUtils:
    """集中處理 Treeview / Listbox 樣式、欄位與批次更新工具。"""

    @staticmethod
    def configure_treeview_list_style(
        style_name: str, *, body_font=None, heading_font=None, rowheight: int | None = None
    ) -> str:
        """建立統一的 Treeview 清單樣式並回傳樣式名稱。

        Args:
            style_name: 樣式前綴名稱。
            body_font: 內容字型。
            heading_font: 標題字型。
            rowheight: 列高。

        Returns:
            產生的 Treeview 樣式名稱。
        """
        style = ttk.Style()
        treeview_style = f"{style_name}.Treeview"
        heading_style = f"{treeview_style}.Heading"
        scaled_rowheight = int(rowheight or FontManager.get_dpi_scaled_size(25))
        body_font = body_font or FontManager.get_font(size=FontSize.INPUT)
        heading_font = heading_font or FontManager.get_font(size=FontSize.LARGE, weight="bold")
        style.configure(
            treeview_style,
            font=body_font,
            rowheight=scaled_rowheight,
            background=Colors.BG_LISTBOX_LIGHT,
            fieldbackground=Colors.BG_LISTBOX_LIGHT,
            foreground=Colors.TEXT_PRIMARY[0],
            bordercolor=Colors.BORDER_LIGHT[0],
            lightcolor=Colors.BORDER_LIGHT[0],
            darkcolor=Colors.BORDER_LIGHT[0],
        )
        style.configure(
            heading_style,
            font=heading_font,
            background=Colors.BG_SECONDARY[0],
            foreground=Colors.TEXT_HEADING[0],
            relief="flat",
        )
        style.map(
            treeview_style, background=[("selected", Colors.SELECT_BG)], foreground=[("selected", Colors.TEXT_ON_DARK)]
        )
        style.map(
            heading_style,
            background=[("active", Colors.BG_SECONDARY[0])],
            foreground=[("active", Colors.TEXT_HEADING[0])],
        )
        return treeview_style

    @staticmethod
    def _iter_treeview_items(treeview, parent: str = ""):
        for item_id in treeview.get_children(parent):
            yield item_id
            yield from TreeUtils._iter_treeview_items(treeview, item_id)

    @staticmethod
    def _get_treeview_item_depth(treeview, item_id: str) -> int:
        depth = 0
        current_item = str(item_id or "").strip()
        while current_item:
            parent_item = str(treeview.parent(current_item) or "").strip()
            if not parent_item:
                break
            depth += 1
            current_item = parent_item
        return depth

    @staticmethod
    def _get_treeview_columns(treeview, *, include_tree_column: bool = False) -> tuple[str, ...]:
        columns = tuple(str(column).strip() for column in tuple(treeview.cget("columns") or ()) if str(column).strip())
        displaycolumns = treeview.cget("displaycolumns")
        show = {part.strip() for part in str(treeview.cget("show") or "").split() if part.strip()}
        if isinstance(displaycolumns, (tuple, list)):
            normalized_displaycolumns = tuple(str(column).strip() for column in displaycolumns if str(column).strip())
        else:
            normalized_value = str(displaycolumns or "").strip()
            if normalized_value.startswith("(") and normalized_value.endswith(")"):
                normalized_displaycolumns = tuple(
                    part.strip().strip("'\"") for part in normalized_value[1:-1].split() if part.strip().strip("'\"")
                )
            elif normalized_value:
                normalized_displaycolumns = (normalized_value,)
            else:
                normalized_displaycolumns = ()
        visible_columns: list[str] = []
        if include_tree_column and "tree" in show:
            visible_columns.append("#0")
        if not normalized_displaycolumns or any(column == "#all" for column in normalized_displaycolumns):
            visible_columns.extend(str(column) for column in columns)
        else:
            visible_columns.extend(column for column in normalized_displaycolumns if column in columns)
        return tuple(visible_columns)

    @staticmethod
    def _get_treeview_column_from_x(treeview, x: int, *, include_tree_column: bool = False) -> str | None:
        column_ref = str(treeview.identify_column(x) or "").strip()
        if not column_ref:
            return None
        if column_ref == "#0":
            return "#0" if include_tree_column else None
        try:
            column_index = int(column_ref.removeprefix("#")) - 1
        except ValueError:
            return None
        visible_columns = TreeUtils._get_treeview_columns(treeview, include_tree_column=include_tree_column)
        if column_index < 0 or column_index >= len(visible_columns):
            return None
        return visible_columns[column_index]

    @staticmethod
    def _get_treeview_separator_column_from_x(treeview, x: int, *, include_tree_column: bool = False) -> str | None:
        if not hasattr(treeview, "identify_column"):
            candidate_columns = TreeUtils._get_treeview_columns(treeview, include_tree_column=include_tree_column)
            if not candidate_columns:
                return None
            columns: list[str] = []
            widths: list[int] = []
            for column_id in candidate_columns:
                try:
                    width = int(treeview.column(column_id, "width"))
                except tkinter.TclError, TypeError, ValueError:
                    continue
                columns.append(column_id)
                widths.append(width)
            if not columns:
                return None
            total_width = sum(widths)
            xview_start = 0.0
            try:
                xview = treeview.xview()
                if xview and len(xview) >= 1:
                    xview_start = float(xview[0])
            except tkinter.TclError, TypeError, ValueError:
                xview_start = 0.0
            logical_x = int(x + xview_start * total_width)
            threshold = FontManager.get_dpi_scaled_size(6)
            boundary = 0
            for index, width in enumerate(widths):
                boundary += width
                if abs(logical_x - boundary) <= threshold:
                    return columns[index]
            return None
        threshold = FontManager.get_dpi_scaled_size(4)
        left_column = TreeUtils._get_treeview_column_from_x(
            treeview, max(0, int(x) - threshold), include_tree_column=include_tree_column
        )
        right_column = TreeUtils._get_treeview_column_from_x(
            treeview, int(x) + threshold, include_tree_column=include_tree_column
        )
        if left_column:
            return left_column
        return right_column

    @staticmethod
    def auto_fit_treeview_column(
        treeview, column_id: str, *, heading_font=None, body_font=None, stretch_columns: set[str] | None = None
    ) -> None:
        """依標題與內容寬度自動調整 Treeview 欄位大小。

        Args:
            treeview: 目標 Treeview。
            column_id: 要調整的欄位 ID。
            heading_font: 標題字型。
            body_font: 內容字型。
            stretch_columns: 允許延展的欄位集合。
        """

        if not treeview or not column_id:
            return
        normalized_column_id = str(column_id).strip()
        if not normalized_column_id:
            return
        heading_font_obj = tkfont.Font(font=heading_font or FontManager.get_font(size=FontSize.LARGE, weight="bold"))
        body_font_obj = tkfont.Font(font=body_font or FontManager.get_font(size=FontSize.INPUT))
        base_padding = FontManager.get_dpi_scaled_size(10)
        tree_extra_padding = FontManager.get_dpi_scaled_size(4)
        safety_min_width = FontManager.get_dpi_scaled_size(12)
        configured_stretch_columns = set(stretch_columns or set())
        heading_text = str(treeview.heading(normalized_column_id, "text") or normalized_column_id)
        max_width = heading_font_obj.measure(heading_text)
        all_columns = tuple(str(column) for column in tuple(treeview.cget("columns") or ()))
        value_column_index = -1 if normalized_column_id == "#0" else all_columns.index(normalized_column_id)
        for item_id in TreeUtils._iter_treeview_items(treeview):
            if normalized_column_id == "#0":
                cell_value = treeview.item(item_id, "text") or ""
                depth_padding = TreeUtils._get_treeview_item_depth(treeview, item_id) * FontManager.get_dpi_scaled_size(
                    16
                ) + FontManager.get_dpi_scaled_size(16)
                measured_width = body_font_obj.measure(str(cell_value or "")) + depth_padding
            else:
                values = treeview.item(item_id, "values") or ()
                if value_column_index >= len(values):
                    continue
                cell_value = values[value_column_index]
                measured_width = body_font_obj.measure(str(cell_value or ""))
            max_width = max(max_width, measured_width)
        computed_width = max(
            safety_min_width,
            min(
                int(max_width + base_padding + (tree_extra_padding if normalized_column_id == "#0" else 0)),
                2000,
            ),
        )
        current_stretch = treeview.column(normalized_column_id, "stretch")
        is_stretch = (
            bool(normalized_column_id in configured_stretch_columns) if configured_stretch_columns else current_stretch
        )
        current_minwidth = treeview.column(normalized_column_id, "minwidth")

        treeview.column(
            normalized_column_id,
            width=computed_width,
            minwidth=computed_width if is_stretch else current_minwidth,
            stretch=is_stretch,
        )

    @staticmethod
    def bind_treeview_header_auto_fit(
        treeview,
        *,
        on_row_double_click: Callable[[Any], Any] | None = None,
        include_tree_column: bool = False,
        heading_font=None,
        body_font=None,
        stretch_columns: set[str] | None = None,
    ) -> None:
        """綁定 Treeview 標題雙擊事件以自動調整欄位寬度。

        Args:
            treeview: 目標 Treeview。
            on_row_double_click: 目前點擊列時要執行的 callback。
            include_tree_column: 是否包含樹狀欄位 #0。
            heading_font: 標題字型。
            body_font: 內容字型。
            stretch_columns: 允許延展的欄位集合。
        """

        if not treeview:
            return

        def _handle_double_click(event):
            region = treeview.identify_region(event.x, event.y)
            if region in ("separator", "heading"):
                if region == "separator":
                    column_id = TreeUtils._get_treeview_separator_column_from_x(
                        treeview, event.x, include_tree_column=include_tree_column
                    )
                    if not column_id:
                        column_id = TreeUtils._get_treeview_column_from_x(
                            treeview, event.x, include_tree_column=include_tree_column
                        )
                else:
                    column_id = TreeUtils._get_treeview_column_from_x(
                        treeview, event.x, include_tree_column=include_tree_column
                    )
                if column_id:
                    TreeUtils.auto_fit_treeview_column(
                        treeview,
                        column_id,
                        heading_font=heading_font,
                        body_font=body_font,
                        stretch_columns=stretch_columns,
                    )
                    return "break"
                return None
            if on_row_double_click is not None:
                return on_row_double_click(event)
            return None

        treeview.bind("<Double-1>", _handle_double_click)

    @staticmethod
    def refresh_treeview_alternating_rows(treeview) -> None:
        """重新套用 Treeview 交錯列背景，保留既有非 odd/even tag。

        Args:
            treeview: 目標 Treeview。
        """
        if not treeview:
            return
        is_dark = ctk.get_appearance_mode() == "Dark"
        odd_bg = Colors.BG_ROW_SOFT_LIGHT if not is_dark else Colors.BG_LISTBOX_DARK
        even_bg = Colors.BG_LISTBOX_ALT_LIGHT if not is_dark else Colors.BG_LISTBOX_ALT_DARK
        try:
            treeview.tag_configure("odd", background=odd_bg)
            treeview.tag_configure("even", background=even_bg)
        except (tkinter.TclError, AttributeError, RuntimeError) as e:
            logger.debug(f"設定 Treeview 交錯列樣式暫時性失敗: {e}", "TreeUtils")
        except Exception:
            logger.exception("設定 Treeview 交錯列樣式失敗", "TreeUtils")
            return
        for index, item_id in enumerate(treeview.get_children("")):
            try:
                existing_tags = tuple(tag for tag in treeview.item(item_id, "tags") if tag not in {"odd", "even"})
                parity_tag = "odd" if index % 2 == 0 else "even"
                treeview.item(item_id, tags=(*existing_tags, parity_tag))
            except (tkinter.TclError, AttributeError, RuntimeError) as e:
                logger.debug(f"更新 Treeview 交錯列暫時性失敗 item={item_id}: {e}", "TreeUtils")
            except Exception:
                logger.exception(f"更新 Treeview 交錯列失敗 item={item_id}", "TreeUtils")

    @staticmethod
    def apply_listbox_alternating_rows(listbox, *, item_count: int | None = None) -> None:
        """套用 Listbox 交錯列背景。

        Args:
            listbox: 目標 Listbox。
            item_count: 要套用的項目數；未提供時使用 listbox.size()。
        """
        if not listbox:
            return
        is_dark = ctk.get_appearance_mode() == "Dark"
        odd_bg = Colors.BG_LISTBOX_LIGHT if not is_dark else Colors.BG_LISTBOX_DARK
        even_bg = Colors.BG_LISTBOX_ALT_LIGHT if not is_dark else Colors.BG_LISTBOX_ALT_DARK
        fg_color = Colors.TEXT_PRIMARY[0] if not is_dark else Colors.TEXT_ON_DARK
        total_items = int(item_count if item_count is not None else listbox.size())
        for index in range(max(0, total_items)):
            try:
                listbox.itemconfig(
                    index,
                    bg=odd_bg if index % 2 == 0 else even_bg,
                    fg=fg_color,
                    selectbackground=Colors.SELECT_BG,
                    selectforeground=Colors.TEXT_ON_DARK,
                )
            except (tkinter.TclError, AttributeError, RuntimeError) as e:
                logger.debug(f"設定 Listbox 交錯列暫時性失敗 index={index}: {e}", "TreeUtils")
                break
            except Exception:
                logger.exception(f"設定 Listbox 交錯列失敗 index={index}", "TreeUtils")
                break

    @staticmethod
    def make_tree_insert_batch(
        *,
        tree,
        pending_insert: list,
        batch_size: int,
        is_refresh_token_valid: Callable[[], bool],
        acquire_recycled: Callable[[tuple], str | None],
        update_recycled: Callable[[str, tuple], None],
        insert_new: Callable[[int, tuple], str],
        set_mapping: Callable[[str, str], None],
        mapping_get: Callable[[str], str | None],
        get_key: Callable[[tuple], str],
        set_row_snapshot: Callable[[str, tuple], None],
        get_order: Callable[[], list],
        _get_rows: Callable[[str], tuple | None],
        finalize_cb: Callable[[], None],
        set_refresh_job: Callable[[str | None], None],
        move_item: Callable[[str, int], None] | None = None,
        logger_name: str = "TreeUtils",
    ) -> Callable[[int, str | None], None]:
        """建立一個可重用的 Treeview 批次插入函式。

        Args:
            tree: 目標 Treeview。
            pending_insert: 待插入資料。
            batch_size: 每批插入數量。
            is_refresh_token_valid: 驗證刷新 token 是否仍有效。
            acquire_recycled: 取得可重用 item 的回呼。
            update_recycled: 更新可重用 item 的回呼。
            insert_new: 插入新 item 的回呼。
            set_mapping: 設定 key 到 item id 的映射。
            mapping_get: 取得 key 對應 item id 的回呼。
            get_key: 從 entry 取得 key 的回呼。
            set_row_snapshot: 設定 row snapshot 的回呼。
            get_order: 取得最終排序的回呼。
            _get_rows: 取得資料列的回呼。
            finalize_cb: 完成後要執行的回呼。
            set_refresh_job: 設定排程 job id 的回呼。
            move_item: 可選的 item 重新排序回呼。
            logger_name: 日誌 component 名稱。

        Returns:
            可呼叫的批次插入函式。
        """

        local_logger = get_logger().bind(component=logger_name)

        def insert_batch(start_index: int, current_job_id: str | None = None) -> None:
            if not is_refresh_token_valid():
                if current_job_id:
                    set_refresh_job(None)
                return
            if not tree or not getattr(tree, "winfo_exists", lambda: False)():
                if current_job_id:
                    set_refresh_job(None)
                return
            try:
                end_index = min(start_index + batch_size, len(pending_insert))
                for idx in range(start_index, end_index):
                    entry = pending_insert[idx]
                    recycled_item_id = acquire_recycled(entry)
                    if recycled_item_id:
                        update_recycled(recycled_item_id, entry)
                        inserted_item_id = recycled_item_id
                    else:
                        inserted_item_id = insert_new(idx, entry)
                    key = get_key(entry)
                    set_mapping(key, inserted_item_id)
                    set_row_snapshot(key, entry[1] if len(entry) > 1 else entry)
                if end_index < len(pending_insert):
                    next_job_id: str | None = None

                    def _run_next() -> None:
                        insert_batch(end_index, current_job_id=next_job_id)

                    next_job_id = tree.after(1, _run_next)
                    set_refresh_job(next_job_id)
                    return
                order = get_order()
                for order_index, key in enumerate(order):
                    item_id = mapping_get(key)
                    if item_id and move_item:
                        move_item(item_id, order_index)
                finalize_cb()
            except Exception as e:
                local_logger.debug(f"批次插入失敗: {e}")
                set_refresh_job(None)

        return insert_batch


__all__ = ["TreeUtils"]
