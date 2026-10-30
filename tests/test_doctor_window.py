# -*- coding: utf-8 -*-
"""验证"蓝牙检测"弹窗能创建、内容正确，且不抛异常。"""
import sys
import tkinter as tk

sys.path.insert(0, r"E:\deepseek")

from bt_stereo.gui import App


def main() -> int:
    app = App()
    app.update()

    app.bluetooth_check()
    app.update()

    tops = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
    if not tops:
        print("FAIL: 没有弹出窗口")
        return 1
    win = tops[0]
    print("窗口标题:", win.title())
    print("窗口尺寸:", win.winfo_width(), "x", win.winfo_height())
    print("可见:", bool(win.winfo_viewable()))

    texts = [w for w in win.winfo_children() if isinstance(w, tk.Text)]
    if not texts:
        print("FAIL: 窗口里没有文本框")
        return 1
    content = texts[0].get("1.0", "end")
    print("文本长度:", len(content))
    for line in content.splitlines()[:6]:
        print("  |", line)
    for key in ("蓝牙适配器", "已配对设备", "结论"):
        if key not in content:
            print(f"FAIL: 缺少段落 {key}")
            return 1

    app.destroy()
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
