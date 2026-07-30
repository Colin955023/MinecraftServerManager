"""伺服器記憶體工具模組。"""

from __future__ import annotations

import re
from dataclasses import dataclass


class MemoryUtils:
    """記憶體工具類別，提供記憶體相關的解析和格式化功能。"""

    @staticmethod
    def parse_memory_setting(text: str, setting_type: str = "Xmx") -> int | None:
        """
        解析 Java 記憶體設定，統一處理 -Xmx 和 -Xms 參數。

        Args:
            text: 含有 Java 記憶體參數的文字。
            setting_type: 設定類型，通常為 `Xmx` 或 `Xms`。

        Returns:
            以 MB 表示的記憶體大小；解析失敗時回傳 `None`。
        """
        if not text or not isinstance(text, str):
            return None
        if not setting_type or setting_type not in ["Xmx", "Xms"]:
            return None
        pattern = rf"-{setting_type}(\d+)([mMgG]?)"
        match = re.search(pattern, text)
        if match:
            val, unit = match.groups()
            try:
                val = int(val)
                if unit and unit.lower() == "g":
                    return val * 1024
                return val
            except ValueError:
                return None
        return None

    @staticmethod
    def format_memory_mb(memory_mb: int, compact: bool = True) -> str:
        """
        格式化記憶體大小（MB），自動選擇單位顯示。

        Args:
            memory_mb: 以 MB 表示的記憶體數值。
            compact: 是否使用簡寫格式。

        Returns:
            格式化後的字串。
        """
        if compact:
            if memory_mb >= 1024:
                return f"{memory_mb // 1024}G" if memory_mb % 1024 == 0 else f"{memory_mb / 1024:.1f}G"
            return f"{memory_mb}M"
        if memory_mb >= 1024:
            return f"{memory_mb / 1024:.1f} GB"
        return f"{memory_mb:.1f} MB"

    @staticmethod
    def check_memory_limits(
        min_mb: int,
        max_mb: int,
        total_system_mb: int,
    ) -> MemoryCheckResult:
        """
        驗證記憶體配置是否合法，回傳警告文字與顏色代碼。

        Args:
            min_mb: 最小記憶體 (MB)
            max_mb: 最大記憶體 (MB)
            total_system_mb: 系統總實體記憶體 (MB)

        Returns:
            MemoryCheckResult: 包含警告文字、顏色類別、是否有效
        """
        half_system_mb = total_system_mb // 2

        # 最小記憶體不能大於最大記憶體
        if min_mb > max_mb:
            return MemoryCheckResult(
                warning_text="⚠️ 警告：最小記憶體不能大於最大記憶體",
                color="error",
                is_valid=False,
            )

        # 最大記憶體超過系統總記憶體
        if max_mb > total_system_mb:
            return MemoryCheckResult(
                warning_text=f"⚠️ 警告：設定記憶體超過系統總記憶體 ({total_system_mb}MB)",
                color="error",
                is_valid=False,
            )

        # 最大記憶體超過系統記憶體一半
        if max_mb > half_system_mb:
            return MemoryCheckResult(
                warning_text=f"⚠️ 提示：設定記憶體超過系統記憶體的一半 ({half_system_mb}MB)",
                color="warning",
                is_valid=True,
            )

        # 通過所有檢查
        return MemoryCheckResult(
            warning_text="",
            color="none",
            is_valid=True,
        )


@dataclass(slots=True)
class MemoryCheckResult:
    """記憶體檢查結果。"""

    warning_text: str
    color: str  # "error" | "warning" | "none"
    is_valid: bool
