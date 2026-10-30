# -*- coding: utf-8 -*-
"""验证"试音"按钮：左右各放 1.2 秒，检查状态文本按预期变化。"""
import sys
import time

sys.path.insert(0, r"E:\deepseek")

from bt_stereo.gui import App


def pick(app, cmb, needle):
    for i, d in enumerate(app._devs):
        if needle.lower() in d.name.lower():
            cmb.current(i)
            return True
    return False


def main() -> int:
    app = App()
    app.update()
    ok = pick(app, app.cmb_left, "Q6") and pick(app, app.cmb_right, "Mi Monitor")
    app.update()
    if not ok:
        print("没有测试设备")
        return 1
    print("左:", app.cmb_left.get(), "| 右:", app.cmb_right.get())

    app.play_test_tone()
    seen = []
    t0 = time.time()
    while time.time() - t0 < 7:
        app.update()
        txt = app.lbl_status.cget("text")
        if not seen or seen[-1] != txt:
            seen.append(txt)
            print("  状态:", txt)
        time.sleep(0.05)
        if txt.startswith("试音结束"):
            break
    done = app.lbl_status.cget("text").startswith("试音结束")
    print("按钮恢复:", str(app.btn_tone.cget("state")))
    app.destroy()
    print("PASS" if done else "FAIL")
    return 0 if done else 2


if __name__ == "__main__":
    raise SystemExit(main())
