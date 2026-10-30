# -*- coding: utf-8 -*-
"""闭环自测：往"音源"端点播一个 左=1kHz / 右=3kHz 的信号，
让引擎把左右分开送到两个输出端点，再把两个输出端点的回环录回来做频谱分析。

用法： python tests\test_split.py "音源名" "左输出名" "右输出名"
不传参数时自动挑三个不同的端点。
"""
from __future__ import annotations

import sys
import threading
import time

import comtypes
import numpy as np

sys.path.insert(0, __file__.rsplit("\\", 2)[0])

from bt_stereo import Device, LoopbackCapture, RenderStream, StereoEngine, EngineConfig, list_devices
from bt_stereo.wasapi import DEVICE_STATE_ACTIVE

FREQ_L, FREQ_R = 1000.0, 3000.0
AMP = 0.25


def peak_freq(chunk: np.ndarray, sr: int) -> tuple[float, float]:
    """返回 (主频, 主频处的相对能量)。"""
    if chunk is None or len(chunk) < 2048:
        return 0.0, 0.0
    mono = chunk.mean(axis=1)
    win = np.hanning(len(mono))
    spec = np.abs(np.fft.rfft(mono * win))
    freqs = np.fft.rfftfreq(len(mono), 1.0 / sr)
    k = int(np.argmax(spec))
    return float(freqs[k]), float(spec[k] / (len(mono) / 2.0))


def energy_at(chunk: np.ndarray, sr: int, f: float) -> float:
    if chunk is None or len(chunk) < 2048:
        return 0.0
    mono = chunk.mean(axis=1)
    spec = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
    freqs = np.fft.rfftfreq(len(mono), 1.0 / sr)
    k = int(np.argmin(np.abs(freqs - f)))
    return float(spec[max(0, k - 3) : k + 4].max() / (len(mono) / 2.0))


def tone_writer(dev: Device, stop: threading.Event, sr_hint: int = 48000):
    comtypes.CoInitialize()
    stream = RenderStream(dev, buffer_ms=200)
    stream.start()
    sr = stream.format.sample_rate
    phase = 0
    try:
        while not stop.is_set():
            free = stream.free_frames()
            if free <= 0:
                time.sleep(0.002)
                continue
            idx = (phase + np.arange(free)) / sr
            l = AMP * np.sin(2 * np.pi * FREQ_L * idx)
            r = AMP * np.sin(2 * np.pi * FREQ_R * idx)
            stream.write(free, np.stack([l, r], axis=1).astype(np.float32))
            phase += free
            time.sleep(0.001)
    finally:
        stream.close()
        comtypes.CoUninitialize()


def record(dev: Device, seconds: float) -> tuple[np.ndarray, int]:
    comtypes.CoInitialize()
    cap = LoopbackCapture(dev, buffer_ms=500)
    cap.start()
    chunks = []
    t0 = time.time()
    try:
        while time.time() - t0 < seconds:
            c = cap.read()
            if c is not None:
                chunks.append(c)
            time.sleep(0.004)
    finally:
        cap.close()
        comtypes.CoUninitialize()
    data = np.concatenate(chunks) if chunks else np.zeros((0, 2), np.float32)
    return data, cap.format.sample_rate


def main() -> int:
    args = sys.argv[1:]
    outs = [d for d in list_devices() if not d.is_input and d.state == DEVICE_STATE_ACTIVE]
    if not outs:
        print("没有可用播放端点")
        return 1
    if len(args) >= 3:
        pick = []
        for name in args[:3]:
            hit = [d for d in outs if name.lower() in d.name.lower()]
            if not hit:
                print(f"找不到设备：{name}")
                return 1
            pick.append(hit[0])
        src, left, right = pick
    else:
        if len(outs) < 3:
            print(f"需要至少 3 个播放端点，当前只有 {len(outs)} 个：", [d.name for d in outs])
            return 1
        src, left, right = outs[0], outs[1], outs[2]

    print(f"音源   : {src.name}")
    print(f"左输出 : {left.name}")
    print(f"右输出 : {right.name}")

    tone_stop = threading.Event()
    tone_thread = threading.Thread(target=tone_writer, args=(src, tone_stop), daemon=True)
    tone_thread.start()
    time.sleep(0.3)

    engine = StereoEngine(EngineConfig(source=src, left=left, right=right, mode="lr"))
    engine.start()
    time.sleep(1.0)  # 让缓冲区建起来

    data_l, sr_l = record(left, 1.0)
    data_r, sr_r = record(right, 1.0)

    st = engine.stats()
    engine.stop()
    tone_stop.set()
    tone_thread.join(timeout=2)

    pl, al = peak_freq(data_l, sr_l)
    pr, ar = peak_freq(data_r, sr_r)
    cross_l = energy_at(data_l, sr_l, FREQ_R)
    cross_r = energy_at(data_r, sr_r, FREQ_L)

    print(f"\n左音箱: 主频 {pl:7.0f} Hz 幅度 {al:.3f} | 3kHz 串音 {cross_l:.4f}")
    print(f"右音箱: 主频 {pr:7.0f} Hz 幅度 {ar:.3f} | 1kHz 串音 {cross_r:.4f}")
    print(f"引擎统计: 捕获 {st.captured_frames} 帧, 欠载 L/R = {st.underruns_left}/{st.underruns_right}"
          f", 水位 L/R = {st.fill_ms_left:.0f}/{st.fill_ms_right:.0f} ms"
          f", 错误={st.error or '无'}")

    ok_l = abs(pl - FREQ_L) < 60 and al > 0.02 and cross_l < al * 0.2
    ok_r = abs(pr - FREQ_R) < 60 and ar > 0.02 and cross_r < ar * 0.2
    print("\n结论:", "左右声道分离正常 ✔" if (ok_l and ok_r) else "分离不正确 ✘")
    return 0 if (ok_l and ok_r) else 2


if __name__ == "__main__":
    raise SystemExit(main())
