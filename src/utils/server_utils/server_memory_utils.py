"""伺服器記憶體工具模組"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(slots=True)
class MemoryValidationResult:
    """記憶體驗證與正規化結果"""

    is_valid: bool
    memory_max_mb: int = 0
    memory_min_mb: int | None = None
    adjusted_max: bool = False
    adjusted_min: bool = False
    error_message: str | None = None
    warning_messages: list[str] = field(default_factory=list)


class MemoryUtils:
    """記憶體工具類別，提供記憶體相關的解析、格式化與驗證功能"""

    @staticmethod
    def parse_memory_setting(text: str, setting_type: str = "Xmx") -> int | None:
        """
        解析 Java 記憶體設定，統一處理 -Xmx 和 -Xms 參數

        Args:
            text: 含有 Java 記憶體參數的文字
            setting_type: 設定類型，通常為 Xmx 或 Xms

        Returns:
            以 MB 表示的記憶體大小；解析失敗時回傳 None
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
        格式化記憶體大小（MB），自動選擇單位顯示

        Args:
            memory_mb: 以 MB 表示的記憶體數值
            compact: 是否使用簡寫格式

        Returns:
            格式化後的字串
        """
        if compact:
            if memory_mb >= 1024:
                return f"{memory_mb // 1024}G" if memory_mb % 1024 == 0 else f"{memory_mb / 1024:.1f}G"
            return f"{memory_mb}M"
        if memory_mb >= 1024:
            return f"{memory_mb / 1024:.1f} GB"
        return f"{memory_mb:.1f} MB"

    @staticmethod
    def validate_and_normalize_server_memory(
        max_memory_text: str,
        min_memory_text: str = "",
        total_memory_mb: int = 0,
    ) -> MemoryValidationResult:
        """
        驗證並正規化伺服器記憶體設定

        Args:
            max_memory_text: 最大記憶體文字
            min_memory_text: 最小記憶體文字（可選）
            total_memory_mb: 系統總實體記憶體（MB），用於邊界調整

        Returns:
            包含驗證狀態、正規化數值與提示訊息的結果物件
        """
        max_str = str(max_memory_text or "").strip()
        min_str = str(min_memory_text or "").strip()

        try:
            max_mb = int(max_str)
        except ValueError:
            return MemoryValidationResult(is_valid=False, error_message="最大記憶體必須是數字")

        if max_mb < 1024:
            return MemoryValidationResult(is_valid=False, error_message="最大記憶體不可低於 1024 MB")

        adjusted_max = False
        warnings: list[str] = []
        if total_memory_mb > 0 and max_mb > total_memory_mb:
            max_mb = total_memory_mb
            adjusted_max = True
            warnings.append(
                f"最大記憶體超出系統總實體記憶體 ({total_memory_mb} MB)，已自動調整為上限值 {total_memory_mb} MB。"
            )

        min_mb: int | None = None
        adjusted_min = False
        if min_str:
            try:
                min_mb = int(min_str)
            except ValueError:
                return MemoryValidationResult(is_valid=False, error_message="最小記憶體必須是數字")

            if min_mb <= 0:
                return MemoryValidationResult(is_valid=False, error_message="最小記憶體必須大於 0")

            if total_memory_mb > 0 and min_mb > total_memory_mb:
                min_mb = total_memory_mb
                adjusted_min = True
                warnings.append(
                    f"最小記憶體超出系統總實體記憶體 ({total_memory_mb} MB)，已自動調整為上限值 {total_memory_mb} MB。"
                )

            if min_mb > max_mb:
                return MemoryValidationResult(is_valid=False, error_message="最小記憶體不可大於最大記憶體")

        return MemoryValidationResult(
            is_valid=True,
            memory_max_mb=max_mb,
            memory_min_mb=min_mb,
            adjusted_max=adjusted_max,
            adjusted_min=adjusted_min,
            warning_messages=warnings,
        )


__all__ = ["MemoryUtils", "MemoryValidationResult"]
