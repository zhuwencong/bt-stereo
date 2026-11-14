# -*- coding: utf-8 -*-
"""python -m bt_stereo 默认打开图形界面，加 --cli 走命令行。

另外兼容 `python -m bt_stereo list|doctor|run|test` 这种直写子命令的写法，
省得用户（和 AI）记不住 --cli。
"""
import sys

_CLI_COMMANDS = {"list", "doctor", "run", "test"}

if "--cli" in sys.argv:
    sys.argv.remove("--cli")
    from .cli import main

    raise SystemExit(main())

if len(sys.argv) > 1 and sys.argv[1] in _CLI_COMMANDS:
    from .cli import main

    raise SystemExit(main())

try:
    from .gui import main as gui_main
except SystemExit as exc:  # gui.py 的 tkinter 兜底会走到这里
    # 图形界面起不来时不要裸崩，降级到命令行，让用户仍然有路可走
    print(exc.code if exc.code else "图形界面不可用。", file=sys.stderr)
    print("", file=sys.stderr)
    from .cli import main as cli_main

    raise SystemExit(cli_main(["--help"]))

raise SystemExit(gui_main())
