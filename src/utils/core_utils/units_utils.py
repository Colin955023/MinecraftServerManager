"""
單位換算工具模組
提供共用的位元組（bytes）單位換算與格式化功能。
"""


def bytes_to_mb(size: int | float) -> float:
    """將位元組數轉換為 MiB。"""
    return float(size) / (1024 * 1024)


def format_bytes(size: int) -> str:
    """將位元組數格式化為適合顯示的二進位單位文字。"""
    size = max(0, int(size))
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
