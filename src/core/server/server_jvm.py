"""
JVM 參數策略

集中產生 Minecraft 伺服器 JVM 啟動參數建議。
從 server_runtime.py 提取以打破與 server_detection.py 的循環匯入。
"""

from __future__ import annotations

import shlex
from typing import Any


class JvmOptionPolicy:
    """集中產生 Minecraft 伺服器 JVM 啟動參數建議。"""

    GC_OPTION_PREFIX = "-XX:+Use"
    LOW_LATENCY_PROFILE = "low_latency"

    @staticmethod
    def normalize_jvm_args(raw_args: Any) -> list[str]:
        """
        將使用者自訂 JVM 參數正規化為清單。

        Args:
            raw_args: 字串、序列或其他可忽略值。

        Returns:
            正規化後的 JVM 參數清單。
        """

        if raw_args is None:
            return []
        if isinstance(raw_args, str):
            try:
                return [arg for arg in shlex.split(raw_args) if arg]
            except ValueError:
                return [arg for arg in raw_args.split() if arg]
        if isinstance(raw_args, (list, tuple)):
            return [str(arg).strip() for arg in raw_args if str(arg).strip()]
        return []

    @staticmethod
    def has_gc_option(args: list[str]) -> bool:
        """檢查參數中是否已包含 GC 選項。"""

        return any(arg.startswith(JvmOptionPolicy.GC_OPTION_PREFIX) and arg.endswith("GC") for arg in args)

    @staticmethod
    def recommend_gc_args(
        *,
        memory_max_mb: int,
        java_major: int | None = None,
        performance_profile: str = "",
        existing_args: list[str] | None = None,
    ) -> list[str]:
        """
        依記憶體與 Java 版本產生 GC 建議。

        Args:
            memory_max_mb: 最大記憶體，單位 MB。
            java_major: Java major 版本；未知時可為 None。
            performance_profile: 效能設定檔，`low_latency` 表示偏低延遲。
            existing_args: 既有 JVM 參數；若已有 GC 參數則不覆蓋。

        Returns:
            建議加入的 JVM 參數清單。
        """

        normalized_existing_args = list(existing_args or [])
        if JvmOptionPolicy.has_gc_option(normalized_existing_args):
            return []
        normalized_profile = str(performance_profile or "").strip().lower()
        if normalized_profile == JvmOptionPolicy.LOW_LATENCY_PROFILE and java_major and java_major >= 17:
            return ["-XX:+UseZGC"]
        if int(memory_max_mb or 0) > 4096:
            return ["-XX:+UseG1GC"]
        return []
