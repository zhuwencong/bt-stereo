# -*- coding: utf-8 -*-
"""命令行入口。

    python -m bt_stereo list
    python -m bt_stereo run --left 2 --right 3 --source 0
    python -m bt_stereo run            # 交互式选择
"""
from __future__ import annotations

import argparse
import sys
import time

from .engine import EngineConfig, StereoEngine
from .wasapi import DEVICE_STATE_ACTIVE, Device, default_device, list_devices, mix_format

BAR = "▁▂▃▄▅▆▇█"


def _devices() -> list[Device]:
    from .doctor import annotate_bluetooth

    return annotate_bluetooth(
        [d for d in list_devices() if not d.is_input and d.state == DEVICE_STATE_ACTIVE]
    )


def cmd_list(_args) -> int:
    dflt = default_device(False)
    devs = _devices()
    print("可用播放端点（首列是编号，* 表示系统默认）：")
    for d in devs:
        mark = "*" if dflt and d.id == dflt.id else " "
        try:
            fmt = mix_format(d).describe()
        except Exception as exc:
            fmt = f"<打不开：{exc}>"
        tag = "  [蓝牙]" if d.is_bt else ""
        print(f" {mark}[{d.index}] {d.name}{tag}\n        {fmt}")
    print("\n提示：先把两只蓝牙音箱都连上电脑，再运行 run。")
    return 0


def _resolve(spec: str, devs: list[Device], kind: str) -> Device:
    spec = (spec or "").strip()
    if not spec:
        raise SystemExit(f"请指定{kind}")
    if spec.isdigit():
        for d in devs:
            if d.index == int(spec):
                return d
        raise SystemExit(f"没有编号为 {spec} 的{kind}")
    hits = [d for d in devs if spec.lower() in d.name.lower()]
    if not hits:
        raise SystemExit(f"找不到名字含“{spec}”的{kind}")
    if len(hits) > 1:
        names = "、".join(h.name for h in hits)
        raise SystemExit(f"“{spec}”匹配到多个{kind}：{names}，请用编号指定")
    return hits[0]


def _ask(prompt: str, devs: list[Device]) -> Device:
    print(prompt)
    for d in devs:
        print(f"  [{d.index}] {d.name}")
    while True:
        s = input("编号或名字片段：").strip()
        try:
            return _resolve(s, devs, prompt)
        except SystemExit as exc:
            print(exc)


def cmd_run(args) -> int:
    devs = _devices()
    if len(devs) < 2:
        print("可用播放端点不足 2 个。先把两只蓝牙音箱连上（设置 → 蓝牙和设备）。")
        return 1

    if args.left and args.right:
        left = _resolve(args.left, devs, "左声道设备")
        right = _resolve(args.right, devs, "右声道设备")
    else:
        left = _ask("左声道 →", devs)
        right = _ask("右声道 →", devs)

    if args.source:
        source = _resolve(args.source, devs, "音源设备")
    else:
        dflt = default_device(False)
        source = dflt if dflt and dflt.id not in (left.id, right.id) else None
        if source is None:
            source = _ask("音源（音乐实际播放到的设备）→", devs)

    if source.id in (left.id, right.id):
        print("错误：音源不能和输出是同一个设备，否则会自我循环。请换一个音源。")
        return 1

    cfg = EngineConfig(
        source=source,
        left=left,
        right=right,
        mode=args.mode,
        gain=args.gain,
        left_delay_ms=args.delay_left,
        right_delay_ms=args.delay_right,
        target_ms=args.target_ms,
    )
    print(f"\n音源 : {source.name}")
    print(f"左   : {left.name}   (+{cfg.left_delay_ms:.0f} ms)")
    print(f"右   : {right.name}   (+{cfg.right_delay_ms:.0f} ms)")
    print(f"模式 : {cfg.mode}   增益 {cfg.gain}\n")

    engine = StereoEngine(cfg)
    engine.start()
    time.sleep(0.15)
    print("运行中，Ctrl+C 停止。")
    try:
        while engine.running:
            st = engine.stats()
            lvl = min(len(BAR) - 1, int(st.level * 260))
            line = (
                f"\r电平 {BAR[lvl]}  "
                f"缓冲 L {st.fill_ms_left:5.0f}ms / R {st.fill_ms_right:5.0f}ms  "
                f"欠载 L{st.underruns_left:3d} R{st.underruns_right:3d}"
            )
            print(line, end="", flush=True)
            if st.error:
                print(f"\n[错误] {st.error}")
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n正在停止…")
        engine.stop()
    return 0


def cmd_doctor(_args) -> int:
    from .doctor import build_report

    text, ok = build_report()
    print(text)
    return 0 if ok else 2


def cmd_test(_args) -> int:
    from .wasapi import _selftest

    return _selftest()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bt_stereo", description="把两只音箱做成一对左右声道")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列出可用播放端点").set_defaults(func=cmd_list)

    sub.add_parser("doctor", help="体检：适配器、配对设备、能否双连").set_defaults(func=cmd_doctor)

    r = sub.add_parser("run", help="开始左右声道拆分")
    r.add_argument("--left", help="左声道输出设备（编号或名字片段）")
    r.add_argument("--right", help="右声道输出设备（编号或名字片段）")
    r.add_argument("--source", help="音源设备：音乐实际播放到的那个端点")
    r.add_argument("--mode", default="lr", choices=["lr", "swap", "duplicate"],
                   help="lr=左右分离（默认）, swap=左右互换, duplicate=两边都放完整立体声")
    r.add_argument("--gain", type=float, default=1.0, help="增益，默认 1.0")
    r.add_argument("--delay-left", type=float, default=0.0, help="左音箱额外延迟（毫秒）")
    r.add_argument("--delay-right", type=float, default=0.0, help="右音箱额外延迟（毫秒）")
    r.add_argument("--target-ms", type=float, default=80.0, help="缓冲目标深度（毫秒）")
    r.set_defaults(func=cmd_run)

    sub.add_parser("test", help="运行硬件自检").set_defaults(func=cmd_test)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
