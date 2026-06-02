#!/usr/bin/env python3
from __future__ import annotations

import inspect
import sys
from pathlib import Path


class ScriptPath:
    """解析相对于当前脚本目录的路径，兼容 PyInstaller 打包。"""

    @classmethod
    def get_script_dir(cls) -> Path:
        """返回当前脚本所在目录。

        - 开发环境：通过调用栈定位调用方 .py 文件所在目录
        - PyInstaller 打包后：使用 ``sys._MEIPASS``（资源解压目录）
        """
        if getattr(sys, "frozen", False):
            return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        return cls._dev_script_dir()

    @classmethod
    def get_path(cls, filename: str) -> Path:
        """返回「当前脚本目录 / filename」的完整路径。

        Args:
            filename: 文件名或相对路径，例如 ``"a.txt"`` 或 ``"data/a.txt"``。

        Returns:
            拼接后的绝对路径。
        """
        return cls.get_script_dir() / filename

    @staticmethod
    def _dev_script_dir() -> Path:
        """开发环境下，跳过 path_utils 内部帧，定位调用方脚本目录。"""
        pkg_name = __name__.split(".")[0]
        for frame_info in inspect.stack()[1:]:
            module = inspect.getmodule(frame_info.frame)
            if module is not None and module.__name__.startswith(pkg_name):
                continue
            filepath = frame_info.filename
            if filepath.endswith(".py"):
                return Path(filepath).resolve().parent
        return Path(__file__).resolve().parent
