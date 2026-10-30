# -*- coding: utf-8 -*-
"""无人值守地驱动 GUI：选中设备 -> 开始 -> 观察状态 -> 停止。"""
import sys
import time

sys.path.insert(0, __file__.rsplit("\\", 2)[0])

from bt_stereo.gui import App


def pick(app, cmb, needle):
    for i, d in enumerate(app._devs):
        if needle.lower() in d.name.lower():
            cmb.current(i)
            return True
    return False


def main():
    app = App()
    app.update()
    print("设备数", len(app._devs))
    print("默认选择:", app.cmb_source.get(), "|", app.cmb_left.get(), "|", app.cmb_right.get())

    ok = (pick(app, app.cmb_source, "耳机")
          and pick(app, app.cmb_left, "Mi Monitor")
          and pick(app, app.cmb_right, "TS238E1"))
    app.update()
    if not ok:
        print("没找到测试用设备")
        return 1

    app.start()
    t0 = time.time()
    while time.time() - t0 < 2.5:
        app.update()
        time.sleep(0.05)
        if app.engine is None:
            print("引擎启动失败")
            return 1

    print("运行时状态:", app.lbl_status.cget("text"))
    print("引擎 running:", app.engine.running)
    print("按钮 开始/停止:", str(app.btn_start.cget("state")), "/", str(app.btn_stop.cget("state")))

    app.stop()
    app.update()
    print("停止后状态:", app.lbl_status.cget("text"))
    print("按钮 开始/停止:", str(app.btn_start.cget("state")), "/", str(app.btn_stop.cget("state")))
    app.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
