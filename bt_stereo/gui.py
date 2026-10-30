# -*- coding: utf-8 -*-
"""图形界面：给不熟悉命令行的使用场景。"""
from __future__ import annotations

import json
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .engine import EngineConfig, StereoEngine
from .wasapi import DEVICE_STATE_ACTIVE, Device, default_device, list_devices, set_default_device

SETTINGS = Path(__file__).resolve().parent.parent / "settings.json"
MODES = {
    "左右分离（左音箱放左声道，右音箱放右声道）": "lr",
    "两边都放完整立体声（相当于双份外放）": "duplicate",
    "左右互换": "swap",
}


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("双音箱 · 左右声道拆分器")
        self.geometry("880x470")
        self.minsize(760, 480)
        self.configure(padx=14, pady=12)

        self.engine: StereoEngine | None = None
        self._devs: list[Device] = []
        self._poll_job = None
        self._saved = self._load_settings()
        self._ui_q: queue.Queue = queue.Queue()

        self._build()
        self.refresh_devices()
        self.after(120, self._drain_ui)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------------- 界面
    def _build(self) -> None:
        self.columnconfigure(1, weight=1)

        ttk.Label(
            self,
            text="把两只音箱分别接到左右声道：音乐照常播放，程序把左右声道拆开分送两只音箱。",
            wraplength=700,
            foreground="#555",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        self.cmb_source = self._row(1, "音源（音乐播放到哪）",
                                    "音乐先播到这里，\n程序再从这里取声。\n选不接音箱的端点。")
        self.cmb_left = self._row(2, "左声道音箱", "")
        self.cmb_right = self._row(3, "右声道音箱", "")

        ttk.Label(self, text="模式").grid(row=4, column=0, sticky="w", pady=4)
        self.cmb_mode = ttk.Combobox(self, values=list(MODES), state="readonly", width=46)
        self.cmb_mode.current(0)
        self.cmb_mode.grid(row=4, column=1, sticky="w", pady=4)

        ttk.Label(self, text="增益").grid(row=5, column=0, sticky="w", pady=4)
        gain_box = ttk.Frame(self)
        gain_box.grid(row=5, column=1, sticky="w")
        self.var_gain = tk.DoubleVar(value=1.0)
        ttk.Scale(gain_box, from_=0.0, to=2.0, variable=self.var_gain, length=200,
                  command=lambda *_: self.lbl_gain.config(text=f"{self.var_gain.get():.2f}×")).pack(side="left")
        self.lbl_gain = ttk.Label(gain_box, text="1.00×", width=7)
        self.lbl_gain.pack(side="left", padx=(8, 0))

        ttk.Label(self, text="延迟补偿 (ms)").grid(row=6, column=0, sticky="w", pady=4)
        delay_box = ttk.Frame(self)
        delay_box.grid(row=6, column=1, sticky="w")
        self.var_dl = tk.IntVar(value=0)
        self.var_dr = tk.IntVar(value=0)
        ttk.Label(delay_box, text="左").pack(side="left")
        ttk.Spinbox(delay_box, from_=0, to=1000, increment=5, width=6,
                    textvariable=self.var_dl).pack(side="left", padx=(4, 12))
        ttk.Label(delay_box, text="右").pack(side="left")
        ttk.Spinbox(delay_box, from_=0, to=1000, increment=5, width=6,
                    textvariable=self.var_dr).pack(side="left", padx=(4, 0))
        ttk.Label(delay_box, text="（哪只听着慢就给哪只加）",
                  foreground="#777").pack(side="left", padx=(10, 0))

        btns = ttk.Frame(self)
        btns.grid(row=7, column=0, columnspan=3, sticky="w", pady=(14, 6))
        self.btn_refresh = ttk.Button(btns, text="刷新设备", command=self.refresh_devices)
        self.btn_refresh.pack(side="left")
        self.btn_start = ttk.Button(btns, text="开始", command=self.start)
        self.btn_start.pack(side="left", padx=8)
        self.btn_stop = ttk.Button(btns, text="停止", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left")
        self.btn_test = ttk.Button(btns, text="自检", command=self.selftest)
        self.btn_test.pack(side="left", padx=8)
        self.btn_bt = ttk.Button(btns, text="蓝牙检测", command=self.bluetooth_check)
        self.btn_bt.pack(side="left")
        self.btn_tone = ttk.Button(btns, text="试音", command=self.play_test_tone)
        self.btn_tone.pack(side="left", padx=8)
        self.btn_sound = ttk.Button(btns, text="打开声音设置", command=self.open_sound_settings)
        self.btn_sound.pack(side="left", padx=8)

        ttk.Label(self, text="电平").grid(row=8, column=0, sticky="w", pady=(10, 2))
        self.meter = tk.Canvas(self, height=18, bg="#e8e8e8", highlightthickness=0)
        self.meter.grid(row=8, column=1, columnspan=2, sticky="ew", pady=(10, 2))
        self._meter_bar = self.meter.create_rectangle(0, 0, 0, 18, fill="#2e9e5b", width=0)

        self.var_auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self,
            text="自动把系统默认播放设备切到「音源」，点开始即可（停止时恢复原样）",
            variable=self.var_auto,
        ).grid(row=9, column=0, columnspan=3, sticky="w", pady=(6, 2))

        self.lbl_status = ttk.Label(self, text="未运行", foreground="#444", wraplength=860, justify="left")
        self.lbl_status.grid(row=10, column=0, columnspan=3, sticky="w")

    def _row(self, row: int, label: str, hint: str) -> ttk.Combobox:
        ttk.Label(self, text=label).grid(row=row, column=0, sticky="w", pady=4)
        cmb = ttk.Combobox(self, state="readonly", width=46)
        cmb.grid(row=row, column=1, sticky="w", pady=4)
        if hint:
            ttk.Label(self, text=hint, foreground="#777", wraplength=170,
                      justify="left").grid(row=row, column=2, sticky="w", padx=(8, 0))
        return cmb

    # ---------------------------------------------------------------- 设备
    def refresh_devices(self) -> None:
        try:
            from .doctor import annotate_bluetooth

            self._devs = annotate_bluetooth(
                [d for d in list_devices() if not d.is_input and d.state == DEVICE_STATE_ACTIVE]
            )
        except Exception as exc:
            messagebox.showerror("枚举设备失败", str(exc))
            return
        labels = [f"{d.name}   #{d.index}" for d in self._devs]
        for cmb in (self.cmb_source, self.cmb_left, self.cmb_right):
            cmb["values"] = labels

        # 默认选择：优先蓝牙设备，其次按顺序
        bt = [i for i, d in enumerate(self._devs) if d.is_bt]
        order = bt + [i for i in range(len(self._devs)) if i not in bt]
        first = order[0] if order else None
        second = order[1] if len(order) > 1 else None

        dflt = default_device(False)
        src_idx = None
        if dflt:
            src_idx = next((i for i, d in enumerate(self._devs) if d.id == dflt.id), None)
        if src_idx in (first, second):
            src_idx = next((i for i in order if i not in (first, second)), first)
        if src_idx is None:
            src_idx = first

        self._restore(self.cmb_left, self._saved.get("left"), first)
        self._restore(self.cmb_right, self._saved.get("right"), second)
        self._restore(self.cmb_source, self._saved.get("source"), src_idx)
        if not getattr(self, "_restored_delays", False):
            self._restored_delays = True
            try:
                self.var_dl.set(int(self._saved.get("delay_left", 0) or 0))
                self.var_dr.set(int(self._saved.get("delay_right", 0) or 0))
            except Exception:
                pass

    def _restore(self, cmb: ttk.Combobox, device_id: str | None, fallback: int | None) -> None:
        if device_id:
            for i, d in enumerate(self._devs):
                if d.id == device_id:
                    cmb.current(i)
                    return
        if fallback is not None and 0 <= fallback < len(self._devs):
            cmb.current(fallback)

    def _pick(self, cmb: ttk.Combobox, what: str) -> Device | None:
        i = cmb.current()
        if i < 0 or i >= len(self._devs):
            messagebox.showwarning("还没选好", f"请选择{what}")
            return None
        return self._devs[i]

    # ---------------------------------------------------------------- 控制
    def start(self) -> None:
        if self.engine and self.engine.running:
            return
        source = self._pick(self.cmb_source, "音源设备")
        left = self._pick(self.cmb_left, "左声道音箱")
        right = self._pick(self.cmb_right, "右声道音箱")
        if not (source and left and right):
            return
        if left.id == right.id:
            messagebox.showwarning("选错了", "左、右声道必须选两个不同的设备")
            return
        if source.id in (left.id, right.id):
            messagebox.showwarning(
                "会自激",
                "音源不能是左/右音箱本身，否则声音会循环叠加。\n"
                "建议把音乐播放到一个不接音箱的端点（比如显示器 HDMI 或板载声卡）。",
            )
            return

        cfg = EngineConfig(
            source=source,
            left=left,
            right=right,
            mode=MODES.get(self.cmb_mode.get(), "lr"),
            gain=float(self.var_gain.get()),
            left_delay_ms=float(self.var_dl.get()),
            right_delay_ms=float(self.var_dr.get()),
        )

        # 自动把系统默认播放设备切到音源：这样"播放器照常放歌"就能被截到，
        # 用户不用再去声音设置里手动选设备。
        self._prev_default = None
        if self.var_auto.get():
            try:
                prev = default_device(False)
                if prev and prev.id != source.id:
                    if set_default_device(source.id):
                        self._prev_default = prev
                    else:
                        messagebox.showwarning(
                            "自动切换失败",
                            "没能自动切换系统默认播放设备，请手动在右下角喇叭图标里选：\n"
                            f"{source.name}",
                        )
            except Exception:
                pass

        try:
            self.engine = StereoEngine(cfg)
            self.engine.start()
        except Exception as exc:
            self.engine = None
            messagebox.showerror("启动失败", f"{exc}\n\n如果提示设备被占用，先关闭其它播放软件再试。")
            return

        self._save_settings(source, left, right,
                            float(self.var_dl.get()), float(self.var_dr.get()))
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.btn_refresh.config(state="disabled")
        for cmb in (self.cmb_source, self.cmb_left, self.cmb_right, self.cmb_mode):
            cmb.config(state="disabled")
        self._poll()

    def stop(self) -> None:
        if self._poll_job:
            self.after_cancel(self._poll_job)
            self._poll_job = None
        if self.engine:
            self.engine.stop()
            self.engine = None
        if getattr(self, "_prev_default", None) is not None:
            try:
                set_default_device(self._prev_default.id)
            except Exception:
                pass
            self._prev_default = None
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.btn_refresh.config(state="normal")
        for cmb in (self.cmb_source, self.cmb_left, self.cmb_right, self.cmb_mode):
            cmb.config(state="readonly")
        self.lbl_status.config(text="已停止")
        self.meter.coords(self._meter_bar, 0, 0, 0, 16)

    def _poll(self) -> None:
        if not self.engine:
            return
        st = self.engine.stats()
        w = max(1, self.meter.winfo_width() - 2)
        frac = min(1.0, (st.level ** 0.5) * 1.6) if st.level > 0 else 0.0
        self.meter.coords(self._meter_bar, 1, 1, 1 + int(frac * w), 17)
        if st.error:
            self.lbl_status.config(text=f"出错：{st.error}", foreground="#b00020")
            self.stop()
            messagebox.showerror("播放中断", st.error)
            return

        # 一路掉线不影响另一路出声音，这里只提示，不整体停下
        problems = []
        if st.capture_state != "正常":
            problems.append(f"音源{st.capture_state}")
        if st.left_state != "正常":
            problems.append(f"左音箱{st.left_state}")
        if st.right_state != "正常":
            problems.append(f"右音箱{st.right_state}")

        # 音源一直没有声音 —— 最常见的原因就是忘了把音乐播到"音源"这个设备
        now = time.time()
        if st.captured_frames != getattr(self, "_last_frames", -1):
            self._last_frames = st.captured_frames
            self._last_audio_t = now
        silent_for = now - getattr(self, "_last_audio_t", now)

        if problems:
            self.lbl_status.config(
                text=("运行中 · " + "，".join(problems) + "（恢复后会自动接回）"),
                foreground="#c77700",
            )
        elif silent_for > 3.0 and st.level < 0.002:
            self.lbl_status.config(
                text=(f"运行中 · 音源没有声音：把音乐播放到「{self.cmb_source.get()}」"
                      "（右下角喇叭图标里选它）"),
                foreground="#c77700",
            )
        else:
            self.lbl_status.config(
                text=(f"运行中 · 缓冲 左 {st.fill_ms_left:.0f} ms / 右 {st.fill_ms_right:.0f} ms"
                      f" · 欠载 左 {st.underruns_left} / 右 {st.underruns_right}"),
                foreground="#2e7d32",
            )
        if not self.engine.running:
            self.stop()
            return
        self._poll_job = self.after(200, self._poll)

    def selftest(self) -> None:
        """跑一遍底层自检，结果直接显示在窗口里（pythonw 没有控制台）。"""
        import contextlib
        import io

        from .wasapi import _selftest

        self.stop()
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                _selftest()
        except Exception:
            import traceback

            buf.write(traceback.format_exc())

        self._text_window("自检结果", buf.getvalue())

    def play_test_tone(self) -> None:
        """先左后右各放一段不同音高的测试音，用来确认某只音箱到底会不会出声。"""
        left = self._pick(self.cmb_left, "左声道音箱")
        right = self._pick(self.cmb_right, "右声道音箱")
        if not (left and right):
            return
        self.btn_tone.config(state="disabled")
        threading.Thread(target=self._tone_worker, args=(left, right), daemon=True).start()

    def _post(self, fn) -> None:
        """把界面操作排进主线程队列（tkinter 不能从子线程直接改控件）。"""
        self._ui_q.put(fn)

    def _drain_ui(self) -> None:
        try:
            while True:
                fn = self._ui_q.get_nowait()
                try:
                    fn()
                except Exception:
                    pass
        except queue.Empty:
            pass
        self.after(120, self._drain_ui)

    def _status(self, text: str, color: str = "#444") -> None:
        self._post(lambda: self.lbl_status.config(text=text, foreground=color))

    def _tone_worker(self, left: Device, right: Device) -> None:
        import numpy as np

        from .wasapi import RenderStream

        try:
            for dev, freq, label in ((left, 440.0, "左"), (right, 660.0, "右")):
                self._status(f"试音：{label}声道 → {dev.name}", "#c77700")
                try:
                    stream = RenderStream(dev, buffer_ms=150)
                    stream.start()
                except Exception as exc:
                    self._status(f"{label}声道打不开：{exc}", "#b00020")
                    continue
                try:
                    sr = stream.format.sample_rate
                    phase, t0 = 0, time.time()
                    fade = max(1, int(sr * 0.05))
                    total = int(sr * 1.2)
                    while phase < total and time.time() - t0 < 2.5:
                        free = stream.free_frames()
                        if free <= 0:
                            time.sleep(0.005)
                            continue
                        n = min(free, total - phase)
                        idx = (phase + np.arange(n)) / sr
                        wave = (0.18 * np.sin(2 * np.pi * freq * idx)).astype(np.float32)
                        # 两端各 50ms 淡入淡出，避免"啪"声
                        env = np.ones(n, np.float32)
                        head = min(n, max(0, fade - phase))
                        if head > 0:
                            env[:head] = np.linspace(0, 1, head, dtype=np.float32)
                        tail = max(0, min(n, phase + n - (total - fade)))
                        if tail > 0:
                            env[n - tail :] = np.linspace(1, 0, tail, dtype=np.float32)
                        wave *= env
                        stream.write(n, np.stack([wave, wave], axis=1))
                        phase += n
                        time.sleep(0.004)
                finally:
                    stream.close()
                    time.sleep(0.25)
            self._status("试音结束：两只都响 = 音箱和连接都没问题", "#444")
        finally:
            self._post(lambda: self.btn_tone.config(state="normal"))

    def bluetooth_check(self) -> None:
        """体检：适配器、配对设备、能不能双连。"""
        from .doctor import build_report

        try:
            text, _ok = build_report()
        except Exception:
            import traceback

            text = traceback.format_exc()
        self._text_window("蓝牙检测", text)

    def _text_window(self, title: str, text: str) -> None:
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("700x460")
        win.update_idletasks()
        x = self.winfo_rootx() + 40
        y = self.winfo_rooty() + 40
        win.geometry(f"+{x}+{y}")
        win.transient(self)
        win.lift()
        win.attributes("-topmost", True)
        win.after(400, lambda: win.attributes("-topmost", False))
        txt = tk.Text(win, wrap="word", padx=12, pady=10)
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", text)
        txt.config(state="disabled")
        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=6)
        win.focus_set()

    def open_sound_settings(self) -> None:
        try:
            import os

            os.startfile("ms-settings:sound")
        except Exception as exc:
            messagebox.showinfo("提示", f"请手动打开：设置 → 系统 → 声音\n({exc})")

    # ---------------------------------------------------------------- 设置
    def _load_settings(self) -> dict:
        try:
            return json.loads(SETTINGS.read_text("utf-8"))
        except Exception:
            return {}

    def _save_settings(self, source: Device, left: Device, right: Device,
                       delay_left: float = 0.0, delay_right: float = 0.0) -> None:
        try:
            SETTINGS.write_text(
                json.dumps(
                    {
                        "source": source.id,
                        "left": left.id,
                        "right": right.id,
                        "delay_left": delay_left,
                        "delay_right": delay_right,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _on_close(self) -> None:
        try:
            self.stop()
        finally:
            self.destroy()


def main() -> int:
    try:  # 高分屏清晰一点
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = App()
    if "--autostart" in sys.argv:
        app.after(600, app.start)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
