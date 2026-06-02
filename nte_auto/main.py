#!/usr/bin/env python3
from __future__ import annotations

import threading
from datetime import datetime

import customtkinter as ctk
from PIL import Image

from device_utils.adb_controller import AdbController, AdbDevice
from path_utils import ScriptPath

from module.fish.autofish import start_script
from module.beiguo.autobeiguo import start_beiguo
from module.car_match.autocarmatch import start_car_match

class NteAutoApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("NTE Auto")
        self.geometry("1100x720")
        self.minsize(900, 600)

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self._adb: AdbController | None = None
        self._selected_serial: str | None = None
        self._device_buttons: dict[str, ctk.CTkButton] = {}
        self._device_statuses: dict[str, str] = {}
        self._feature_buttons: dict[str, ctk.CTkButton] = {}
        self._selected_feature: str | None = "钓鱼"
        self._preview_image: ctk.CTkImage | None = None
        self._stop_event = threading.Event()
        self._feature_running = False

        self._build_ui()
        self._init_adb()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=0, minsize=260)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=3)
        self.grid_rowconfigure(1, weight=2)

        self._build_left_panel()
        self._build_image_panel()
        self._build_log_panel()

    def _build_left_panel(self) -> None:
        panel = ctk.CTkFrame(self)
        panel.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(12, 6), pady=12)
        panel.grid_rowconfigure(2, weight=1)
        panel.grid_rowconfigure(5, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(panel, text="ADB Devices", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 6),
        )

        device_toolbar = ctk.CTkFrame(panel, fg_color="transparent")
        device_toolbar.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        device_toolbar.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(device_toolbar, text="刷新", width=70, command=self.refresh_devices).grid(
            row=0, column=0, sticky="w",
        )
        ctk.CTkButton(device_toolbar, text="截图", width=70, command=self.take_screenshot).grid(
            row=0, column=1, sticky="e", padx=(8, 0),
        )

        self._device_list = ctk.CTkScrollableFrame(panel, label_text="")
        self._device_list.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 8))
        self._device_list.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(panel, text="功能列表", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=3, column=0, sticky="w", padx=12, pady=(8, 6),
        )

        feature_toolbar = ctk.CTkFrame(panel, fg_color="transparent")
        feature_toolbar.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 8))
        feature_toolbar.grid_columnconfigure(0, weight=1)
        feature_toolbar.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(feature_toolbar, text="开始", command=self.start_feature).grid(
            row=0, column=0, sticky="ew", padx=(0, 4),
        )
        ctk.CTkButton(feature_toolbar, text="停止", command=self.stop_feature).grid(
            row=0, column=1, sticky="ew", padx=(4, 0),
        )

        self._feature_list = ctk.CTkScrollableFrame(panel, label_text="")
        self._feature_list.grid(row=5, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self._feature_list.grid_columnconfigure(0, weight=1)
        self._build_feature_list()

    def _build_image_panel(self) -> None:
        panel = ctk.CTkFrame(self)
        panel.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=(12, 6))
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(panel, text="图片预览", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 6),
        )

        self._image_label = ctk.CTkLabel(
            panel,
            text="暂无图片",
            fg_color=("gray90", "gray20"),
            corner_radius=8,
        )
        self._image_label.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

    def _build_log_panel(self) -> None:
        panel = ctk.CTkFrame(self)
        panel.grid(row=1, column=1, sticky="nsew", padx=(6, 12), pady=(6, 12))
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(panel, text="日志", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 6),
        )

        self._log_box = ctk.CTkTextbox(panel, state="disabled", wrap="word")
        self._log_box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

    def _init_adb(self) -> None:
        try:
            self._adb = AdbController()
            self.log(f"ADB 已就绪: {self._adb.adb_path}")
            self.refresh_devices()
        except FileNotFoundError as exc:
            self.log(f"错误: {exc}")

    def log(self, message: str) -> None:
        self.after(0, self._append_log, message)

    def show_preview(self, path: str) -> None:
        """线程安全：从后台任务更新图片预览。"""
        self.after(0, self._show_image, path)

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._log_box.configure(state="normal")
        self._log_box.insert("end", f"[{timestamp}] {message}\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def refresh_devices(self) -> None:
        if self._adb is None:
            self.log("ADB 未初始化，无法刷新设备列表")
            return
        self._run_async(self._refresh_devices_task)

    def _refresh_devices_task(self) -> None:
        try:
            devices = self._adb.list_devices()
            self.after(0, self._update_device_list, devices)
            self.log(f"已刷新设备列表，共 {len(devices)} 台")
        except Exception as exc:
            self.log(f"刷新设备失败: {exc}")

    def _update_device_list(self, devices: list[AdbDevice]) -> None:
        for widget in self._device_list.winfo_children():
            widget.destroy()
        self._device_buttons.clear()
        self._device_statuses.clear()

        if not devices:
            ctk.CTkLabel(self._device_list, text="未发现设备").grid(
                row=0, column=0, sticky="ew", pady=4,
            )
            self._selected_serial = None
            return

        online_serials = {d.serial for d in devices if d.status == "device"}
        if self._selected_serial not in online_serials:
            self._selected_serial = next(iter(online_serials), None)

        for index, device in enumerate(devices):
            label = f"{device.serial}\n({device.status})"
            button = ctk.CTkButton(
                self._device_list,
                text=label,
                anchor="w",
                fg_color=self._device_color(device.serial, device.status),
                command=lambda s=device.serial: self._select_device(s),
            )
            button.grid(row=index, column=0, sticky="ew", pady=4)
            self._device_buttons[device.serial] = button
            self._device_statuses[device.serial] = device.status

    def _device_color(self, serial: str, status: str) -> str | tuple[str, str]:
        if serial == self._selected_serial and status == "device":
            return ("#2FA572", "#106A43")
        if status != "device":
            return ("gray70", "gray35")
        return ("gray84", "gray25")

    def _select_device(self, serial: str) -> None:
        status = self._device_statuses.get(serial, "unknown")
        if status != "device":
            self.log(f"设备不可用: {serial} ({status})")
            return
        self._selected_serial = serial
        for device_serial, button in self._device_buttons.items():
            button.configure(
                fg_color=self._device_color(device_serial, self._device_statuses[device_serial]),
            )
        self.log(f"已选择设备: {serial}")

    def _build_feature_list(self) -> None:
        features = ["钓鱼", "呗果", "黑暗赛车界"]
        for index, name in enumerate(features):
            button = ctk.CTkButton(
                self._feature_list,
                text=name,
                anchor="w",
                fg_color=self._feature_color(name),
                command=lambda n=name: self._select_feature(n),
            )
            button.grid(row=index, column=0, sticky="ew", pady=4)
            self._feature_buttons[name] = button

    def _feature_color(self, name: str) -> str | tuple[str, str]:
        if name == self._selected_feature:
            return ("#2FA572", "#106A43")
        return ("gray84", "gray25")

    def _select_feature(self, name: str) -> None:
        self._selected_feature = name
        for feature_name, button in self._feature_buttons.items():
            button.configure(fg_color=self._feature_color(feature_name))
        self.log(f"已选择功能: {name}")

    def start_feature(self) -> None:
        if not self._selected_feature:
            self.log("请先选择功能")
            return
        if not self._selected_serial:
            self.log("请先选择一台在线设备")
            return
        if self._feature_running:
            self.log("功能已在运行中")
            return

        self._run_async(lambda: self._feature_task())

        self._stop_event.clear()
        self._feature_running = True
        self.log(f"开始: {self._selected_feature}")

    def stop_feature(self) -> None:
        if not self._feature_running:
            self.log("当前没有运行中的功能")
            return
        self._stop_event.set()
        self.log("正在停止...")

    def _feature_task(self) -> None:
        serial = self._selected_serial
        feature = self._selected_feature
        try:
            if feature == "钓鱼":
                start_script(
                    serial,
                    stop_event=self._stop_event,
                    log_fn=self.log,
                    preview_fn=self.show_preview,
                )
            elif feature == "呗果":
                start_beiguo(
                    serial,
                    stop_event=self._stop_event,
                    log_fn=self.log,
                    preview_fn=self.show_preview,
                )
            elif feature == "黑暗赛车界":
                start_car_match(
                    serial,
                    stop_event=self._stop_event,
                    log_fn=self.log,
                    preview_fn=self.show_preview,
                )
            else:
                self.log(f"未实现的功能: {feature}")
        except Exception as exc:
            self.log(f"运行出错: {exc}")
        finally:
            self._feature_running = False
            if not self._stop_event.is_set():
                self.log("功能已结束")
            else:
                self.log("功能已停止")

    def take_screenshot(self) -> None:
        if self._adb is None:
            self.log("ADB 未初始化，无法截图")
            return
        if not self._selected_serial:
            self.log("请先选择一台在线设备")
            return
        self._run_async(self._screenshot_task)

    def _screenshot_task(self) -> None:
        try:
            path = self._adb.screenshot(
                ScriptPath.get_path("img_tmp/preview.png"),
                device_serial=self._selected_serial,
            )
            self.after(0, self._show_image, path)
            self.log(f"截图已保存: {path}")
        except Exception as exc:
            self.log(f"截图失败: {exc}")

    def _show_image(self, path: str) -> None:
        try:
            image = Image.open(path)
            max_w = max(self._image_label.winfo_width() - 24, 320)
            max_h = max(self._image_label.winfo_height() - 24, 240)
            image.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
            self._preview_image = ctk.CTkImage(
                light_image=image,
                dark_image=image,
                size=image.size,
            )
            self._image_label.configure(image=self._preview_image, text="")
        except Exception as exc:
            self.log(f"图片加载失败: {exc}")

    def _run_async(self, target) -> None:
        threading.Thread(target=target, daemon=True).start()


def main() -> None:
    app = NteAutoApp()
    app.mainloop()


if __name__ == "__main__":
    main()
