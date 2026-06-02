#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from path_utils import ScriptPath

from PIL import Image

if sys.platform != "win32":
    raise ImportError("windows_screenshot 仅支持 Windows 系统")

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_APPWINDOW = 0x00040000

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DIB_RGB_COLORS = 0
BI_RGB = 0


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]

    @property
    def width(self) -> int:
        return int(self.right - self.left)

    @property
    def height(self) -> int:
        return int(self.bottom - self.top)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = wintypes.LONG
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.GetWindowDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.LPVOID,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL


@dataclass(frozen=True)
class WindowInfo:
    window_id: int
    owner_name: str
    title: str
    x: int
    y: int
    w: int
    h: int
    layer: int
    alpha: float
    on_screen: bool

    @property
    def area(self) -> int:
        return self.w * self.h

    @property
    def display_name(self) -> str:
        if self.title:
            return f"{self.owner_name} - {self.title}"
        return self.owner_name


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _hwnd_to_int(hwnd: wintypes.HWND) -> int:
    return _as_int(int(hwnd or 0))


def _get_window_title(hwnd: wintypes.HWND) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value.strip()


def _get_process_name(pid: int) -> str:
    if pid <= 0:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(260)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _is_tool_window(hwnd: wintypes.HWND) -> bool:
    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if ex_style == 0:
        return False
    return bool(ex_style & WS_EX_TOOLWINDOW) and not bool(ex_style & WS_EX_APPWINDOW)


def _should_skip_window(hwnd: wintypes.HWND, min_w: int, min_h: int) -> bool:
    if not user32.IsWindow(hwnd):
        return True
    if _is_tool_window(hwnd):
        return True

    rect = RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return True
    w, h = rect.width, rect.height
    if w < min_w or h < min_h:
        return True

    owner_name = _get_process_name(_get_window_pid(hwnd))
    if not owner_name:
        return True
    if owner_name.lower() in ("dwm.exe", "applicationframehost.exe"):
        return True

    return False


def _get_window_pid(hwnd: wintypes.HWND) -> int:
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _build_window_info(hwnd: wintypes.HWND) -> WindowInfo:
    outer = RECT()
    client = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(outer))
    user32.GetClientRect(hwnd, ctypes.byref(client))

    visible = bool(user32.IsWindowVisible(hwnd))
    minimized = bool(user32.IsIconic(hwnd))
    on_screen = visible and not minimized

    pid = _get_window_pid(hwnd)
    owner_name = _get_process_name(pid)
    title = _get_window_title(hwnd)

    return WindowInfo(
        window_id=_hwnd_to_int(hwnd),
        owner_name=owner_name,
        title=title,
        x=int(outer.left),
        y=int(outer.top),
        w=client.width,
        h=client.height,
        layer=0,
        alpha=1.0 if visible else 0.0,
        on_screen=on_screen,
    )


def _iter_windows(on_screen_only: bool, min_w: int, min_h: int) -> Iterable[WindowInfo]:
    collected: list[WindowInfo] = []

    def callback(hwnd: wintypes.HWND, _lparam: wintypes.LPARAM) -> bool:
        if _should_skip_window(hwnd, min_w=min_w, min_h=min_h):
            return True

        info = _build_window_info(hwnd)
        if on_screen_only and not info.on_screen:
            return True
        if info.alpha <= 0:
            return True

        collected.append(info)
        return True

    if not user32.EnumWindows(WNDENUMPROC(callback), 0):
        raise ctypes.WinError(ctypes.get_last_error())

    yield from collected


def list_windows(on_screen_only: bool = False, min_w: int = 200, min_h: int = 120) -> list[WindowInfo]:
    windows = list(_iter_windows(on_screen_only=on_screen_only, min_w=min_w, min_h=min_h))
    windows.sort(key=lambda w: (w.on_screen, w.area), reverse=True)
    return windows


def _print_windows(windows: list[WindowInfo], max_items: int) -> None:
    print("Idx  WindowID  OnScreen  Size        Position      Name")
    print("-" * 78)
    for idx, win in enumerate(windows[:max_items]):
        on_screen = "Y" if win.on_screen else "N"
        size = f"{win.w}x{win.h}"
        pos = f"({win.x},{win.y})"
        print(f"{idx:>3}  {win.window_id:>8}  {on_screen:>8}  {size:<10}  {pos:<12}  {win.display_name}")


