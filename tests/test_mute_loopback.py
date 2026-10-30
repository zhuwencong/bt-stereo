# -*- coding: utf-8 -*-
"""验证：把音源端点静音后，WASAPI 回环还能不能收到声音。

如果"能"，程序就可以自动静音音源设备，用户就不必去改默认播放设备了。
"""
import sys
import time
from ctypes import POINTER, byref, c_float, c_void_p
from ctypes.wintypes import BOOL, UINT

sys.path.insert(0, r"E:\deepseek")

import numpy as np
import comtypes
from comtypes import CLSCTX_ALL, COMMETHOD, GUID, HRESULT, IUnknown

from bt_stereo import LoopbackCapture, RenderStream, list_devices
from bt_stereo.wasapi import DEVICE_STATE_ACTIVE, _open

IID_IAudioEndpointVolume = GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")


class IAudioEndpointVolume(IUnknown):
    _iid_ = IID_IAudioEndpointVolume
    _methods_ = [
        COMMETHOD([], HRESULT, "RegisterControlChangeNotify", (["in"], POINTER(IUnknown), "n")),
        COMMETHOD([], HRESULT, "UnregisterControlChangeNotify", (["in"], POINTER(IUnknown), "n")),
        COMMETHOD([], HRESULT, "GetChannelCount", (["out"], POINTER(UINT), "n")),
        COMMETHOD([], HRESULT, "SetMasterVolumeLevel", (["in"], c_float, "f"), (["in"], c_void_p, "c")),
        COMMETHOD([], HRESULT, "SetMasterVolumeLevelScalar", (["in"], c_float, "f"), (["in"], c_void_p, "c")),
        COMMETHOD([], HRESULT, "GetMasterVolumeLevel", (["out"], POINTER(c_float), "f")),
        COMMETHOD([], HRESULT, "GetMasterVolumeLevelScalar", (["out"], POINTER(c_float), "f")),
        COMMETHOD([], HRESULT, "SetChannelVolumeLevel", (["in"], UINT, "ch"), (["in"], c_float, "f"), (["in"], c_void_p, "c")),
        COMMETHOD([], HRESULT, "SetChannelVolumeLevelScalar", (["in"], UINT, "ch"), (["in"], c_float, "f"), (["in"], c_void_p, "c")),
        COMMETHOD([], HRESULT, "GetChannelVolumeLevel", (["in"], UINT, "ch"), (["out"], POINTER(c_float), "f")),
        COMMETHOD([], HRESULT, "GetChannelVolumeLevelScalar", (["in"], UINT, "ch"), (["out"], POINTER(c_float), "f")),
        COMMETHOD([], HRESULT, "SetMute", (["in"], BOOL, "m"), (["in"], c_void_p, "c")),
        COMMETHOD([], HRESULT, "GetMute", (["out"], POINTER(BOOL), "m")),
    ]


def vol_iface(device_id: str):
    return _open(device_id).Activate(
        byref(IID_IAudioEndpointVolume), CLSCTX_ALL, None
    ).QueryInterface(IAudioEndpointVolume)


def measure(dev, seconds=1.2):
    comtypes.CoInitialize()
    cap = LoopbackCapture(dev, 500)
    cap.start()
    chunks = []
    t0 = time.time()
    while time.time() - t0 < seconds:
        c = cap.read()
        if c is not None:
            chunks.append(c)
        time.sleep(0.004)
    cap.close()
    if not chunks:
        return 0.0
    d = np.concatenate(chunks)
    return float(np.sqrt(np.mean(d ** 2)))


def main() -> int:
    comtypes.CoInitialize()
    devs = [d for d in list_devices() if not d.is_input and d.state == DEVICE_STATE_ACTIVE]
    dev = next((d for d in devs if "Mi Monitor" in d.name), devs[0])
    print("被测端点:", dev.name)

    rs = RenderStream(dev, 150)
    rs.start()
    sr = rs.format.sample_rate

    def feed(seconds=2.6):
        t0, phase = time.time(), 0
        while time.time() - t0 < seconds:
            free = rs.free_frames()
            if free > 0:
                idx = (phase + np.arange(free)) / sr
                tone = (0.2 * np.sin(2 * np.pi * 440 * idx)).astype(np.float32)
                rs.write(free, np.stack([tone, tone], axis=1))
                phase += free
            time.sleep(0.004)

    import threading

    th = threading.Thread(target=feed, daemon=True)
    th.start()
    time.sleep(0.3)
    rms_normal = measure(dev)
    print(f"未静音时回环 RMS = {rms_normal:.5f}")

    vol = vol_iface(dev.id)
    vol.SetMute(True, None)
    time.sleep(0.2)
    rms_muted = measure(dev)
    muted_flag = bool(vol.GetMute())
    vol.SetMute(False, None)
    rs.close()
    print(f"静音后回环 RMS = {rms_muted:.5f}（端点静音状态={muted_flag}）")

    kept = rms_muted > rms_normal * 0.3 if rms_normal > 1e-6 else False
    print("结论:", "静音不影响回环 ✔（可自动静音音源）" if kept else "静音会掐断回环 ✘")
    return 0 if kept else 2


if __name__ == "__main__":
    raise SystemExit(main())
