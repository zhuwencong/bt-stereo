# -*- coding: utf-8 -*-
"""PyInstaller 打包入口（源码运行时请用 `python -m bt_stereo`）。

这里只做转发，真正的路由逻辑在 bt_stereo/entry.py，
和源码入口 bt_stereo/__main__.py 共用同一份实现。
"""
import sys


def main() -> int:
    from bt_stereo.entry import main as entry_main

    return entry_main()


if __name__ == "__main__":
    raise SystemExit(main())
