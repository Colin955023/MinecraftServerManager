"""版本與發行說明檢查工具。

集中管理版本解析、標籤驗證與 CHANGELOG 提取邏輯，
避免在 GitHub Actions workflow 內重複維護字串與正則處理。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
project_root_str = str(project_root)
if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)
from src.version_info.version_info import APP_VERSION

_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def _ensure_non_empty_str(parser: argparse.ArgumentParser, opt_name: str, value: object) -> str:
    """確保參數值為非空字串。"""
    if not isinstance(value, str) or not value.strip():
        parser.error(f"參數 --{opt_name} 必須為非空字串")
    return value


class ReleaseNotesNotFoundError(RuntimeError):
    """找不到指定版本的 CHANGELOG 章節。"""


def get_app_version() -> str:
    """回傳應用程式版本字串。"""
    return str(APP_VERSION)


def validate_release_tag() -> None:
    """驗證發行標籤是否合法。"""
    version = get_app_version()
    if not _VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"版本格式不合法：{version}")


def extract_release_notes(changelog_path: Path, *, strict: bool = False) -> str:
    """從 CHANGELOG 依版本標題提取發行說明內容。"""
    content = changelog_path.read_text(encoding="utf-8-sig") if changelog_path.exists() else ""

    version = get_app_version()
    heading_pattern = rf"##\s+\[?{re.escape(version)}\]?.*?\n(.*?)(?=\n##\s+|$)"

    match = re.search(heading_pattern, content, re.S)
    if match:
        return match.group(1).strip()

    if strict:
        raise ReleaseNotesNotFoundError(f"CHANGELOG.md 找不到版本 {version} 對應章節")

    return "Release notes not found in CHANGELOG.md"


def write_release_notes(changelog_path: Path, output_path: Path, *, strict: bool = False) -> None:
    """提取發行說明並寫入指定檔案。"""
    notes = extract_release_notes(changelog_path, strict=strict)
    output_path.write_text(notes, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="版本與發行說明檢查工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("get-all", help="一次輸出標籤與版本的 JSON 資料")

    extract_parser = subparsers.add_parser("extract-release-notes", help="從 CHANGELOG 提取發行說明")
    extract_parser.add_argument("--changelog", default="CHANGELOG.md", help="CHANGELOG 路徑")
    extract_parser.add_argument("--output", default="release_notes.md", help="輸出檔案路徑")
    extract_parser.add_argument("--strict", action="store_true", help="找不到章節時以非 0 結束")

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "get-all":
        try:
            validate_release_tag()
        except ValueError as e:
            sys.stderr.write(f"[錯誤] {e}\n")
            return 1

        tag = get_app_version()
        payload = {"Tag": tag, "Version": tag}
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return 0

    if args.command == "extract-release-notes":
        changelog = _ensure_non_empty_str(parser, "changelog", getattr(args, "changelog", None))
        output = _ensure_non_empty_str(parser, "output", getattr(args, "output", None))
        try:
            write_release_notes(Path(changelog).resolve(), Path(output).resolve(), strict=args.strict)
        except ReleaseNotesNotFoundError as e:
            sys.stderr.write(f"[錯誤] {e}\n")
            return 1
        sys.stdout.write(f"成功提取發行說明至 {output}\n")
        return 0

    parser.error("未知指令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
