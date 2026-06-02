#!/usr/bin/env python3
"""
根据 ADB serial 解析宿主机模拟器窗口 ID（macOS: CGWindowNumber，Windows: HWND）。
"""
from __future__ import annotations

import re
import shutil
import sys
from typing import Iterable, Optional

from device_utils.subprocess_utils import run as subprocess_run
from screen_utils import screenshot

if not screenshot.is_supported():
    raise ImportError("emulator_window 仅支持 macOS 与 Windows")

_MIN_W = 200
_MIN_H = 120

_EMULATOR_CMD_MARKERS = (
    "emulator",
    "qemu-system",
    "qemu_system",
    "nemu",
    "mumu",
    "dnplayer",
    "nox",
    "hd-player",
    "hdplayer",
    "ldplayer",
    "androidemulator",
)

_EMULATOR_EXE_MARKERS = _EMULATOR_CMD_MARKERS + (
    "qemu-system-x86_64",
    "qemu-system-aarch64",
    "qemu-system-i386",
)


def get_window_id(serial: str, *, adb_path: str | None = None) -> int:
    """
  根据 ADB 设备 serial 返回宿主机模拟器主窗口 ID。

  Args:
      serial: 如 emulator-5554、127.0.0.1:16384。
      adb_path: 可选 adb 可执行文件路径（用于官方模拟器 AVD 名辅助匹配）。

  Returns:
      window_id，可直接传给 screen_utils.screenshot.capture_window。
  """
    serial = serial.strip()
    if not serial:
        raise ValueError("serial 不能为空")

    ports = _parse_adb_ports(serial)
    if not ports:
        raise ValueError(f"无法从 serial 解析端口: {serial!r}")

    avd_name = _get_avd_name(serial, adb_path) if serial.startswith("emulator-") else None

    pids = _find_host_pids(ports)
    for pid in pids:
        window_id = _window_id_for_pid(pid)
        if window_id is not None:
            return window_id

    window_id = _window_id_by_title_hints(ports=ports, avd_name=avd_name)
    if window_id is not None:
        return window_id

    raise RuntimeError(
        f"无法根据 serial={serial!r} 定位模拟器窗口；"
        f"已尝试端口 {ports}，请确认模拟器窗口已打开。"
    )


def _parse_adb_ports(serial: str) -> list[int]:
    if serial.startswith("emulator-"):
        try:
            console_port = int(serial.split("-", 1)[1])
        except ValueError:
            return []
        # emulator-5554：控制台 5554，adb 一般为 5555
        return [console_port, console_port + 1]

    if ":" in serial:
        port_part = serial.rsplit(":", 1)[-1]
        try:
            return [int(port_part)]
        except ValueError:
            return []

    return []