def _pick_window_interactive(windows: list[WindowInfo], max_items: int) -> WindowInfo:
    if not windows:
        raise RuntimeError("未找到可截图窗口。请确认目标窗口已打开。")

    _print_windows(windows, max_items=max_items)
    prompt = f"\n请输入序号(0-{min(len(windows), max_items)-1})，或直接输入 WindowID: "
    user_input = input(prompt).strip()
    if not user_input:
        raise RuntimeError("未输入任何内容，已取消。")

    value = int(user_input)
    if 0 <= value < min(len(windows), max_items):
        return windows[value]

    by_id = {w.window_id: w for w in windows}
    if value in by_id:
        return by_id[value]
    raise RuntimeError(f"输入无效: {value}")


def find_window_by_name(
    name_keyword: str,
    on_screen_only: bool = False,
    min_w: int = 200,
    min_h: int = 120,
) -> WindowInfo:
    """
    Find the best-matched window by substring match on display name.

    Matching rule:
    - Use case-insensitive "contains" check.
    - Pick the first match from sorted list (on-screen first, then larger area).
    """
    keyword = name_keyword.strip().lower()
    if not keyword:
        raise ValueError("window_name 不能为空")

    windows = list_windows(on_screen_only=on_screen_only, min_w=min_w, min_h=min_h)
    matches = [w for w in windows if keyword in w.display_name.lower()]
    if not matches:
        raise RuntimeError(f"未找到包含名称 '{name_keyword}' 的窗口")
    return matches[0]


def _bitmap_to_pil(hdc: wintypes.HDC, bitmap: wintypes.HBITMAP, width: int, height: int) -> Image.Image:
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB

    buffer_size = width * height * 4
    buffer = (ctypes.c_ubyte * buffer_size)()
    lines = gdi32.GetDIBits(
        hdc,
        bitmap,
        0,
        height,
        ctypes.byref(buffer),
        ctypes.byref(bmi),
        DIB_RGB_COLORS,
    )
    if lines == 0:
        raise RuntimeError(f"读取位图失败: WinError {ctypes.get_last_error()}")

    image = Image.frombuffer("RGBA", (width, height), bytes(buffer), "raw", "BGRA", 0, 1)
    return image.copy()


def _hwnd_to_pil(hwnd: int) -> Image.Image:
    hwnd_handle = wintypes.HWND(hwnd)
    if not user32.IsWindow(hwnd_handle):
        raise RuntimeError(f"窗口不存在: WindowID={hwnd}")

    client = RECT()
    if not user32.GetClientRect(hwnd_handle, ctypes.byref(client)):
        raise RuntimeError("无法获取窗口客户区大小")
    width, height = client.width, client.height
    if width <= 0 or height <= 0:
        raise RuntimeError("窗口客户区无效")

    hwnd_dc = user32.GetWindowDC(hwnd_handle)
    if not hwnd_dc:
        raise RuntimeError("GetWindowDC 失败")

    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    if not mem_dc:
        user32.ReleaseDC(hwnd_handle, hwnd_dc)
        raise RuntimeError("CreateCompatibleDC 失败")

    bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    if not bitmap:
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd_handle, hwnd_dc)
        raise RuntimeError("CreateCompatibleBitmap 失败")

    old_obj = gdi32.SelectObject(mem_dc, bitmap)
    try:
        flags = PW_RENDERFULLCONTENT | PW_CLIENTONLY
        ok = user32.PrintWindow(hwnd_handle, mem_dc, flags)
        if not ok:
            raise RuntimeError(
                "截图失败：PrintWindow 未成功。窗口可能已关闭、受保护，或该应用不支持后台截图。"
            )
        return _bitmap_to_pil(mem_dc, bitmap, width, height)
    finally:
        gdi32.SelectObject(mem_dc, old_obj)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd_handle, hwnd_dc)


def _crop_window_region(
    img: Image.Image, x: Optional[int], y: Optional[int], w: Optional[int], h: Optional[int]
) -> Image.Image:
    if x is None and y is None and w is None and h is None:
        return img

    if None in (x, y, w, h):
        raise ValueError("使用窗口内局部截图时，必须同时提供 x/y/width/height")
    assert x is not None and y is not None and w is not None and h is not None

    if x < 0 or y < 0:
        raise ValueError("x 和 y 必须 >= 0（相对窗口左上角）")
    if w <= 0 or h <= 0:
        raise ValueError("width 和 height 必须 > 0")

    img_w, img_h = img.size
    if x >= img_w or y >= img_h:
        raise ValueError(f"起点超出窗口范围：x={x}, y={y}, 窗口大小={img_w}x{img_h}")

    crop_right = min(img_w, x + w)
    crop_bottom = min(img_h, y + h)
    if crop_right <= x or crop_bottom <= y:
        raise ValueError("局部截图区域无效，请检查 x/y/width/height")

    return img.crop((x, y, crop_right, crop_bottom))


