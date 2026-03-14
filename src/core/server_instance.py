"""伺服器實例 (ServerInstance) skeleton。

封裝單一伺服器的基礎屬性與基本 process 管理，供逐步遷移用。
"""

from __future__ import annotations

import threading
from ..utils.subprocess_utils import SubprocessUtils, get_logger
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    # 僅在型別檢查時引入以避免執行時依賴循環
    from ..models import ServerConfig
else:
    ServerConfig = Any

logger = get_logger().bind(component="ServerInstance")


@dataclass
class ServerInstance:
    """代表單一伺服器的輕量實例封裝。

    屬性皆為公開以利逐步遷移；方法提供最小的 process 管理介面。
    """

    id: str
    name: str
    path: Path
    config: ServerConfig | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    process: Any | None = field(default=None, init=False, repr=False)

    def start(self, cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> Any:
        """啟動伺服器，回傳 subprocess.Popen 物件。

        注意：此方法為同步呼叫（會立即 return Popen），若需非同步監控請使用 BackgroundTask。
        """
        with self._lock:
            if self.process is not None:
                raise RuntimeError("伺服器已在執行中")
            cwd = cwd or self.path
            proc = SubprocessUtils.popen_checked(
                cmd, cwd=str(cwd), env=env, stdout=SubprocessUtils.PIPE, stderr=SubprocessUtils.PIPE
            )
            self.process = proc
            return proc

    def stop(self, timeout: float = 5.0) -> bool:
        """嘗試優雅停止伺服器，若逾時則強制終止。"""
        with self._lock:
            if self.process is None:
                return True
            try:
                self.process.terminate()
                self.process.wait(timeout=timeout)
            except SubprocessUtils.TimeoutExpired:
                # 逾時，嘗試強制終止
                try:
                    self.process.kill()
                    self.process.wait(timeout=1)
                except (SubprocessUtils.TimeoutExpired, OSError):
                    logger.warning(
                        "強制終止超時伺服器進程失敗 (id=%s, name=%s).",
                        getattr(self, "id", None),
                        getattr(self, "name", None),
                        exc_info=True,
                    )
            except OSError:
                # I/O 相關錯誤（例如管線已關閉），嘗試強制終止以確保資源清理
                try:
                    self.process.kill()
                    self.process.wait(timeout=1)
                except (SubprocessUtils.TimeoutExpired, OSError):
                    logger.warning(
                        "強制終止伺服器進程失敗 (id=%s, name=%s).",
                        getattr(self, "id", None),
                        getattr(self, "name", None),
                        exc_info=True,
                    )
            finally:
                self.process = None
            return True

    def is_running(self) -> bool:
        """回傳是否有正在執行的 process。"""
        with self._lock:
            return self.process is not None and self.process.poll() is None

    def to_dict(self) -> dict[str, Any]:
        """序列化不含 process 的 instance 資料，用於儲存或 UI 顯示。"""
        return {"id": self.id, "name": self.name, "path": str(self.path), "metadata": dict(self.metadata)}
