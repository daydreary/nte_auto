import random
import threading
import time
from typing import Callable

from device_utils.adb_controller import AdbController
from path_utils import ScriptPath
from screen_utils.image_detector import detect_once
from device_utils.emulator_window import get_window_id

from module.workflow import WorkflowStep, WorkflowRunner

# 点击持续时间（毫秒）
TAP_DURATION_MS = 50

SCREENSHOT_FILE = "img_tmp/screenshot.png"

# 模板图位于本脚本目录下的 img_template/
_IMG_TEMPLATE = "img_template"

# =========================
# 动作坐标定义（你自行设置）
# =========================
POS_ENTRY = (1607, 50)
POS_ENTRY_SCROLL = (169, 537)
POS_GO = (1689, 1019)

POS_MOVE_FORWARD = (293, 851)
MOVE_DISTANCE = -100


def _template_path(filename: str) -> str:
    return str(ScriptPath.get_path(f"{_IMG_TEMPLATE}/{filename}"))


def _take_screenshot(adb: AdbController) -> str:
    result = str(adb.screenshot(SCREENSHOT_FILE))
    return result

def _log(log_fn: Callable[[str], None] | None, message: str) -> None:
    if log_fn:
        log_fn(message)
    else:
        print(message)


def _sleep(seconds: float, stop_event: threading.Event | None) -> bool:
    """可中断 sleep，返回 True 表示收到停止信号。"""
    if stop_event is None:
        time.sleep(seconds)
        return False
    return stop_event.wait(timeout=seconds)


def _should_stop(stop_event: threading.Event | None) -> bool:
    return stop_event is not None and stop_event.is_set()


def _notify_preview(
    adb: AdbController,
    preview_fn: Callable[[str], None] | None,
    window_id: int,
    log_fn: Callable[[str], None] | None,
    path: str | None = None,
) -> None:
    if preview_fn is None:
        return
    try:
        if (path is None):
            path = _take_screenshot(adb)
        preview_fn(path)
    except Exception as exc:
        _log(log_fn, f"预览截图失败: {exc}")

def where_am_i(adb: AdbController, preview_fn: Callable[[str], None] | None, window_id: int, log_fn: Callable[[str], None] | None) -> str | None:
    screenshot_where = _take_screenshot(adb)
    _notify_preview(adb,preview_fn, window_id, log_fn, screenshot_where)
    checks = (
        ("car_ui.png", "car_match_ui"),
        ("list.png", "entry_list"),
    )
    for filename, state in checks:
        matches = detect_once(
            template_path=_template_path(filename),
            screenshot_path=screenshot_where,
            threshold=0.82,
            result_count=1,
        )
        if matches:
            return state
    return None

def start_car_match(
    adb_serial: str,
    *,
    stop_event: threading.Event | None = None,
    log_fn: Callable[[str], None] | None = None,
    preview_fn: Callable[[str], None] | None = None,
) -> None:
    """黑暗赛车界主循环。"""
    adb = AdbController(device_serial=adb_serial)
    runner = WorkflowRunner(device_serial=adb_serial)
    

    _log(log_fn, f"黑暗赛车界脚本已启动，设备: {adb_serial}")
    window_id = get_window_id(adb_serial)   

    while not _should_stop(stop_event):
        where = where_am_i(adb, preview_fn, window_id, log_fn)

        if where == "entry_list":
            _log(log_fn, f"当前所在页面: 活动列表")
            screenshot_entry_list = _take_screenshot(adb)
            matches = detect_once(
                template_path=_template_path("list.png"),
                screenshot_path=screenshot_entry_list,
                threshold=0.82,
                result_count=1,
            )
            if matches:
                steps = [
                    WorkflowStep.long_press(matches[0]["center"][0], matches[0]["center"][1], wait_after=2),
                ]
                runner.run(steps, stop_event=stop_event, log_fn=log_fn)
                continue

            steps = [
                WorkflowStep.swipe(POS_ENTRY_SCROLL[0], POS_ENTRY_SCROLL[1], POS_ENTRY_SCROLL[0], POS_ENTRY_SCROLL[1] - 200, wait_after=2),
            ]
            runner.run(steps, stop_event=stop_event, log_fn=log_fn)
            
        elif where == "car_match_ui":
            screenshot_entry_list = _take_screenshot(adb)
            matches = detect_once(
                template_path=_template_path("car_ui.png"),
                screenshot_path=screenshot_entry_list,
                threshold=0.82,
                result_count=1,
            )
            if matches:
                steps = [
                    WorkflowStep.tap(POS_GO[0], POS_GO[1], wait_after=40),
                    WorkflowStep.swipe(POS_MOVE_FORWARD[0], POS_MOVE_FORWARD[1], POS_MOVE_FORWARD[0], POS_MOVE_FORWARD[1] + MOVE_DISTANCE, duration_ms=20000, wait_after=20),
                ]
                runner.run(steps, stop_event=stop_event, log_fn=log_fn)

                _notify_preview(adb,preview_fn, window_id, log_fn)

                while not _should_stop(stop_event):
                    time.sleep(10)
                    result_ui = _take_screenshot(adb)
                    matches = detect_once(
                        template_path=_template_path("quit.png"),
                        screenshot_path=result_ui,
                        threshold=0.82,
                        result_count=1,
                    )
                    if matches:
                        steps = [
                            WorkflowStep.long_press(matches[0]["center"][0], matches[0]["center"][1], wait_after=10),
                        ]
                        runner.run(steps, stop_event=stop_event, log_fn=log_fn)
                        break

        else:
            steps = [
                WorkflowStep.tap(POS_ENTRY[0], POS_ENTRY[1], wait_after=2),
            ]
            runner.run(steps, stop_event=stop_event, log_fn=log_fn)

        if _should_stop(stop_event):
            break

    _log(log_fn, "黑暗赛车界脚本已停止")
