# -*- coding: utf-8 -*-
"""验证"自动切换默认播放设备"：开始后默认设备应变成音源，停止后应恢复。"""
import sys
import time

sys.path.insert(0, r"E:\deepseek")

from bt_stereo.gui import App
from bt_stereo.wasapi import default_device


def pick(app, cmb, needle):
    for i, d in enumerate(app._devs):
        if needle.lower() in d.name.lower():
            cmb.current(i)
            return True
    return False


def main() -> int:
    from bt_stereo.wasapi import set_default_device

    app = App()
    app.update()
    # 先把默认设备设成"真实播放设备"，模拟用户平时直接放歌的状态
    mi = next((d for d in app._devs if "Mi Monitor" in d.name), None)
    if mi:
        set_default_device(mi.id)
    before = default_device(False)
    print("开始前默认:", before.name if before else None)

    pick(app, app.cmb_source, "ToDesk")
    pick(app, app.cmb_left, "Q6")
    pick(app, app.cmb_right, "DOME 2")
    app.var_auto.set(True)
    app.update()

    app.start()
    app.update()
    time.sleep(0.5)
    during = default_device(False)
    print("运行中默认:", during.name if during else None)

    app.stop()
    app.update()
    after = default_device(False)
    print("停止后默认:", after.name if after else None)

    ok = (during and "ToDesk" in during.name and after and before and after.id == before.id)
    app.destroy()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
