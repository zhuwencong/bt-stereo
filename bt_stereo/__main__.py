# -*- coding: utf-8 -*-
"""python -m bt_stereo 的入口。

真正的路由逻辑放在 entry.py，和打包入口 app_entry.py 共用同一份实现，
避免两边各写一份、改了一个忘了另一个。
"""
import sys

from .entry import main

raise SystemExit(main())
