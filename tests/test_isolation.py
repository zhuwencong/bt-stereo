# -*- coding: utf-8 -*-
"""验证单路故障隔离：右声道指向一个不存在的设备，左声道应继续正常工作。"""
import sys
import time

sys.path.insert(0, r"E:\deepseek")

from bt_stereo import Device, EngineConfig, StereoEngine, list_devices
from bt_stereo.wasapi import DEVICE_STATE_ACTIVE


def find(needle):
    devs = [d for d in list_devices() if not d.is_input and d.state == DEVICE_STATE_ACTIVE]
    return next((d for d in devs if needle.lower() in d.name.lower()), None)


def main() -> int:
    src = find("High Definition")
    left = find("Mi Monitor")
    ghost = Device(index=-1, id="ghost", name="不存在的音箱XYZ", state=1, is_input=False)
    if not (src and left):
        print("找不到测试设备")
        return 1

    eng = StereoEngine(EngineConfig(source=src, left=left, right=ghost, mode="lr"))
    eng.start()
    time.sleep(4.0)
    st = eng.stats()
    print(f"running={st.running}  left_state={st.left_state}  right_state={st.right_state}"
          f"  capture_state={st.capture_state}  error={st.error or '无'}")
    eng.stop()

    ok = (st.left_state == "正常" and st.right_state == "音箱离线" and st.running)
    print("结果:", "通过：左路正常工作，右路单独等待重连" if ok else "失败")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
