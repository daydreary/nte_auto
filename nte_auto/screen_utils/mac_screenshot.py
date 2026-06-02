#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from path_utils import ScriptPath

from PIL import Image
from Quartz import (
    CGDataProviderCopyData,
    CGImageGetBitsPerPixel,
    CGImageGetBytesPerRow,
    CGImageGetDataProvider,
    CGImageGetHeight,
    CGImageGetWidth,
    CGWindowListCopyWindowInfo,
    CGWindowListCreateImage,
    CGRectNull,
    kCGNullWindowID,
    kCGWindowImageBoundsIgnoreFraming,
    kCGWindowImageBestResolution,
    kCGWindowListOptionAll,
    kCGWindowListOptionIncludingWindow,
    kCGWindowListOptionOnScreenOnly,
)


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


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    return default


def _iter_windows(on_screen_only: bool, min_w: int, min_h: int) -> Iterable[WindowInfo]:
    option = kCGWindowListOptionOnScreenOnly if on_screen_only else kCGWindowListOptionAll
    raw_list = CGWindowListCopyWindowInfo(option, kCGNullWindowID) or []

    for item in raw_list:
        bounds = item.get("kCGWindowBounds", {})
        w = _as_int(bounds.get("Width"))
        h = _as_int(bounds.get("Height"))
        if w < min_w or h < min_h:
            continue

        owner_name = str(item.get("kCGWindowOwnerName") or "").strip()
        if not owner_name or owner_name == "Window Server":
            continue

        layer = _as_int(item.get("kCGWindowLayer"))
        if layer != 0:
            continue

        alpha = _as_float(item.get("kCGWindowAlpha"), 1.0)
        if alpha <= 0:
            continue

        yield WindowInfo(
            window_id=_as_int(item.get("kCGWindowNumber")),
            owner_name=owner_name,
            title=str(item.get("kCGWindowName") or "").strip(),
            x=_as_int(bounds.get("X")),
            y=_as_int(bounds.get("Y")),
            w=w,
            h=h,
            layer=layer,
            alpha=alpha,
            on_screen=_as_bool(item.get("kCGWindowIsOnscreen")),
        )


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
        raise RuntimeError("未找到可截图窗口。请确认目标窗口已打开，并已授予屏幕录制权限。")

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


def _cgimage_to_pil(img_ref: Any) -> Image.Image:
    width = int(CGImageGetWidth(img_ref))
    height = int(CGImageGetHeight(img_ref))
    bpp = int(CGImageGetBitsPerPixel(img_ref))
    bpr = int(CGImageGetBytesPerRow(img_ref))

    if bpp != 32:
        raise RuntimeError(f"不支持的像素格式: {bpp} bpp")

    provider = CGImageGetDataProvider(img_ref)
    data = bytes(CGDataProviderCopyData(provider))
    # macOS 窗口图通常是 BGRA(8-bit/channel)；使用 bytes_per_row 处理行对齐。
    image = Image.frombuffer("RGBA", (width, height), data, "raw", "BGRA", bpr, 1)
    return image.copy()


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
        raise ValueError(
            f"起点超出窗口范围：x={x}, y={y}, 窗口大小={img_w}x{img_h}"
        )

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
        window_id: macOS window id.
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

    image_ref = CGWindowListCreateImage(
        CGRectNull,
        kCGWindowListOptionIncludingWindow,
        window_id,
        kCGWindowImageBoundsIgnoreFraming | kCGWindowImageBestResolution,
    )
    if image_ref is None:
        raise RuntimeError(
            "截图失败：窗口不存在、无权限，或窗口内容受系统保护。请检查屏幕录制权限。"
        )

    img = _cgimage_to_pil(image_ref)
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
        description="在 macOS 上按窗口截图（支持交互选择，尽量可截被遮挡窗口）"
    )
    parser.add_argument("--window-id", type=int, default=None, help="直接指定 WindowID")
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
