"""UI 工作範圍：統一背景工作的提交、結果投遞、取消與延遲排程"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from PySide6 import QtCore

from src.utils import CancellationToken, get_logger, is_qobject_alive

logger = get_logger().bind(component="UIWorkScope")


class WorkStatus(Enum):
    """UI 背景工作的完成狀態"""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class WorkOutcome:
    """由 UIWorkScope 投遞的不可變工作結果"""

    status: WorkStatus
    value: Any = None
    error: BaseException | None = None

    @staticmethod
    def succeeded(value: Any = None) -> WorkOutcome:
        """建立成功結果

        Args:
            value: 工作完成後攜帶的結果值

        Returns:
            狀態為成功的工作結果
        """
        return WorkOutcome(status=WorkStatus.SUCCEEDED, value=value)

    @staticmethod
    def failed(error: BaseException) -> WorkOutcome:
        """建立含例外的失敗結果

        Args:
            error: 導致工作失敗的例外

        Returns:
            狀態為失敗且含原始例外的工作結果
        """
        return WorkOutcome(status=WorkStatus.FAILED, error=error)

    @staticmethod
    def cancelled() -> WorkOutcome:
        """建立取消結果

        Returns:
            狀態為已取消的工作結果
        """
        return WorkOutcome(status=WorkStatus.CANCELLED)

    @property
    def is_succeeded(self) -> bool:
        return self.status == WorkStatus.SUCCEEDED

    @property
    def is_failed(self) -> bool:
        return self.status == WorkStatus.FAILED

    @property
    def is_cancelled(self) -> bool:
        return self.status == WorkStatus.CANCELLED


class _WorkHandle:
    """工作句柄，用於取消與追蹤工作"""

    def __init__(self, generation: int, key: str | None, cancel_token: CancellationToken):
        self._generation = generation
        self._key = key
        self._cancel_token = cancel_token
        self._is_cancelled = False

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def key(self) -> str | None:
        return self._key

    def cancel(self) -> None:
        self._is_cancelled = True
        self._cancel_token.cancel()

    @property
    def is_cancelled(self) -> bool:
        return self._is_cancelled


class _WorkRunnable(QtCore.QRunnable):
    def __init__(
        self,
        generation: int,
        work: Callable[[], Any],
        cancel_token: CancellationToken,
        outcome_signal: QtCore.SignalInstance,
    ):
        super().__init__()
        self._generation = generation
        self._work = work
        self._cancel_token = cancel_token
        self._outcome_signal = outcome_signal

    def run(self) -> None:
        if self._cancel_token.is_cancelled():
            self._outcome_signal.emit(self._generation, WorkOutcome.cancelled())
            return

        try:
            result = self._work()
            if self._cancel_token.is_cancelled():
                self._outcome_signal.emit(self._generation, WorkOutcome.cancelled())
            else:
                self._outcome_signal.emit(self._generation, WorkOutcome.succeeded(result))
        except Exception as e:
            logger.exception(f"Background work error in generation {self._generation}", exc_info=e)
            self._outcome_signal.emit(self._generation, WorkOutcome.failed(e))


class UIWorkScope(QtCore.QObject):
    """UI 工作範圍，管理背景工作提交、結果投遞、取消與延遲排程"""

    _outcome_signal = QtCore.Signal(int, object)

    def __init__(self, parent: QtCore.QObject):
        if not isinstance(parent, QtCore.QObject):
            raise TypeError("parent must be a QObject")
        super().__init__(parent)
        self._generation: int = 0
        self._gen_lock = threading.Lock()
        self._active_handles: dict[int, _WorkHandle] = {}
        self._key_generations: dict[str, int] = {}
        self._timers: dict[str, QtCore.QTimer] = {}
        self._draining: bool = False

        self._pool = QtCore.QThreadPool(self)
        self._pool.setMaxThreadCount(4)

        self._callbacks: dict[int, tuple[Callable[[WorkOutcome], None] | None, bool, str | None]] = {}

        self._outcome_signal.connect(self._on_outcome_received, QtCore.Qt.ConnectionType.QueuedConnection)
        self.destroyed.connect(self._on_destroyed)

    def submit(
        self,
        work: Callable[[], Any],
        *,
        on_done: Callable[[WorkOutcome], None] | None = None,
        key: str | None = None,
        replace: bool = False,
        critical: bool = False,
    ) -> _WorkHandle:
        """
        提交一個背景工作，並在完成時透過 on_done 回呼通知結果

        Args:
            work: 要執行的背景工作 callable
            on_done: 工作完成後的回呼函式，接收 WorkOutcome 參數
            key: 可選的工作鍵，用於取消或替換相同鍵的工作
            replace: 如果為 True，則取消並替換相同鍵的現有工作
            critical: 如果為 True，則此工作被視為關鍵工作，取消時不會影響其他工作

        Returns:
            用於取消和追蹤工作的句柄
        """
        if self._draining:
            logger.warning("UIWorkScope is draining, rejecting new work")
            handle = _WorkHandle(-1, key, CancellationToken())
            handle.cancel()
            if on_done:
                on_done(WorkOutcome.cancelled())
            return handle

        with self._gen_lock:
            self._generation += 1
            generation = self._generation

            if key is not None:
                if replace and key in self._key_generations:
                    prev_gen = self._key_generations[key]
                    if prev_gen in self._active_handles:
                        logger.debug(f"Cancelling previous work for key {key} (generation {prev_gen})")
                        self._active_handles[prev_gen].cancel()
                self._key_generations[key] = generation

            cancel_token = CancellationToken()
            handle = _WorkHandle(generation, key, cancel_token)
            self._active_handles[generation] = handle
            self._callbacks[generation] = (on_done, critical, key)

            runnable = _WorkRunnable(generation, work, cancel_token, self._outcome_signal)
            self._pool.start(runnable)

            return handle

    @QtCore.Slot(int, object)
    def _on_outcome_received(self, generation: int, outcome: WorkOutcome) -> None:
        if not is_qobject_alive(self):
            logger.debug(f"UIWorkScope destroyed, dropping outcome for generation {generation}")
            return

        with self._gen_lock:
            if generation not in self._active_handles:
                logger.debug(f"Generation {generation} not in active handles, dropping outcome")
                self._callbacks.pop(generation, None)
                return

            callback_info = self._callbacks.pop(generation, None)
            if not callback_info:
                return

            on_done, _, key = callback_info

            if key is not None:
                latest_gen = self._key_generations.get(key)
                if latest_gen != generation:
                    logger.debug(f"Outcome for generation {generation} superseded by {latest_gen} for key {key}")
                    self._active_handles.pop(generation, None)
                    return

            self._active_handles.pop(generation, None)

        if on_done:
            on_done(outcome)

    def schedule(self, delay_ms: int, callback: Callable[[], None], *, key: str | None = None) -> None:
        """
        排程一個延遲執行的回呼，若指定 key，則會取消並替換相同 key 的現有排程

        Args:
            delay_ms: 延遲時間（毫秒）
            callback: 要執行的回呼函式
            key: 可選的排程鍵，用於取消或替換相同鍵的排程
        """
        if self._draining:
            return

        if key is not None and key in self._timers:
            self._timers[key].stop()

        timer = QtCore.QTimer(self)
        timer.setSingleShot(True)

        def _on_timeout():
            if key is not None:
                self._timers.pop(key, None)
            callback()

        timer.timeout.connect(_on_timeout)

        if key is not None:
            self._timers[key] = timer

        timer.start(delay_ms)

    def cancel_all(self) -> None:
        """取消所有已排程的工作"""
        with self._gen_lock:
            for gen, handle in list(self._active_handles.items()):
                callback_info = self._callbacks.get(gen)
                if callback_info:
                    _, critical, _ = callback_info
                    if not critical:
                        handle.cancel()

        for timer in self._timers.values():
            timer.stop()
        self._timers.clear()

    def drain(self, timeout_ms: int = 2000) -> None:
        """
        等待所有工作完成

        Args:
            timeout_ms: 等待的最大時間（毫秒）
        """
        self._draining = True
        self.cancel_all()
        self._pool.waitForDone(timeout_ms)

    def _on_destroyed(self) -> None:
        self.drain()


__all__ = ["UIWorkScope"]
