# -*- coding: utf-8 -*-
"""稳定性测试（静音、不吵人）。

往"音源"端点持续写真正的零样本（不是静音标志位），让回环捕获一直有数据流过，
再把数据分给两只蓝牙音箱。这样可以完整跑通"捕获 -> 拆分 -> 双输出 -> 漂移补偿"
整条链路，但耳朵听不到任何声音。

判据：水位稳定在目标附近不持续漂移，欠载不随时间增长。
"""
import sys
import threading
import time

sys.path.insert(0, r"E:\deepseek")

import comtypes
import numpy as np

from bt_stereo import EngineConfig, RenderStream, StereoEngine, list_devices
from bt_stereo.wasapi import DEVICE_STATE_ACTIVE


def find(needle):
    devs = [d for d in list_devices() if not d.is_input and d.state == DEVICE_STATE_ACTIVE]
    return next((d for d in devs if needle.lower() in d.name.lower()), None)


def silence_writer(dev, stop: threading.Event) -> None:
    comtypes.CoInitialize()
    stream = RenderStream(dev, buffer_ms=200)
    stream.start()
    try:
        while not stop.is_set():
            free = stream.free_frames()
            if free > 0:
                stream.write(free, np.zeros((free, 2), np.float32))
            time.sleep(0.005)
    finally:
        stream.close()
        comtypes.CoUninitialize()


def main() -> int:
    args = sys.argv[1:]
    devs = [d for d in list_devices() if not d.is_input and d.state == DEVICE_STATE_ACTIVE]
    src = find(args[0]) if len(args) > 0 else find("High Definition")
    if src is None:
        src = devs[0]
    pool = [d for d in devs if d.name != src.name]
    # 优先用蓝牙端点
    bt = [d for d in pool if d.is_bt]
    ordered = bt + [d for d in pool if d not in bt]
    left = find(args[1]) if len(args) > 1 else (ordered[0] if ordered else None)
    right = find(args[2]) if len(args) > 2 else next(
        (d for d in ordered if left and d.name != left.name), None)
    if not (src and left and right):
        print("设备不全:", src, left, right)
        return 1
    print(f"音源 {src.name} / 左 {left.name} / 右 {right.name}")

    stop = threading.Event()
    feeder = threading.Thread(target=silence_writer, args=(src, stop), daemon=True)
    feeder.start()
    time.sleep(0.3)

    eng = StereoEngine(EngineConfig(source=src, left=left, right=right, mode="lr"))
    eng.start()
    t0 = time.time()
    rows = []
    underruns = []
    while time.time() - t0 < 20:
        time.sleep(2.0)
        st = eng.stats()
        rows.append((st.fill_ms_left, st.fill_ms_right))
        underruns.append(st.underruns_left + st.underruns_right)
        print(f"t={time.time() - t0:4.1f}s  水位 L={st.fill_ms_left:5.1f} R={st.fill_ms_right:5.1f}"
              f"  欠载 累计 {underruns[-1]}  错误={st.error or '无'}")
        if st.error:
            break
    eng.stop()
    stop.set()
    feeder.join(timeout=2)

    ls = [r[0] for r in rows]
    rs = [r[1] for r in rows]
    grew = underruns[-1] - underruns[len(underruns) // 2] if underruns else 0
    print(f"\n水位范围 左 {min(ls):.0f}~{max(ls):.0f} ms / 右 {min(rs):.0f}~{max(rs):.0f} ms")
    print(f"后半程新增欠载: {grew}")
    ok = grew <= 2 and max(max(ls), max(rs)) < 400
    print("稳定性:", "通过" if ok else "不稳定")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