def _get_avd_name(serial: str, adb_path: str | None) -> str | None:
    adb = adb_path or shutil.which("adb")
    if not adb:
        return None
    result = subprocess_run(
        [adb, "-s", serial, "emu", "avd", "name"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    name = result.stdout.strip()
    return name or None


def _find_host_pids(ports: list[int]) -> list[int]:
    found: list[int] = []
    for port in ports:
        found.extend(_pids_listening_on_port(port))
        found.extend(_pids_with_port_in_cmdline(port))

    deduped = list(dict.fromkeys(found))
    filtered = _filter_emulator_pids(deduped)
    return filtered


def _pids_listening_on_port(port: int) -> list[int]:
    if sys.platform == "darwin":
        return _pids_listening_on_port_mac(port)
    if sys.platform == "win32":
        return _pids_listening_on_port_win(port)
    return []


def _pids_listening_on_port_mac(port: int) -> list[int]:
    try:
        result = subprocess_run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []
    pids: list[int] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def _pids_listening_on_port_win(port: int) -> list[int]:
    try:
        result = subprocess_run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []

    needle = f":{port}"
    pids: list[int] = []
    for line in result.stdout.splitlines():
        if needle not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        pid_text = parts[-1]
        if pid_text.isdigit():
            pids.append(int(pid_text))
    return pids


def _pids_with_port_in_cmdline(port: int) -> list[int]:
    port_text = str(port)
    patterns = (
        f"-port {port_text}",
        f"-ports {port},{port + 1}",
        f":{port_text}",
    )

    if sys.platform == "darwin":
        try:
            result = subprocess_run(
                ["ps", "-A", "-o", "pid=,command="],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return []
        if result.returncode != 0:
            return []
        return _match_cmdline_pids(result.stdout.splitlines(), patterns)

    if sys.platform == "win32":
        return _pids_with_port_in_cmdline_win(port_text, patterns)

    return []


def _match_cmdline_pids(lines: Iterable[str], patterns: tuple[str, ...]) -> list[int]:
    pids: list[int] = []
    for line in lines:
        cmd = line.strip()
        if not cmd:
            continue
        if not _looks_like_emulator_cmd(cmd):
            continue
        if not any(p in cmd for p in patterns):
            continue
        head = cmd.split(None, 1)[0]
        if head.isdigit():
            pids.append(int(head))
    return pids


def _pids_with_port_in_cmdline_win(port_text: str, patterns: tuple[str, ...]) -> list[int]:
    try:
        result = subprocess_run(
            [
                "wmic",
                "process",
                "get",
                "ProcessId,CommandLine",
                "/FORMAT:LIST",
            ],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return _pids_with_port_in_cmdline_win_powershell(port_text)

    if result.returncode != 0:
        return _pids_with_port_in_cmdline_win_powershell(port_text)

    pids: list[int] = []
    cmd_parts: list[str] = []
    pid: Optional[int] = None
    for line in result.stdout.splitlines():
        if line.startswith("CommandLine="):
            cmd_parts = [line.split("=", 1)[1]]
        elif line.startswith("ProcessId="):
            value = line.split("=", 1)[1].strip()
            pid = int(value) if value.isdigit() else None
        elif line.strip() == "" and pid is not None:
            cmd = " ".join(cmd_parts)
            if _looks_like_emulator_cmd(cmd) and any(p in cmd for p in patterns):
                pids.append(pid)
            cmd_parts = []
            pid = None
    if pid is not None:
        cmd = " ".join(cmd_parts)
        if _looks_like_emulator_cmd(cmd) and any(p in cmd for p in patterns):
            pids.append(pid)
    return pids


def _pids_with_port_in_cmdline_win_powershell(port_text: str) -> list[int]:
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -and $_.CommandLine -match '"
        + re.escape(port_text)
        + "' } | "
        "Select-Object -ExpandProperty ProcessId"
    )
    try:
        result = subprocess_run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []
    return [int(x) for x in result.stdout.split() if x.strip().isdigit()]


def _looks_like_emulator_cmd(cmd: str) -> bool:
    lower = cmd.lower()
    return any(marker in lower for marker in _EMULATOR_CMD_MARKERS)


def _filter_emulator_pids(pids: list[int]) -> list[int]:
    if not pids:
        return []
    matched = [pid for pid in pids if _is_emulator_process(_process_name(pid))]
    return matched or pids


def _is_emulator_process(name: str) -> bool:
    lower = name.lower()
    return any(marker in lower for marker in _EMULATOR_EXE_MARKERS)


def _process_name(pid: int) -> str:
    if sys.platform == "darwin":
        result = subprocess_run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    if sys.platform == "win32":
        result = subprocess_run(
            [
                "tasklist",
                "/FI",
                f"PID eq {pid}",
                "/FO",
                "CSV",
                "/NH",
            ],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0 or not result.stdout.strip():
            return ""
        line = result.stdout.strip().splitlines()[0]
        # "qemu-system-x86_64.exe","1234",...
        if line.startswith('"'):
            return line.split('"')[1]
        return line.split(",", 1)[0]

    return ""


def _window_id_for_pid(pid: int) -> int | None:
    if sys.platform == "darwin":
        return _mac_window_id_for_pid(pid)
    if sys.platform == "win32":
        return _win_window_id_for_pid(pid)
    return None


def _mac_window_id_for_pid(pid: int) -> int | None:
    from Quartz import CGWindowListCopyWindowInfo, kCGNullWindowID, kCGWindowListOptionAll

    raw_list = CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID) or []
    candidates: list[tuple[bool, int, int]] = []

    for item in raw_list:
        if int(item.get("kCGWindowOwnerPID") or 0) != pid:
            continue
        if int(item.get("kCGWindowLayer") or -1) != 0:
            continue

        bounds = item.get("kCGWindowBounds") or {}
        w = int(bounds.get("Width") or 0)
        h = int(bounds.get("Height") or 0)
        if w < _MIN_W or h < _MIN_H:
            continue

        window_id = int(item.get("kCGWindowNumber") or 0)
        if window_id <= 0:
            continue

        on_screen = bool(item.get("kCGWindowIsOnscreen"))
        candidates.append((on_screen, w * h, window_id))

    return _pick_best_window_id(candidates)


def _win_window_id_for_pid(pid: int) -> int | None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    candidates: list[tuple[bool, int, int]] = []

    def callback(hwnd: wintypes.HWND, _lparam: wintypes.LPARAM) -> bool:
        window_pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
        if int(window_pid.value) != pid:
            return True
        if not user32.IsWindowVisible(hwnd):
            return True

        rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return True
        w = int(rect.right - rect.left)
        h = int(rect.bottom - rect.top)
        if w < _MIN_W or h < _MIN_H:
            return True

        minimized = bool(user32.IsIconic(hwnd))
        on_screen = not minimized
        candidates.append((on_screen, w * h, int(hwnd)))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return _pick_best_window_id(candidates)


def _title_matches_hints(
    title: str,
    owner: str,
    *,
    avd_name: str | None,
    ports: list[int],
) -> bool:
    text = f"{owner} {title}".lower()
    if avd_name and avd_name.lower() in text:
        return True
    if any(marker in text for marker in _EMULATOR_CMD_MARKERS):
        return True
    return any(f":{port}" in text for port in ports)


def _window_id_by_title_hints(*, ports: list[int], avd_name: str | None) -> int | None:
    candidates: list[tuple[bool, int, int]] = []
    for win in screenshot.list_windows(on_screen_only=False, min_w=_MIN_W, min_h=_MIN_H):
        if not _title_matches_hints(win.title, win.owner_name, avd_name=avd_name, ports=ports):
            continue
        candidates.append((win.on_screen, win.area, win.window_id))
    return _pick_best_window_id(candidates)


def _pick_best_window_id(candidates: list[tuple[bool, int, int]]) -> int | None:
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]
