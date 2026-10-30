# -*- coding: utf-8 -*-
"""单端点隔离测试：只往一个设备播 440Hz，再把它自己的回环录回来分析。

用来区分三种情况：
  * 主频 = 440 且无明显断流  -> 这个设备单独工作正常
  * 主频 = 440 但有大量断流   -> 流在被打断（通常是蓝牙带宽/调度）
  * 主频 ≠ 440               -> 数据被破坏
"""
import sys
import time

sys.path.insert(0, r"E:\deepseek")

import numpy as np
import comtypes

from bt_stereo import LoopbackCapture, RenderStream, list_devices, mix_format
from bt_stereo.wasapi import DEVICE_STATE_ACTIVE

FREQ = 440.0


def find(needle: str):
    devs = [d for d in list_devices() if not d.is_input and d.state == DEVICE_STATE_ACTIVE]
    return next((d for d in devs if needle.lower() in d.name.lower()), None)


def analyse(path: str, seconds: float = 2.0) -> None:
    dev = find(path)
    if dev is None:
        print(f"{path:<22} 端点不存在")
        return
    comtypes.CoInitialize()
    fmt = mix_format(dev)
    rs = RenderStream(dev, buffer_ms=150)
    cap = LoopbackCapture(dev, buffer_ms=500)
    rs.start()
    cap.start()
    sr = fmt.sample_rate
    chunks, written, t0, phase = [], 0, time.time(), 0
    while time.time() - t0 < seconds:
        free = rs.free_frames()
        if free > 0:
            idx = (phase + np.arange(free)) / sr
            tone = (0.2 * np.sin(2 * np.pi * FREQ * idx)).astype(np.float32)
            rs.write(free, np.stack([tone, tone], axis=1))
            phase += free
            written += free
        c = cap.read()
        if c is not None:
            chunks.append(c)
        time.sleep(0.003)
    rs.close()
    cap.close()

    if not chunks:
        print(f"{dev.name:<22} 没有收到任何回环数据")
        return
    data = np.concatenate(chunks)[:, 0]
    elapsed = time.time() - t0

    # 断流检测：10ms 窗口的 RMS，低于中位数 25% 视为断流
    win = int(sr * 0.01)
    n = len(data) // win
    if n < 5:
        print(f"{dev.name:<22} 数据太少")
        return
    rms = np.sqrt(np.mean(data[: n * win].reshape(n, win) ** 2, axis=1))
    med = float(np.median(rms)) or 1e-9
    gaps = int(np.sum(rms < med * 0.25))

    spec = np.abs(np.fft.rfft(data * np.hanning(len(data))))
    freqs = np.fft.rfftfreq(len(data), 1 / sr)
    peak = float(freqs[int(np.argmax(spec))])

    print(f"{dev.name:<22} sr={sr} 写入 {written / elapsed:.0f} 帧/秒 "
          f"回环 {len(data) / elapsed:.0f} 帧/秒 | 主频 {peak:6.0f} Hz | "
          f"10ms 断流 {gaps}/{n} ({(gaps / n * 100) if n else 0:.0f}%)")


if __name__ == "__main__":
    comtypes.CoInitialize()
    names = sys.argv[1:] or ["DOME 2", "Q6", "High Definition Audio Device"]
    for name in names:
        analyse(name)
        time.sleep(0.5)