def capture_window_region(
    window_id: int,
    x: int,
    y: int,
    width: int,
    height: int,
    fmt: str = "png",
    name: str | None = None,
) -> str:
    """
    Capture a region inside a window and save image to script directory.

    Args:
        window_id: Windows HWND (window handle).
        x: Region start x in window coordinates (top-left origin).
        y: Region start y in window coordinates (top-left origin).
        width: Region width.
        height: Region height.
        fmt: Output format, "png" or "jpg".
        name: Optional output filename.

    Returns:
        Absolute path of the saved screenshot.
    """
    return capture_window(
        window_id=window_id,
        fmt=fmt,
        name=name,
        x=x,
        y=y,
        width=width,
        height=height,
    )


def capture_window_region_by_name(
    window_name: str,
    x: int,
    y: int,
    width: int,
    height: int,
    fmt: str = "png",
    name: str | None = None,
    on_screen_only: bool = False,
    min_w: int = 200,
    min_h: int = 120,
) -> str:
    """
    Capture a region by window name keyword.
    """
    win = find_window_by_name(
        name_keyword=window_name,
        on_screen_only=on_screen_only,
        min_w=min_w,
        min_h=min_h,
    )
    return capture_window_region(
        window_id=win.window_id,
        x=x,
        y=y,
        width=width,
        height=height,
        fmt=fmt,
        name=name,
    )


def capture_window(
    window_id: int,
    fmt: str = "png",
    name: str | None = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> str:
    if fmt not in ("png", "jpg"):
        raise ValueError("fmt 必须是 'png' 或 'jpg'")

    img = _hwnd_to_pil(window_id)
    img = _crop_window_region(img, x=x, y=y, w=width, h=height)

    script_dir = ScriptPath.get_script_dir()
    ts = time.strftime("%Y%m%d_%H%M%S")
    ext = "jpg" if fmt == "jpg" else "png"
    filename = name or f"window_{window_id}_{ts}.{ext}"
    out_path = script_dir / "img_tmp" / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "png":
        img.save(out_path, format="PNG", compress_level=1)
    else:
        img.convert("RGB").save(
            out_path, format="JPEG", quality=90, optimize=False, subsampling=0
        )

    return str(out_path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="在 Windows 上按窗口截图（支持交互选择，尽量可截被遮挡窗口）"
    )
    parser.add_argument("--window-id", type=int, default=None, help="直接指定 WindowID (HWND)")
    parser.add_argument(
        "--window-name",
        type=str,
        default=None,
        help="按窗口名称关键字匹配（Name 包含匹配，不区分大小写）",
    )
    parser.add_argument("--list", action="store_true", help="仅列出可选窗口，不截图")
    parser.add_argument(
        "--on-screen-only",
        action="store_true",
        help="仅列出当前可见窗口（默认会列出更多窗口）",
    )
    parser.add_argument("--max-items", type=int, default=30, help="展示候选窗口数量上限")
    parser.add_argument("--min-w", type=int, default=200, help="候选窗口最小宽度")
    parser.add_argument("--min-h", type=int, default=120, help="候选窗口最小高度")
    parser.add_argument("--fmt", choices=("png", "jpg"), default="png", help="输出图片格式")
    parser.add_argument("--name", default=None, help="输出文件名")
    parser.add_argument("--x", type=int, default=None, help="窗口内起点 x（左上角为 0,0）")
    parser.add_argument("--y", type=int, default=None, help="窗口内起点 y（左上角为 0,0）")
    parser.add_argument("--width", type=int, default=None, help="窗口内截图宽度")
    parser.add_argument("--height", type=int, default=None, help="窗口内截图高度")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    windows = list_windows(
        on_screen_only=args.on_screen_only, min_w=args.min_w, min_h=args.min_h
    )

    if args.list:
        _print_windows(windows, max_items=args.max_items)
        return

    selected: WindowInfo
    if args.window_id is not None:
        by_id = {w.window_id: w for w in windows}
        if args.window_id not in by_id:
            raise RuntimeError(
                f"WindowID={args.window_id} 不在候选列表中，请先运行 --list 查看。"
            )
        selected = by_id[args.window_id]
    elif args.window_name:
        selected = find_window_by_name(
            name_keyword=args.window_name,
            on_screen_only=args.on_screen_only,
            min_w=args.min_w,
            min_h=args.min_h,
        )
    else:
        selected = _pick_window_interactive(windows, max_items=args.max_items)

    t0 = time.perf_counter()
    out_path = capture_window(
        window_id=selected.window_id,
        fmt=args.fmt,
        name=args.name,
        x=args.x,
        y=args.y,
        width=args.width,
        height=args.height,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    print(out_path)
    print(f"capture_elapsed_ms={elapsed_ms:.2f}")


if __name__ == "__main__":
    main()
