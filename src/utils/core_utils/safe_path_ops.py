"""安全路徑操作工具，僅處理路徑檢查、目錄/檔案安全操作。"""

import shutil
from pathlib import Path


class SafePathOps:
    """安全路徑操作工具，僅處理路徑檢查、目錄/檔案安全操作。"""

    @staticmethod
    def is_path_within(base_dir: Path, target_path: Path, *, strict: bool = True) -> bool:
        """
        檢查 target_path 是否在 base_dir 內部。
        Args:
            base_dir (Path): 基準目錄。
            target_path (Path): 目標路徑。
            strict (bool, optional): 是否使用嚴格模式。默認為 True。
        Returns:
            bool: 如果 target_path 在 base_dir 內部，返回 True；否則返回 False。
        """
        try:
            base_resolved = base_dir.resolve(strict=True)
            target_resolved = target_path.resolve(strict=strict)
        except FileNotFoundError:
            return False
        except OSError:
            return False
        try:
            target_resolved.relative_to(base_resolved)
            return True
        except ValueError:
            return False

    @staticmethod
    def ensure_dir_exists(path: Path) -> bool:
        """
        確保目錄存在，如果不存在則創建。

        Args:
            path (Path): 要確保存在的目錄路徑。

        Returns:
            bool: 如果目錄存在或成功創建，返回 True；否則返回 False。
        """
        try:
            path.mkdir(parents=True, exist_ok=True)
            return True
        except OSError:
            return False

    @staticmethod
    def delete_path(path: Path | str) -> bool:
        """
        安全地刪除指定的文件或目錄。

        Args:
            path (Path | str): 要刪除的文件或目錄路徑。

        Returns:
            bool: 如果刪除成功，返回 True；否則返回 False。
        """
        try:
            if isinstance(path, str):
                path = Path(path)
            if not path.exists():
                return True
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            return True
        except OSError:
            return False

    @staticmethod
    def move_path(src: Path, dst: Path) -> bool:
        """
        安全地移動文件或目錄。

        Args:
            src (Path): 源文件或目錄路徑。
            dst (Path): 目標文件或目錄路徑。

        Returns:
            bool: 如果移動成功，返回 True；否則返回 False。
        """
        try:
            if not src.exists():
                return False
            dst.parents[0].mkdir(parents=True, exist_ok=True)
            shutil.move(src, dst)
            return True
        except OSError:
            return False

    @staticmethod
    def copy_file(src: Path, dst: Path) -> bool:
        """
        安全地複製文件。

        Args:
            src (Path): 源文件路徑。
            dst (Path): 目標文件路徑。

        Returns:
            bool: 如果複製成功，返回 True；否則返回 False。
        """
        try:
            if not src.exists():
                return False
            dst.parents[0].mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return True
        except OSError:
            return False
