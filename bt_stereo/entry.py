# -*- coding: utf-8 -*-
"""统一的启动路由。

两个入口共用这一份逻辑，避免各写一份然后改漏：
- 源码运行：python -m bt_stereo  → bt_stereo/__main__.py
- 打包运行：bt-stereo.exe        → app_entry.py（PyInstaller 的入口脚本）

历史教训：这两个入口曾经各写一份，结果 __main__.py 支持了
`bt-stereo list` 这种直写子命令的写法，app_entry.py 却没跟上。
打包后的 exe 跑 `bt-stereo.exe list` 会当成"无参数"直接开图形界面——
在命令行里表现为挂住且一个字都不输出，看起来像是程序卡死。
"""
from __future__ import annotations

import sys

# 可以直接写、不用加 --cli 的子命令
CLI_COMMANDS = {"list", "doctor", "run", "test"}

# 这些参数说明用户想要命令行，不该弹图形界面
CLI_FLAGS = {"-h", "--help", "-V", "--version"}


def _wants_cli(argv: list[str]) -> bool:
    """判断这次调用该走命令行还是图形界面。"""
    if "--cli" in argv:
        return True
    if not argv:
        return False
    first = argv[0]
    return first in CLI_COMMANDS or first in CLI_FLAGS


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if _wants_cli(argv):
        if "--cli" in argv:
            argv.remove("--cli")
        from .cli import main as cli_main

        return cli_main(argv)

    try:
        from .gui import main as gui_main
    except SystemExit as exc:
        # gui.py 发现缺 tkinter 时会抛 SystemExit 并附带中文说明。
        # 图形界面起不来不该让用户彻底没路走，降级到命令行帮助。
        print(exc.code if exc.code else "图形界面不可用。", file=sys.stderr)
        print("", file=sys.stderr)
        from .cli import main as cli_main

        return cli_main(["--help"])

    return gui_main()
