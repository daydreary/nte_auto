from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from device_utils.adb_controller import AdbController


class ActionType(str, Enum):
    """工作流步骤类型。"""

    TAP = "tap"
    LONG_PRESS = "long_press"
    SWIPE = "swipe"
    INPUT_TEXT = "input_text"


@dataclass(frozen=True)
class WorkflowStep:
    """
    单条工作流步骤。

    - TAP / LONG_PRESS：使用 x, y
    - SWIPE：使用 x, y 作为起点，end_x, end_y 作为终点
    - INPUT_TEXT：使用 text（需输入框已聚焦，会先清空再输入）
    - duration_ms：长按或滑动的持续时间（毫秒）
    - wait_after：该步骤执行完成后的等待时间（秒）
    """

    action: ActionType
    x: int = 0
    y: int = 0
    wait_after: float = 0.0
    duration_ms: int = 300
    end_x: int | None = None
    end_y: int | None = None
    text: str = ""
    name: str = ""

    @classmethod
    def tap(
        cls,
        x: int,
        y: int,
        *,
        wait_after: float = 0.0,
        name: str = "",
    ) -> WorkflowStep:
        return cls(action=ActionType.TAP, x=x, y=y, wait_after=wait_after, name=name)

    @classmethod
    def long_press(
        cls,
        x: int,
        y: int,
        *,
        duration_ms: int = 1000,
        wait_after: float = 0.0,
        name: str = "",
    ) -> WorkflowStep:
        return cls(
            action=ActionType.LONG_PRESS,
            x=x,
            y=y,
            duration_ms=duration_ms,
            wait_after=wait_after,
            name=name,
        )

    @classmethod
    def swipe(
        cls,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        duration_ms: int = 300,
        wait_after: float = 0.0,
        name: str = "",
    ) -> WorkflowStep:
        return cls(
            action=ActionType.SWIPE,
            x=x1,
            y=y1,
            end_x=x2,
            end_y=y2,
            duration_ms=duration_ms,
            wait_after=wait_after,
            name=name,
        )

    @classmethod
    def input_text(
        cls,
        text: str,
        *,
        wait_after: float = 0.0,
        name: str = "",
    ) -> WorkflowStep:
        return cls(
            action=ActionType.INPUT_TEXT,
            text=text,
            wait_after=wait_after,
            name=name,
        )


class WorkflowRunner:
    """按顺序执行 WorkflowStep 列表。"""

    def __init__(
        self,
        adb: AdbController | None = None,
        *,
        device_serial: str | None = None,
    ) -> None:
        self._adb = adb or AdbController(device_serial=device_serial)

    @property
    def adb(self) -> AdbController:
        return self._adb

    def run(
        self,
        steps: list[WorkflowStep],
        *,
        stop_event: threading.Event | None = None,
        log_fn: Callable[[str], None] | None = None,
    ) -> bool:
        """
        依次执行步骤列表。

        返回 True 表示全部执行完成；若收到 stop_event 中断则返回 False。
        """
        for index, step in enumerate(steps, start=1):
            if self._should_stop(stop_event):
                return False

            label = step.name or step.action.value
            self._log(log_fn, f"[{index}/{len(steps)}] {label} {self._step_detail(step)}")
            self._execute_step(step)

            if step.wait_after <= 0:
                continue
            if self._sleep(step.wait_after, stop_event):
                return False

        return True

    def _execute_step(self, step: WorkflowStep) -> None:
        if step.action is ActionType.TAP:
            self._adb.tap(step.x, step.y)
            return

        if step.action is ActionType.LONG_PRESS:
            self._adb.long_press(step.x, step.y, duration_ms=step.duration_ms)
            return

        if step.action is ActionType.SWIPE:
            if step.end_x is None or step.end_y is None:
                raise ValueError(
                    f"SWIPE 步骤缺少终点坐标: {step.name or step.action.value}"
                )
            self._adb.swipe(
                step.x,
                step.y,
                step.end_x,
                step.end_y,
                duration_ms=step.duration_ms,
            )
            return

        if step.action is ActionType.INPUT_TEXT:
            if not step.text:
                raise ValueError(
                    f"INPUT_TEXT 步骤缺少文本内容: {step.name or step.action.value}"
                )
            self._adb.input_text(step.text)
            return

        raise ValueError(f"不支持的操作类型: {step.action}")

    @staticmethod
    def _step_detail(step: WorkflowStep) -> str:
        if step.action is ActionType.INPUT_TEXT:
            return f'"{step.text}"'
        if step.action is ActionType.SWIPE:
            return (
                f"({step.x}, {step.y}) -> ({step.end_x}, {step.end_y})"
            )
        return f"({step.x}, {step.y})"

    @staticmethod
    def _should_stop(stop_event: threading.Event | None) -> bool:
        return stop_event is not None and stop_event.is_set()

    @staticmethod
    def _sleep(seconds: float, stop_event: threading.Event | None) -> bool:
        """可中断 sleep，返回 True 表示收到停止信号。"""
        if stop_event is None:
            time.sleep(seconds)
            return False
        return stop_event.wait(timeout=seconds)

    @staticmethod
    def _log(log_fn: Callable[[str], None] | None, message: str) -> None:
        if log_fn:
            log_fn(message)
        else:
            print(message)
