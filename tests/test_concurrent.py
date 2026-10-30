# -*- coding: utf-8 -*-
"""并发测试：同时往两个端点播不同音高，再把两路都录回来。

如果「两路蓝牙」有断流而「蓝牙+有线」没有，就说明适配器撑不住两条 A2DP 流，
解决方案是一只有线 + 一只蓝牙。
"""
import sys
import time

sys.path.insert(0, r"E:\deepseek")

import numpy as np
import comtypes

from bt_stereo import LoopbackCapture, RenderStream, list_devices
from bt_stereo.wasapi import DEVICE_STATE_ACTIVE


def find(needle):
    devs = [d for d in list_devices() if not d.is_input and d.state == DEVICE_STATE_ACTIVE]
    return next((d for d in devs if needle.lower() in d.name.lower()), None)


def stats(data: np.ndarray, sr: int) -> tuple[float, float, float]:
    """返回 (主频, 断流百分比, 有效帧率占比)。"""
    if len(data) < sr // 4:
        return 0.0, 100.0, 0.0
    x = data[:, 0]
    win = int(sr * 0.01)
    n = len(x) // win
    rms = np.sqrt(np.mean(x[: n * win].reshape(n, win) ** 2, axis=1))
    med = float(np.median(rms)) or 1e-9
    gaps = 100.0 * float(np.sum(rms < med * 0.25)) / max(n, 1)
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1 / sr)
    peak = float(freqs[int(np.argmax(spec))])
    return peak, gaps, len(x) / (n * win)


def run(name_a: str, name_b: str, fa: float = 440.0, fb: float = 880.0, seconds: float = 2.0) -> None:
    a, b = find(name_a), find(name_b)
    if not (a and b):
        print(f"跳过 {name_a} + {name_b}: 设备不存在")
        return
    comtypes.CoInitialize()
    ra, rb = RenderStream(a, 150), RenderStream(b, 150)
    ca, cb = LoopbackCapture(a, 500), LoopbackCapture(b, 500)
    for s in (ra, rb, ca, cb):
        s.start()
    sra, srb = ra.format.sample_rate, rb.format.sample_rate
    da, db = [], []
    t0 = time.time()
    pa = pb = 0
    while time.time() - t0 < seconds:
        for stream, sr, f, getattr_p in ((ra, sra, fa, "a"), (rb, srb, fb, "b")):
            free = stream.free_frames()
            if free <= 0:
                continue
            base = pa if getattr_p == "a" else pb
            idx = (base + np.arange(free)) / sr
            tone = (0.2 * np.sin(2 * np.pi * f * idx)).astype(np.float32)
            stream.write(free, np.stack([tone, tone], axis=1))
            if getattr_p == "a":
                pa += free
            else:
                pb += free
        for cap, out in ((ca, da), (cb, db)):
            c = cap.read()
            if c is not None:
                out.append(c)
        time.sleep(0.003)
    for s in (ra, rb, ca, cb):
        s.close()

    for name, dev, chunks, sr, expect in (
        (name_a, a, da, sra, fa), (name_b, b, db, srb, fb)
    ):
        if not chunks:
            print(f"  {dev.name:<40} 无数据")
            continue
        peak, gaps, ratio = stats(np.concatenate(chunks), sr)
        flag = "✔" if abs(peak - expect) < 40 and gaps < 5 else "✘"
        print(f"  {flag} {dev.name:<40} 期望 {expect:4.0f} 实测 {peak:6.0f} Hz  "
              f"断流 {gaps:5.1f}%  数据率 {ratio * 100:5.1f}%")


if __name__ == "__main__":
    comtypes.CoInitialize()
    print("=== 组合 1：两只蓝牙同时 ===")
    run("DOME 2", "Q6")
    time.sleep(1.0)
    print("=== 组合 2：有线 + DOME 2 ===")
    run("High Definition Audio Device", "DOME 2")
    time.sleep(1.0)
    print("=== 组合 3：有线 + Q6 ===")
    run("High Definition Audio Device", "Q6")
