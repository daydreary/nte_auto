#!/usr/bin/env python3
"""
跨平台窗口截图封装。

在 macOS 上委托 screen_utils.mac_screenshot，在 Windows 上委托
screen_utils.windows_screenshot。对外 API 与两个平台模块保持一致。
"""
from __future__ import annotations

import sys
from types import ModuleType
from typing import Any, Optional

_SUPPORTED_PLATFORMS = frozenset({"darwin", "win32"})

_BACKEND: Optional[ModuleType] = None

_EXPORT_NAMES = (
    "WindowInfo",
    "list_windows",
    "find_window_by_name",
    "capture_window",
    "capture_window_region",
    "capture_window_region_by_name",
)

__all__ = (
    *_EXPORT_NAMES,
    "is_supported",
    "platform_label",
    "main",
)


def is_supported() -> bool:
    """当前运行环境是否支持窗口截图。"""
    return sys.platform in _SUPPORTED_PLATFORMS


def platform_label() -> str:
    """返回可读的平台名称（macOS / Windows）。"""
    if sys.platform == "darwin":
        return "macOS"
    if sys.platform == "win32":
        return "Windows"
    raise OSError(
        f"当前系统 ({sys.platform}) 不支持窗口截图，仅支持: macOS、Windows"
    )


def _load_backend() -> ModuleType:
    if sys.platform == "darwin":
        from screen_utils import mac_screenshot

        return mac_screenshot
    if sys.platform == "win32":
        from screen_utils import windows_screenshot

        return windows_screenshot
    raise OSError(
        f"当前系统 ({sys.platform}) 不支持窗口截图，仅支持: macOS、Windows"
    )


def _impl() -> ModuleType:
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = _load_backend()
    return _BACKEND


def __getattr__(name: str) -> Any:
    if name in _EXPORT_NAMES:
        return getattr(_impl(), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def list_windows(*args: Any, **kwargs: Any) -> list[Any]:
    return _impl().list_windows(*args, **kwargs)


def find_window_by_name(*args: Any, **kwargs: Any) -> Any:
    return _impl().find_window_by_name(*args, **kwargs)


def capture_window(*args: Any, **kwargs: Any) -> str:
    return _impl().capture_window(*args, **kwargs)


def capture_window_region(*args: Any, **kwargs: Any) -> str:
    return _impl().capture_window_region(*args, **kwargs)


def capture_window_region_by_name(*args: Any, **kwargs: Any) -> str:
    return _impl().capture_window_region_by_name(*args, **kwargs)


def main() -> None:
    """命令行入口，参数与各平台模块一致。"""
    _impl().main()


if __name__ == "__main__":
    main()
