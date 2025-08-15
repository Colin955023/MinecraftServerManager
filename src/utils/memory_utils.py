#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
記憶體工具模組
提供記憶體設定解析和格式化功能
Memory Utilities Module
Provides memory setting parsing and formatting functionality
"""
# ====== 標準函式庫 ======
from typing import Optional
import re

# ====== 記憶體工具類別 ======
class MemoryUtils:
    """
    記憶體工具類別，提供記憶體相關的解析和格式化功能
    Memory utilities class for memory-related parsing and formatting functions
    """

    @staticmethod
    def parse_memory_setting(text: str, setting_type: str = "Xmx") -> Optional[int]:
        """
        解析 Java 記憶體設定，統一處理 -Xmx 和 -Xms 參數
        Args:
            text: 包含記憶體設定的文本
            setting_type: "Xmx" 或 "Xms"
        Returns:
            記憶體大小（MB），如果找不到則返回 None
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
                else:
                    return val
            except ValueError:
                return None
        return None

    @staticmethod
    def format_memory(memory_bytes: float) -> str:
        """格式化記憶體大小"""
        if memory_bytes < 1024:
            return f"{memory_bytes:.1f} B"
        elif memory_bytes < 1024 * 1024:
            return f"{memory_bytes / 1024:.1f} KB"
        elif memory_bytes < 1024 * 1024 * 1024:
            return f"{memory_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{memory_bytes / (1024 * 1024 * 1024):.1f} GB"

    @staticmethod
    def format_memory_mb(memory_mb: int) -> str:
        """格式化記憶體顯示（MB輸入），自動選擇 M 或 G 單位"""
        if memory_mb >= 1024:
            if memory_mb % 1024 == 0:
                return f"{memory_mb // 1024}G"
            else:
                return f"{memory_mb / 1024:.1f}G"
        else:
            return f"{memory_mb}M"
