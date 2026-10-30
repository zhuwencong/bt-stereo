# -*- coding: utf-8 -*-
"""PyInstaller 打包入口（源码运行时请用 `python -m bt_stereo`）。"""
import sys


def main() -> int:
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        from bt_stereo.cli import main as cli_main

        return cli_main()
    from bt_stereo.gui import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
