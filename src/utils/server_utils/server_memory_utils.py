"""伺服器記憶體工具模組。"""

import re


class MemoryUtils:
    """記憶體工具類別，提供記憶體相關的解析和格式化功能。"""

    @staticmethod
    def parse_memory_setting(text: str, setting_type: str = "Xmx") -> int | None:
        """解析 Java 記憶體設定，統一處理 -Xmx 和 -Xms 參數。

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
        """格式化記憶體大小（MB），自動選擇單位顯示。

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
