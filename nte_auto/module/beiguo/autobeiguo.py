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
POS_GO = (1700, 1000)
POS_SCROLL_CENTER = (1067, 709)
POS_CLOSE = (1835, 60)
POS_INPUT_COMPLETE = (1695, 1045)
POS_INPUT_SEND = (1747, 969)

POS_BEIGUO_LIST_TYPE = (488, 170)
POS_BEIGUO_LIST_NEW = (458, 329)

# 评论文案池，每次互动随机选一条
AUTO_INPUT_TEXTS: tuple[str, ...] = (
    "哈哈哈，还挺好的",
    "不错不错，支持一下",
    "看着挺好的，已赞",
    "可以可以，继续加油",
    "蛮有意思的，关注了",
    "学到了，感谢分享",
    "真实，说得对",
    "同感，我也是这么想的",
    "厉害厉害，长见识了",
    "有意思，马克一下",
    "支持支持！",
    "挺好的，期待更新",
    "牛啊，这个可以",
    "说得好，顶一个",
    "哈哈哈笑到了",
    "原来如此，受教了",
    "不错诶，可以试试",
    "挺实用的，收藏了",
    "有道理，记下了",
    "赞，继续保持",
    "看着不错，冲了",
    "可以，已点赞",
    "好活，多更点",
    "针不戳，爱了",
    "稳的，没毛病",
)


def _pick_input_text() -> str:
    return random.choice(AUTO_INPUT_TEXTS)


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
    preview_fn: Callable[[str], None] | None,
    window_id: int,
    log_fn: Callable[[str], None] | None,
    path: str | None = None,
) -> None:
    if preview_fn is None:
        return
    try:
        if (path is None):
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

