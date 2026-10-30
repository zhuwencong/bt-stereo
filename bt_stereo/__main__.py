# -*- coding: utf-8 -*-
"""python -m bt_stereo 默认打开图形界面，加 --cli 走命令行。"""
import sys

if "--cli" in sys.argv:
    sys.argv.remove("--cli")
    from .cli import main

    raise SystemExit(main())

from .gui import main

raise SystemExit(main())
