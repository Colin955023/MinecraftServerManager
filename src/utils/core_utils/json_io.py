"""JSON 讀寫與序列化工具。"""

import json
from pathlib import Path
from typing import Any

from .atomic_writer import atomic_write_json


class JsonIO:
    """JSON 讀寫與序列化工具。"""

    @staticmethod
    def load_json(path: Path | str, default: Any = None) -> Any:
        """
        從指定路徑讀取 JSON 文件並返回其內容。如果文件不存在或無法解析，則返回默認值。

        Args:
            path (Path | str): JSON 文件的路徑。
            default (Any, optional): 如果文件不存在或無法解析，返回的默認值。默認為 None。
        Returns:
            Any: 讀取的 JSON 數據，或者默認值。
        """
        try:
            p = Path(path)
            if not p.exists():
                return default
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    @staticmethod
    def save_json(path: Path | str, data: Any, indent: int = 2) -> bool:
        """
        將數據保存到指定的 JSON 文件中。

        Args:
            path (Path | str): JSON 文件的路徑。
            data (Any): 要保存的數據。
            indent (int, optional): JSON 文件的縮進空格數。默認為 2。

        Returns:
            bool: 保存成功返回 True，否則返回 False。
        """
        try:
            return atomic_write_json(Path(path), data, indent=indent)
        except Exception:
            return False

    @staticmethod
    def to_json_str(data: Any, indent: int | None = None) -> str:
        """
        將數據序列化為 JSON 字符串。

        Args:
            data (Any): 要序列化的數據。
            indent (int | None, optional): JSON 字符串的縮進空格數。默認為 None，表示不使用縮進。
        Returns:
            str: 序列化後的 JSON 字符串，如果序列化失敗則返回空字符串。
        """
        try:
            return json.dumps(data, indent=indent, ensure_ascii=False)
        except TypeError:
            return ""
        except ValueError:
            return ""

    @staticmethod
    def from_json_str(json_str: str) -> Any:
        """
        將 JSON 字符串反序列化為 Python 對象。

        Args:
            json_str (str): 要反序列化的 JSON 字符串。
        Returns:
            Any: 反序列化後的 Python 對象，如果反序列化失敗則返回 None。
        """
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return None
        except TypeError:
            return None
        except ValueError:
            return None
