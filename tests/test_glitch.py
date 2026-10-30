# -*- coding: utf-8 -*-
"""端到端卡顿检测：往音源灌 440Hz，引擎拆成左右，再把两只音箱的输出录回来数断流。

用法： python tests\test_glitch.py [秒数]
"""
import sys
import threading
import time

sys.path.insert(0, r"E:\deepseek")

import numpy as np
import comtypes

from bt_stereo import EngineConfig, LoopbackCapture, RenderStream, StereoEngine, list_devices, mix_format
from bt_stereo.wasapi import DEVICE_STATE_ACTIVE


def find(needle):
    devs = [d for d in list_devices() if not d.is_input and d.state == DEVICE_STATE_ACTIVE]
    return next((d for d in devs if needle.lower() in d.name.lower()), None)


def gaps_of(chunks, sr):
    if not chunks:
        return 100.0, 0, 0.0
    x = np.concatenate(chunks)[:, 0]
    win = int(sr * 0.01)
    n = len(x) // win
    if n < 5:
        return 100.0, n, 0.0
    rms = np.sqrt(np.mean(x[: n * win].reshape(n, win) ** 2, axis=1))
    med = float(np.median(rms)) or 1e-9
    gaps = int(np.sum(rms < med * 0.25))
    return 100.0 * gaps / n, n, float(np.sqrt(np.mean(x ** 2)))


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    src = find("ToDesk")
    left = find("Q6")
    right = find("DOME 2")
    if not (src and left and right):
        print("设备不全", src, left, right)
        return 1
    print(f"音源 {src.name} / 左 {left.name} / 右 {right.name} / 时长 {seconds:.0f}s")

    comtypes.CoInitialize()
    # 音源喂一个连续 440Hz
    stop_feed = threading.Event()

    def feed():
        comtypes.CoInitialize()
        s = RenderStream(src, 200)
        s.start()
        sr = s.format.sample_rate
        phase = 0
        try:
            while not stop_feed.is_set():
                f = s.free_frames()
                if f > 0:
                    idx = (phase + np.arange(f)) / sr
                    t = (0.15 * np.sin(2 * np.pi * 440 * idx)).astype(np.float32)
                    s.write(f, np.stack([t, t], axis=1))
                    phase += f
                time.sleep(0.004)
        finally:
            s.close()

    threading.Thread(target=feed, daemon=True).start()
    time.sleep(0.4)

    eng = StereoEngine(EngineConfig(source=src, left=left, right=right))
    eng.start()
    time.sleep(0.5)

    caps = {}
    def rec(key, dev):
        comtypes.CoInitialize()
        c = LoopbackCapture(dev, 400)
        c.start()
        ch = []
        t0 = time.time()
        while time.time() - t0 < seconds:
            x = c.read()
            if x is not None:
                ch.append(x)
            time.sleep(0.004)
        c.close()
        caps[key] = (ch, mix_format(dev).sample_rate)

    ths = [threading.Thread(target=rec, args=("L", left)), threading.Thread(target=rec, args=("R", right))]
    [t.start() for t in ths]
    [t.join() for t in ths]

    st = eng.stats()
    eng.stop()
    stop_feed.set()
    time.sleep(0.3)

    ok = True
    for key in ("L", "R"):
        ch, sr = caps.get(key, ([], 44100))
        pct, n, rms = gaps_of(ch, sr)
        print(f"  {key}声道: 10ms 断流 {pct:5.1f}%  窗数 {n}  RMS {rms:.4f}")
        ok = ok and pct < 3.0
    print(f"引擎: 欠载 L/R={st.underruns_left}/{st.underruns_right} "
          f"水位 {st.fill_ms_left:.0f}/{st.fill_ms_right:.0f} ms 错误={st.error or '无'}")
    print("结论:", "流畅 ✔" if ok else "仍有明显断流 ✘")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
