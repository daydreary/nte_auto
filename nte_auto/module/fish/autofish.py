import sys
import threading
import time
from typing import Callable

from device_utils.emulator_window import get_window_id
from screen_utils.image_detector import detect_once
from module.fish.region_detector import detect_green_and_yellow
from path_utils import ScriptPath
from device_utils.adb_controller import AdbController

from module.workflow import WorkflowStep, WorkflowRunner

from screen_utils.screenshot import (
    capture_window,
    capture_window_region,
)


# =========================
# 动作坐标定义（你自行设置）
# =========================
POS_READY_TO_FISH = (1233, 581)
POS_READY_TO_START = (1611, 939)
POS_FISH = (1739, 965)

POS_FISH_CLOSE = (1855, 64)

POS_MARKET = (1517, 983)
POS_SHOP = (1405, 983)

POS_BATE_CHOSEN = (1709, 783)
POS_BATE_CHOSEN_SHOP = (1305, 941)
POS_CHANGE_BAIT = (1167, 703)
POS_BAIT_INFO_CLOSE = (1835, 55)

POS_P = (1365, 983)
POS_O = (1577, 1053)
POS_Z = (1825, 97)
POS_X = (1151, 723)
POS_CANCEL = (1099, 999)

POS_CHAT_CLOSE = (1169, 67)
POS_BUY_CLOSE = (1829, 63)
POS_BUY_ADD = (1771, 947)

POS_SELL_2 = (153, 411)
POS_SELL_3 = (1063, 963)
POS_SELL_CLOSE = (1831, 64)

POS_CONFIRM = (1233, 583)

LEFT_TAP = (231, 869)
RIGHT_TAP = (1637, 869)

# 钓鱼进度条截图区域（窗口内 x, y, width, height）
# macOS/Windows 截图 API 对「内容区」起点的定义不同，且模拟器顶栏高度可能不一致，故 y 需分平台校准
_FISH_BAR_REGION_BY_PLATFORM: dict[str, tuple[int, int, int, int]] = {
    "darwin": (593, 146, 737, 26),
    "win32": (593, 128, 737, 26),
}


def _fish_bar_region() -> tuple[int, int, int, int]:
    return _FISH_BAR_REGION_BY_PLATFORM.get(
        sys.platform,
        _FISH_BAR_REGION_BY_PLATFORM["darwin"],
    )

success_count = 0
failed_count = 0

BUY_COUNT = 40

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
    preview_fn: Callable[[str], None] | None,
    window_id: int,
    log_fn: Callable[[str], None] | None,
) -> None:
    if preview_fn is None:
        return
    try:
        path = capture_window_region(
            window_id=window_id,
            x=0,
            y=0,
            width=1920,
            height=1080,
            fmt="png",
            name="preview.png",
        )
        preview_fn(path)
    except Exception as exc:
        _log(log_fn, f"预览截图失败: {exc}")


def relation(data: dict):
    """
    计算 green_region 与 yellow_cursor 中心点的水平位置关系。

    返回:
        float | None:
            - 正数：green 在 cursor 右侧
            - 负数：green 在 cursor 左侧
            - 绝对值表示中心点水平距离（像素）
    """
    green = data.get("green_region")
    cursor = data.get("yellow_cursor")

    if green is None or cursor is None:
        return None
    if not isinstance(green, dict) or not isinstance(cursor, dict):
        return None
    if "x" not in green or "w" not in green or "x" not in cursor or "w" not in cursor:
        return None

    try:
        center_green = green["x"] + green["w"] / 2.0
        center_cursor = cursor["x"] + cursor["w"] / 2.0
        return center_green - center_cursor
    except (TypeError, ValueError):
        return None


def calculate_delay(diff: float) -> float:
    delta = (abs(diff) / 65.0) * 200.0
    if diff < 0:
        return -delta
    return delta


