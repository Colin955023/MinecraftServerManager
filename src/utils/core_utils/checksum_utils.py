"""檔案雜湊與檢查碼工具。"""

import hashlib
from pathlib import Path


class ChecksumUtils:
    """提供檔案雜湊與檢查碼相關功能的工具類別。"""

    @staticmethod
    def calculate_checksum(path: Path, algorithm: str = "sha256") -> str | None:
        """
        計算檔案的雜湊值。

        Args:
            path: 檔案路徑。
            algorithm: 雜湊演算法，預設為 "sha256"。

        Returns:
            檔案的雜湊值，若發生錯誤則返回 None。
        """
        try:
            if not path.exists():
                return None
            h = hashlib.new(algorithm)
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest().lower()
        except OSError:
            return None
