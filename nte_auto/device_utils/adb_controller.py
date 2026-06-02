#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
import os
from dataclasses import dataclass
from pathlib import Path
from path_utils import ScriptPath


@dataclass(frozen=True)
class AdbDevice:
    serial: str
    status: str


class AdbController:
    """通过 ADB 控制 Android 设备。"""

    def __init__(
        self,
        adb_path: str | Path | None = None,
        device_serial: str | None = None,
    ) -> None:
        if adb_path is not None:
            resolved = Path(adb_path).expanduser().resolve()
            if not resolved.is_file():
                raise FileNotFoundError(f"ADB 可执行文件不存在: {resolved}")
            self._adb_path = str(resolved)
        else:
            found = shutil.which("adb")
            if found is not None:
                self._adb_path = found
            else:
                self._adb_path = str(self._resolve_bundled_adb())
        self._device_serial = device_serial

    @staticmethod
    def _resolve_bundled_adb() -> Path:
        """返回内置 ADB 可执行文件路径（platform-tools 目录）。"""
        base = ScriptPath.get_script_dir()
        if sys.platform == "darwin":
            bundled = base / "platform-tools-mac" / "adb"
        elif sys.platform == "win32":
            bundled = base / "platform-tools" / "adb.exe"
        else:
            raise FileNotFoundError(
                f"当前系统 ({sys.platform}) 不支持内置 ADB，请通过 adb_path 指定路径"
            )
        if not bundled.is_file():
            raise FileNotFoundError(
                f"未在 PATH 中找到 adb，且内置 ADB 不存在: {bundled}"
            )
        return bundled

    @property
    def adb_path(self) -> str:
        return self._adb_path

    @property
    def device_serial(self) -> str | None:
        return self._device_serial

    def list_devices(self) -> list[AdbDevice]:
        """检测 adb devices 中所有设备。"""
        result = self._run("devices", global_cmd=True)
        devices: list[AdbDevice] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                devices.append(AdbDevice(serial=parts[0], status=parts[1]))
        return devices

    def tap(
        self,
        x: int,
        y: int,
        *,
        device_serial: str | None = None,
    ) -> None:
        """点击指定坐标。"""
        self._shell("input", "tap", str(x), str(y), device_serial=device_serial)

    def long_press(
        self,
        x: int,
        y: int,
        duration_ms: int = 1000,
        *,
        device_serial: str | None = None,
    ) -> None:
        """长按指定坐标。"""
        duration = str(duration_ms)
        coord = str(x), str(y)
        self._shell(
            "input", "swipe", *coord, *coord, duration,
            device_serial=device_serial,
        )

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
        *,
        device_serial: str | None = None,
    ) -> None:
        """从 (x1, y1) 滑动到 (x2, y2)。"""
        self._shell(
            "input", "swipe",
            str(x1), str(y1), str(x2), str(y2), str(duration_ms),
            device_serial=device_serial,
        )

    def screenshot(
        self,
        filename: str,
        *,
        device_serial: str | None = None,
    ) -> Path:
        """截图并保存到当前脚本目录，文件名为 filename。"""
        output_path = ScriptPath.get_path(filename)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = self._adb_cmd("exec-out", "screencap", "-p", device_serial=device_serial)
        result = subprocess.run(cmd, capture_output=True, check=False)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ADB 截图失败: {stderr or result.returncode}")
        if not result.stdout:
            raise RuntimeError("ADB 截图失败: 未返回图片数据")
        output_path.write_bytes(result.stdout)
        return output_path

    @staticmethod
    def escape_adb_input_text(text: str) -> str:
        """为 adb shell input text 转义特殊字符。"""
        mapping = {
            " ": "%s",
            "%": "%%",
            "&": "\\&",
            "<": "\\<",
            ">": "\\>",
            "|": "\\|",
            "(": "\\(",
            ")": "\\)",
            ";": "\\;",
            "*": "\\*",
            "`": "\\`",
            "\\": "\\\\",
            '"': '\\"',
            "'": "\\'",
            "$": "\\$",
        }
        return "".join(mapping.get(ch, ch) for ch in text)

    def clear_input_text(
        self,
        max_chars: int = 200,
        *,
        device_serial: str | None = None,
    ) -> None:
        """清空当前聚焦输入框中的已有内容。"""
        deletes = "; ".join(["input keyevent 67"] * max_chars)
        self._run(
            "shell",
            f"input keyevent 123; {deletes}",
            device_serial=device_serial,
        )

    def input_text(
        self,
        text: str,
        *,
        device_serial: str | None = None,
    ) -> None:
        """
        假设输入框已弹起并聚焦，通过 adb 输入文本。
        若输入框内已有内容，会先清空再输入。
        """
        self.clear_input_text(device_serial=device_serial)
        escaped = self.escape_adb_input_text(text)
        shell_safe = escaped.replace("'", "'\\''")
        self._run(
            "shell",
            f"input text '{shell_safe}'",
            device_serial=device_serial,
        )

    def _shell(
        self,
        *args: str,
        device_serial: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return self._run("shell", *args, device_serial=device_serial)

    def _adb_cmd(
        self,
        *args: str,
        device_serial: str | None = None,
        global_cmd: bool = False,
    ) -> list[str]:
        cmd = [self._adb_path]
        if not global_cmd:
            serial = self._resolve_device_serial(device_serial)
            if serial:
                cmd.extend(["-s", serial])
        cmd.extend(args)
        return cmd

    def _resolve_device_serial(self, device_serial: str | None) -> str | None:
        serial = device_serial or self._device_serial
        if serial:
            return serial
        online = [d for d in self.list_devices() if d.status == "device"]
        if len(online) == 1:
            return online[0].serial
        if not online:
            raise RuntimeError("没有可用的 ADB 设备")
        serials = ", ".join(d.serial for d in online)
        raise RuntimeError(f"连接了多个设备，请指定 device_serial: {serials}")

    def _run(
        self,
        *args: str,
        device_serial: str | None = None,
        global_cmd: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        cmd = self._adb_cmd(*args, device_serial=device_serial, global_cmd=global_cmd)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            detail = stderr or stdout or str(result.returncode)
            raise RuntimeError(f"ADB 命令失败: {' '.join(cmd)}\n{detail}")
        return result