def run_steps_fishing(
    window_id: int,
    adb_serial: str,
    *,
    stop_event: threading.Event | None = None,
    log_fn: Callable[[str], None] | None = None,
    preview_fn: Callable[[str], None] | None = None,
) -> None:
    global success_count, failed_count
    runner = WorkflowRunner(device_serial=adb_serial)
    """执行一次完整钓鱼流程。"""
    adb = AdbController(device_serial=adb_serial)

    steps = [
        WorkflowStep.tap(POS_CONFIRM[0], POS_CONFIRM[1], wait_after=2),
        WorkflowStep.tap(POS_FISH[0], POS_FISH[1], wait_after=10),
        WorkflowStep.tap(POS_FISH[0], POS_FISH[1], wait_after=1),
    ]
    runner.run(steps, stop_event=stop_event, log_fn=log_fn) 
    _log(log_fn, f"已开始钓鱼控制")
    while not _should_stop(stop_event):
        start_screenshot = time.perf_counter()

        bar_x, bar_y, bar_w, bar_h = _fish_bar_region()
        result_path = capture_window(
            window_id=window_id,
            fmt="png",
            name="screenshot.png",
            x=bar_x,
            y=bar_y,
            width=bar_w,
            height=bar_h,
        )

        end_screenshot = time.perf_counter()
        #_log(log_fn, f"截屏耗时：{end_screenshot - start_screenshot:.6f} 秒")

        start_analyze = time.perf_counter()
        result_dict = detect_green_and_yellow(result_path)
        diff = relation(result_dict)

        if diff is None:
            break

        end_analyze = time.perf_counter()
        #_log(log_fn, f"分析耗时：{end_analyze - start_analyze:.6f} 秒")
        #_log(log_fn, f"光标中心相差距离 = {diff}")

        delay_time = calculate_delay(diff)
        #_log(log_fn, f"按键延时 = {delay_time}")
        if delay_time < 0:
            adb.long_press(*LEFT_TAP, duration_ms=int(-delay_time))
        elif delay_time > 0:
            adb.long_press(*RIGHT_TAP, duration_ms=int(delay_time))

    if _should_stop(stop_event):
        return

    if _sleep(5, stop_event) or _should_stop(stop_event):
        return

    incase_failed_break = 0
    while not _should_stop(stop_event):
        if _sleep(1, stop_event) or _should_stop(stop_event):
            return
        incase_failed_break += 1
        if incase_failed_break > 8:
            failed_count += 1
            break
        screenshot_path = capture_window(
            window_id=window_id,
            fmt="png",
            name="full_screen.png",
            x=0,
            y=0,
            width=1920,
            height=1080,
        )
        matches = detect_once(
            template_path=ScriptPath.get_path("img_template/fish_success.png"),
            screenshot_path=screenshot_path,
            threshold=0.82,
        )
        if matches:
            success_count += 1
            _notify_preview(preview_fn, window_id, log_fn)
            break

    _log(log_fn, f"本次运行钓鱼成功次数: {success_count}，失败次数: {failed_count}")

    steps = [
        WorkflowStep.tap(POS_CANCEL[0], POS_CANCEL[1], wait_after=2),
        WorkflowStep.tap(POS_FISH_CLOSE[0], POS_FISH_CLOSE[1], wait_after=2),
    ]
    runner.run(steps, stop_event=stop_event, log_fn=log_fn)


def run_sell(
    adb_serial: str,
    *,
    stop_event: threading.Event | None = None,
) -> None:
    adb = AdbController(device_serial=adb_serial)
    runner = WorkflowRunner(device_serial=adb_serial)
    steps = [
        WorkflowStep.tap(POS_SELL_2[0], POS_SELL_2[1], wait_after=2),
        WorkflowStep.tap(POS_SELL_3[0], POS_SELL_3[1], wait_after=2),
        WorkflowStep.tap(POS_X[0], POS_X[1], wait_after=2),
        WorkflowStep.tap(POS_X[0], POS_X[1], wait_after=2),
        WorkflowStep.tap(POS_SELL_CLOSE[0], POS_SELL_CLOSE[1], wait_after=2),
        WorkflowStep.tap(POS_FISH_CLOSE[0], POS_FISH_CLOSE[1], wait_after=2),
    ]
    runner.run(steps, stop_event=stop_event, log_fn=log_fn)


