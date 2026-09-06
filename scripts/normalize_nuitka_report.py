"""標準化並驗證 Nuitka 編譯報告的 XML 編碼宣告"""

from __future__ import annotations

from pathlib import Path

from defusedxml import ElementTree


def main() -> None:
    """修正 Nuitka 使用的非標準 utf8 編碼別名並驗證 XML"""
    report_path = Path(__file__).resolve().parents[1] / "report" / "nuitka-compilation-report.xml"
    raw = report_path.read_bytes()
    single_quote = bytes([39])
    double_quote = bytes([34])
    normalized = raw.replace(
        b"encoding=" + single_quote + b"utf8" + single_quote,
        b"encoding=" + single_quote + b"UTF-8" + single_quote,
        1,
    )
    normalized = normalized.replace(
        b"encoding=" + double_quote + b"utf8" + double_quote,
        b"encoding=" + double_quote + b"UTF-8" + double_quote,
        1,
    )
    ElementTree.fromstring(normalized)
    if normalized == raw:
        return
    temporary_path = report_path.with_suffix(report_path.suffix + ".tmp")
    try:
        temporary_path.write_bytes(normalized)
        temporary_path.replace(report_path)
    finally:
        temporary_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
