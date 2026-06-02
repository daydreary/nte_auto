#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from typing import Any


def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    """subprocess.run 封装，Windows GUI 下隐藏子进程控制台窗口。"""
    if sys.platform == "win32":
        flags = kwargs.pop("creationflags", 0)
        kwargs["creationflags"] = flags | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(*args, **kwargs)