def run_extra_step(
    window_id: int,
    adb_serial: str,
    *,
    stop_event: threading.Event | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> None:
    """每批次执行一次扩展步骤（补购鱼饵等）。"""
    adb = AdbController(device_serial=adb_serial)
    runner = WorkflowRunner(device_serial=adb_serial)
    if _should_stop(stop_event):
        return

    screenshot_dir = capture_window(
        window_id=window_id,
        fmt="png",
        name="full_screen.png",
        x=0,
        y=0,
        width=1920,
        height=1080,
    )

    matches = detect_once(
        template_path=ScriptPath.get_path("img_template/bait.png"),
        screenshot_path=screenshot_dir,
        threshold=0.82,
    )
    if matches:
        first_center = matches[0]["center"]
        adb.tap(int(first_center[0]), int(first_center[1]))
        _log(log_fn, f"找到鱼饵，位置 {first_center[0]}, {first_center[1]}")

    if _sleep(2, stop_event) or _should_stop(stop_event):
        return

    for _ in range(BUY_COUNT):
        steps = [
            WorkflowStep.tap(POS_BUY_ADD[0], POS_BUY_ADD[1], wait_after=0.2),
        ]
        runner.run(steps, stop_event=stop_event, log_fn=log_fn)

    steps = [
        WorkflowStep.tap(POS_O[0], POS_O[1], wait_after=2),
        WorkflowStep.tap(POS_X[0], POS_X[1], wait_after=2),
        WorkflowStep.tap(POS_CANCEL[0], POS_CANCEL[1], wait_after=2),
        WorkflowStep.tap(POS_BUY_CLOSE[0], POS_BUY_CLOSE[1], wait_after=2),
    ]
    runner.run(steps, stop_event=stop_event, log_fn=log_fn)


def where_am_i(window_id: int) -> str | None:
    screenshot_path = capture_window_region(
        window_id=window_id,
        x=0,
        y=0,
        width=1920,
        height=1080,
        fmt="png",
        name="full_screen.png",
    )

    templates = (
        ("img_template/ready_to_fish.png", "ready_to_fish"),
        ("img_template/bait.png", "bait_shop"),
        ("img_template/start_fish.png", "start_fish"),
        ("img_template/sell_fish.png", "sell_fish"),
    )
    for template, state in templates:
        matches = detect_once(
            template_path=ScriptPath.get_path(template),
            screenshot_path=screenshot_path,
            threshold=0.82,
        )
        if matches:
            return state

    return "go"

def check_bait_count(window_id: int,
    adb_serial: str,
    *,
    stop_event: threading.Event | None = None,
    log_fn: Callable[[str], None] | None = None,) -> None:
    if _should_stop(stop_event):
        return
    runner = WorkflowRunner(device_serial=adb_serial)
    adb = AdbController(device_serial=adb_serial)
    screenshot_dir = capture_window(
        window_id=window_id,
        fmt="png",
        name="full_screen.png",
        x=0,
        y=0,
        width=1920,
        height=1080,
    )
    matches = detect_once(
        template_path=ScriptPath.get_path("img_template/bait_chosen.png"),
        screenshot_path=screenshot_dir,
        threshold=0.82,
    )
    if matches:
        _log(log_fn, f"当前状态: 检测到鱼饵，开始钓鱼")
        steps = [
            WorkflowStep.tap(POS_READY_TO_START[0], POS_READY_TO_START[1], wait_after=2),
        ]
        runner.run(steps, stop_event=stop_event, log_fn=log_fn)
        return
    else:
        _log(log_fn, f"当前状态: 未检测到鱼饵，开始购买")
        steps = [
            WorkflowStep.tap(POS_BATE_CHOSEN_SHOP[0], POS_BATE_CHOSEN_SHOP[1], wait_after=2),
        ]
        runner.run(steps, stop_event=stop_event, log_fn=log_fn)
        run_extra_step(
            window_id,
            adb_serial,
            stop_event=stop_event,
            log_fn=log_fn,
        )
        steps = [
            WorkflowStep.tap(POS_BATE_CHOSEN[0], POS_BATE_CHOSEN[1], wait_after=2),
        ]
        runner.run(steps, stop_event=stop_event, log_fn=log_fn)


        screenshot_dir = capture_window(
            window_id=window_id,
            fmt="png",
            name="full_screen.png",
            x=0,
            y=0,
            width=1920,
            height=1080,
        )
        matches = detect_once(
            template_path=ScriptPath.get_path("img_template/bait_chose.png"),
            screenshot_path=screenshot_dir,
            threshold=0.82,
        )
        if matches:
            _log(log_fn, f"当前状态: 选择鱼饵")
            first_center = matches[0]["center"]
            steps = [
                WorkflowStep.tap(int(first_center[0]), int(first_center[1]), wait_after=2),
                WorkflowStep.tap(POS_BAIT_INFO_CLOSE[0], POS_BAIT_INFO_CLOSE[1], wait_after=2),
                WorkflowStep.tap(POS_CHANGE_BAIT[0], POS_CHANGE_BAIT[1], wait_after=2),
                WorkflowStep.tap(POS_READY_TO_START[0], POS_READY_TO_START[1], wait_after=2),
            ]
            runner.run(steps, stop_event=stop_event, log_fn=log_fn)
        return



def start_script(
    adb_serial: str,
    *,
    stop_event: threading.Event | None = None,
    log_fn: Callable[[str], None] | None = None,
    preview_fn: Callable[[str], None] | None = None,
) -> None:
    global success_count, failed_count
    success_count = 0
    failed_count = 0    

    go_market = False
    window_id = get_window_id(adb_serial)
    adb = AdbController(device_serial=adb_serial)

    _log(log_fn, f"钓鱼脚本已启动，窗口 ID: {window_id}")

    _notify_preview(preview_fn, window_id, log_fn)

    runner = WorkflowRunner(device_serial=adb_serial)

    while not _should_stop(stop_event):
        if go_market:
            steps = [
                WorkflowStep.tap(POS_MARKET[0], POS_MARKET[1], wait_after=2),
            ]
            runner.run(steps, stop_event=stop_event, log_fn=log_fn)
            go_market = False
            _log(log_fn, f"当前状态: 售卖页面")
            run_sell(adb_serial, stop_event=stop_event)
            if _should_stop(stop_event):
                break
            continue

        state = where_am_i(window_id)

        if _should_stop(stop_event):
            break

        if state == "ready_to_fish":
            _log(log_fn, f"当前状态: 准备钓鱼")
            steps = [
                WorkflowStep.tap(POS_READY_TO_FISH[0], POS_READY_TO_FISH[1], wait_after=2),
            ]
            runner.run(steps, stop_event=stop_event, log_fn=log_fn)
            if _should_stop(stop_event):
                break

        elif state == "bait_shop":
            _log(log_fn, f"当前状态: 商店")
            steps = [
                WorkflowStep.tap(POS_BUY_CLOSE[0], POS_BUY_CLOSE[1], wait_after=2),
            ]
            runner.run(steps, stop_event=stop_event, log_fn=log_fn)
            if _should_stop(stop_event):
                break

        elif state == "start_fish":
            _log(log_fn, f"当前状态: 开始钓鱼")
            check_bait_count(window_id, adb_serial, stop_event=stop_event, log_fn=log_fn)

        elif state == "go":
            _log(log_fn, f"当前状态: 钓鱼抛线界面")

            run_steps_fishing(
                window_id,
                adb_serial,
                stop_event=stop_event,
                log_fn=log_fn,
                preview_fn=preview_fn,
            )

        elif state == "sell_fish":
            _log(log_fn, f"当前状态: 售卖页面")
            steps = [
                WorkflowStep.tap(POS_SELL_CLOSE[0], POS_SELL_CLOSE[1], wait_after=2),
            ]
            runner.run(steps, stop_event=stop_event, log_fn=log_fn)
            if _should_stop(stop_event):
                break

        else:
            if _sleep(2, stop_event) or _should_stop(stop_event):
                break

        if _should_stop(stop_event):
            break

    _log(log_fn, "钓鱼脚本已停止")