def where_am_i(adb: AdbController, preview_fn: Callable[[str], None] | None, window_id: int, log_fn: Callable[[str], None] | None) -> str | None:
    screenshot_where = _take_screenshot(adb)
    _notify_preview(preview_fn, window_id, log_fn, screenshot_where)
    checks = (
        ("send.png", "send"),
        ("beiguo.png", "beiguo"),
        ("entry_list.png", "entry_list"),
        ("input.png", "input"),
        ("submit.png", "submit"),
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


def go_to_new_page(
    runner: WorkflowRunner,
    *,
    stop_event: threading.Event | None = None,
    log_fn: Callable[[str], None] | None = None,
    adb_serial: str,
) -> bool:
    steps = [
        WorkflowStep.tap(POS_BEIGUO_LIST_TYPE[0], POS_BEIGUO_LIST_TYPE[1], wait_after=2),
        WorkflowStep.tap(POS_BEIGUO_LIST_NEW[0], POS_BEIGUO_LIST_NEW[1], wait_after=2),
    ]
    return not runner.run(steps, stop_event=stop_event, log_fn=log_fn)


def do_auto_work(
    adb: AdbController,
    runner: WorkflowRunner,
    *,
    stop_event: threading.Event | None = None,
    log_fn: Callable[[str], None] | None = None,
    adb_serial: str,
) -> bool:
    """执行一轮列表互动，返回 True 表示应停止主循环。"""
    if _should_stop(stop_event):
        return True
    
    find_item = _take_screenshot(adb)
    items = detect_once(
        template_path=_template_path("like.png"),
        screenshot_path=find_item,
        threshold=0.82,
        result_count=4,
    )
    if items:
        for item in items:
            if _should_stop(stop_event):
                return True
            point_center = item["center"]
            _log(
                log_fn,
                f"找到列表 item 位置 {point_center[0]}, {point_center[1]}",
            )
            steps = [
                WorkflowStep.tap(point_center[0], point_center[1], wait_after=2),
            ]
            runner.run(steps, stop_event=stop_event, log_fn=log_fn)
        

            do_action = _take_screenshot(adb)
            do_like = detect_once(
                template_path=_template_path("click_like.png"),
                screenshot_path=do_action,
                threshold=0.82,
            )
            do_collect = detect_once(
                template_path=_template_path("collect.png"),
                screenshot_path=do_action,
                threshold=0.82,
            )
            do_input = detect_once(
                template_path=_template_path("input.png"),
                screenshot_path=do_action,
                threshold=0.82,
            )
            if do_like:
                center = do_like[0]["center"]
                _log(log_fn, f"找到点赞位置 {center[0]}, {center[1]}")
                steps = [
                    WorkflowStep.long_press(center[0], center[1], wait_after=2),
                ]
                runner.run(steps, stop_event=stop_event, log_fn=log_fn)
                
            if do_collect:
                center = do_collect[0]["center"]
                _log(log_fn, f"找到收藏位置 {center[0]}, {center[1]}")
                steps = [
                    WorkflowStep.long_press(center[0], center[1], wait_after=2),
                ]
                runner.run(steps, stop_event=stop_event, log_fn=log_fn)
                
            if do_input:
                center = do_input[0]["center"]
                _log(log_fn, f"找到输入位置 {center[0]}, {center[1]}")
                comment = _pick_input_text()
                _log(log_fn, f"本次评论文案: {comment}")

                steps = [
                    WorkflowStep.long_press(center[0], center[1], wait_after=2),
                    WorkflowStep.input_text(comment, wait_after=2),
                    WorkflowStep.tap(POS_INPUT_COMPLETE[0], POS_INPUT_COMPLETE[1], wait_after=2),
                    WorkflowStep.tap(POS_INPUT_SEND[0], POS_INPUT_SEND[1], wait_after=2),
                ]
                runner.run(steps, stop_event=stop_event, log_fn=log_fn)
                

            steps = [
                WorkflowStep.long_press(POS_CLOSE[0], POS_CLOSE[1], wait_after=2),
            ]
            runner.run(steps, stop_event=stop_event, log_fn=log_fn)

    steps = [
        WorkflowStep.swipe(POS_SCROLL_CENTER[0], POS_SCROLL_CENTER[1], POS_SCROLL_CENTER[0], POS_SCROLL_CENTER[1] + 400, wait_after=2),
    ]
    return not runner.run(steps, stop_event=stop_event, log_fn=log_fn)


def go_to_send(
    runner: WorkflowRunner,
    *,
    stop_event: threading.Event | None = None,
    log_fn: Callable[[str], None] | None = None,
    adb_serial: str,
) -> bool:
    steps = [
        WorkflowStep.tap(POS_GO[0], POS_GO[1], wait_after=2),
    ]
    return not runner.run(steps, stop_event=stop_event, log_fn=log_fn)


def go_to_beiguo(
    adb: AdbController,
    runner: WorkflowRunner,
    *,
    stop_event: threading.Event | None = None,
    log_fn: Callable[[str], None] | None = None,
    adb_serial: str,
) -> bool:
    while not _should_stop(stop_event):
        screenshot_entry_list = _take_screenshot(adb)
        matches = detect_once(
            template_path=_template_path("entry_list.png"),
            screenshot_path=screenshot_entry_list,
            threshold=0.82,
            result_count=1,
        )
        if matches:
            steps = [
                WorkflowStep.long_press(matches[0]["center"][0], matches[0]["center"][1], wait_after=2),
            ]
            return not runner.run(steps, stop_event=stop_event, log_fn=log_fn)
        
        steps = [
            WorkflowStep.swipe(POS_ENTRY_SCROLL[0], POS_ENTRY_SCROLL[1], POS_ENTRY_SCROLL[0], POS_ENTRY_SCROLL[1] + 400, wait_after=2),
        ]
        return not runner.run(steps, stop_event=stop_event, log_fn=log_fn)
    return True


def go_to_entry_list(
    runner: WorkflowRunner,
    *,
    stop_event: threading.Event | None = None,
    log_fn: Callable[[str], None] | None = None,
    adb_serial: str,
) -> bool:
    steps = [
        WorkflowStep.tap(POS_ENTRY[0], POS_ENTRY[1], wait_after=2),
    ]
    return not runner.run(steps, stop_event=stop_event, log_fn=log_fn)
    


def back_to_send(
    runner: WorkflowRunner,
    *,
    stop_event: threading.Event | None = None,
    log_fn: Callable[[str], None] | None = None,
    adb_serial: str,
) -> bool:
    steps = [
        WorkflowStep.long_press(POS_CLOSE[0], POS_CLOSE[1], wait_after=2),
    ]
    return not runner.run(steps, stop_event=stop_event, log_fn=log_fn)


def start_beiguo(
    adb_serial: str,
    *,
    stop_event: threading.Event | None = None,
    log_fn: Callable[[str], None] | None = None,
    preview_fn: Callable[[str], None] | None = None,
) -> None:
    """呗果自动留言主循环。"""
    adb = AdbController(device_serial=adb_serial)
    runner = WorkflowRunner(device_serial=adb_serial)
    new_list = False

    _log(log_fn, f"呗果脚本已启动，设备: {adb_serial}")
    window_id = get_window_id(adb_serial)   

    while not _should_stop(stop_event):
        where = where_am_i(adb, preview_fn, window_id, log_fn)

        if where == "send":
            _log(log_fn, f"当前所在页面: 发布列表")
            if not new_list:
                if go_to_new_page(runner, stop_event=stop_event, log_fn=log_fn, adb_serial=adb_serial):
                    break
                new_list = True
            if do_auto_work(adb, runner, stop_event=stop_event, log_fn=log_fn, adb_serial=adb_serial):
                break
        elif where == "beiguo":
            _log(log_fn, f"当前所在页面: 呗果活动")
            new_list = False
            if go_to_send(runner, stop_event=stop_event, log_fn=log_fn, adb_serial=adb_serial):
                break
        elif where == "entry_list":
            _log(log_fn, f"当前所在页面: 活动列表")
            new_list = False
            if go_to_beiguo(adb,runner, stop_event=stop_event, log_fn=log_fn, adb_serial=adb_serial):
                break
        elif where in ("input", "submit"):
            _log(log_fn, f"当前所在页面: 输入内容")
            new_list = False
            if back_to_send(runner, stop_event=stop_event, log_fn=log_fn, adb_serial=adb_serial):
                break
        else:
            new_list = False
            if go_to_entry_list(runner, stop_event=stop_event, log_fn=log_fn, adb_serial=adb_serial):
                break

        if _should_stop(stop_event):
            break

    _log(log_fn, "呗果脚本已停止")
