# -*- coding: utf-8 -*-
"""蓝牙能力体检。

回答一个具体问题：这台电脑能不能同时连两只蓝牙音箱、并把它们当两个独立输出用。

数据来源（全部只读，不需要装任何东西）：
  * HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion      -> 系统版本
  * HKLM\\SYSTEM\\...\\Enum\\USB + Class\\{蓝牙类GUID}          -> 适配器型号与驱动
  * HKLM\\SYSTEM\\...\\Services\\BTHPORT\\Parameters\\Devices  -> 已配对设备、COD、LMP 版本、上次连接时间
  * WASAPI 端点枚举                                            -> 当前真正可用的播放端点
"""
from __future__ import annotations

import ctypes
import datetime as dt
import winreg

from .wasapi import DEVICE_STATE_ACTIVE, list_devices

BT_CLASS_GUID = "{e0cbf06c-cd8b-4647-bb8a-263b43f0f974}"
NET_CLASS_GUID = "{4d36e972-e325-11ce-bfc1-08002be10318}"

# 音频类设备的次要类型（COD bits 2-7）
AUDIO_MINOR = {
    0: "未分类音频",
    1: "头戴式耳机/头戴设备",
    2: "免手操设备",
    4: "麦克风",
    5: "音箱",
    6: "耳机",
    7: "便携音频",
    8: "车载音响",
    9: "机顶盒",
    10: "HiFi 音频",
    15: "显示器/电视",
    18: "游戏/玩具",
}
MAJOR = {
    0: "杂项", 1: "电脑", 2: "手机", 3: "局域网", 4: "音频/视频",
    5: "外设", 6: "成像", 7: "穿戴", 8: "玩具", 9: "健康",
}

# 常见 Intel 组合模块对应的蓝牙版本（仅用于给个参考，识别不到就不显示）
COMBO_BT = {
    "AX201": "5.2", "AX200": "5.1", "AX210": "5.3", "AX211": "5.3",
    "AX411": "5.3", "BE200": "5.4", "BE201": "5.4", "9560": "5.0", "8265": "4.2",
}

# LMP version -> 蓝牙核心规范
LMP_VERSION = {
    0: "1.0b", 1: "1.1", 2: "1.2", 3: "2.0", 4: "2.1", 5: "3.0",
    6: "4.0", 7: "4.1", 8: "4.2", 9: "5.0", 10: "5.1", 11: "5.2",
    12: "5.3", 13: "5.4",
}


# ---------------------------------------------------------------- 注册表小工具
def _reg(path: str, value: str):
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            return winreg.QueryValueEx(key, value)[0]
    except OSError:
        return None


def _reg_subkeys(path: str) -> list[str]:
    out = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            i = 0
            while True:
                try:
                    out.append(winreg.EnumKey(key, i))
                except OSError:
                    break
                i += 1
    except OSError:
        pass
    return out


def _reg_values(path: str) -> dict:
    out = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                out[name] = value
                i += 1
    except OSError:
        pass
    return out


# ---------------------------------------------------------------- 设备是否在位
_cfgmgr = ctypes.WinDLL("cfgmgr32")
_cfgmgr.CM_Locate_DevNodeW.argtypes = [
    ctypes.POINTER(ctypes.c_uint32), ctypes.c_wchar_p, ctypes.c_uint32
]
_cfgmgr.CM_Locate_DevNodeW.restype = ctypes.c_uint32
_cfgmgr.CM_Get_DevNode_Status.argtypes = [
    ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32),
    ctypes.c_uint32, ctypes.c_uint32,
]
_cfgmgr.CM_Get_DevNode_Status.restype = ctypes.c_uint32

DN_HAS_PROBLEM = 0x00000400


def _devnode_state(instance_id: str) -> tuple[bool, int]:
    """返回 (是否在位, 问题码)。"""
    devinst = ctypes.c_uint32()
    if _cfgmgr.CM_Locate_DevNodeW(ctypes.byref(devinst), instance_id, 0) != 0:
        return False, 0
    status, problem = ctypes.c_uint32(), ctypes.c_uint32()
    if _cfgmgr.CM_Get_DevNode_Status(ctypes.byref(status), ctypes.byref(problem),
                                    devinst, 0) != 0:
        return False, 0
    return True, (int(problem) if status.value & DN_HAS_PROBLEM else 0)


# ---------------------------------------------------------------- 各段数据
def os_info() -> dict:
    p = "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion"
    build = int(_reg(p, "CurrentBuild") or 0)
    ubr = int(_reg(p, "UBR") or 0)
    name = _reg(p, "ProductName") or "Windows"
    # Win11 的注册表里 ProductName 仍是 "Windows 10"，靠 build 号纠正
    if build >= 22000:
        name = name.replace("Windows 10", "Windows 11")
    return {
        "name": name,
        "release": _reg(p, "DisplayVersion") or "",
        "build": f"{build}.{ubr}" if ubr else str(build),
    }


def bluetooth_radios() -> list[dict]:
    """从 Enum\\USB 里找蓝牙类设备，再用内核接口确认是否在位。"""
    radios = []
    for vidpid in _reg_subkeys("SYSTEM\\CurrentControlSet\\Enum\\USB"):
        for inst in _reg_subkeys(f"SYSTEM\\CurrentControlSet\\Enum\\USB\\{vidpid}"):
            path = f"SYSTEM\\CurrentControlSet\\Enum\\USB\\{vidpid}\\{inst}"
            vals = _reg_values(path)
            # 实例键里没有 Class，只有 ClassGUID；蓝牙类 = e0cbf06c-...
            if str(vals.get("ClassGUID", "")).lower() != BT_CLASS_GUID:
                continue
            inst_id = f"USB\\{vidpid}\\{inst}"
            present, problem = _devnode_state(inst_id)
            drv = str(vals.get("Driver", ""))
            cls_path = f"SYSTEM\\CurrentControlSet\\Control\\Class\\{drv}" if drv else ""
            desc = str(vals.get("DeviceDesc", ""))
            radios.append({
                "name": (vals.get("FriendlyName") or desc.split(";")[-1] or "蓝牙适配器"),
                "instance": inst_id,
                "driver_version": _reg(cls_path, "DriverVersion") if cls_path else None,
                "provider": _reg(cls_path, "ProviderName") if cls_path else None,
                "present": present,
                "problem": problem,
            })
    # 在位的排前面
    radios.sort(key=lambda r: (not r["present"], r["problem"] != 0))
    return radios


def wifi_modules() -> list[str]:
    out = []
    for sub in _reg_subkeys(f"SYSTEM\\CurrentControlSet\\Control\\Class\\{NET_CLASS_GUID}"):
        path = f"SYSTEM\\CurrentControlSet\\Control\\Class\\{NET_CLASS_GUID}\\{sub}"
        desc = _reg(path, "DriverDesc")
        if not desc:
            continue
        desc = str(desc)
        if "Virtual" in desc or "Wi-Fi Direct" in desc:
            continue
        if any(k in desc for k in ("Wi-Fi", "WiFi", "Wireless", "无线")) and desc not in out:
            out.append(desc)
    return out


def _decode_name(raw) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace").rstrip("\x00").strip()
    if isinstance(raw, str):
        return raw.strip()
    return ""


def _filetime(value) -> dt.datetime | None:
    try:
        v = int(value)
        if v <= 0:
            return None
        return dt.datetime(1601, 1, 1) + dt.timedelta(microseconds=v // 10)
    except Exception:
        return None


def _human_ago(when: dt.datetime | None) -> str:
    if not when:
        return "未知"
    delta = dt.datetime.now() - when
    secs = delta.total_seconds()
    if secs < 0:
        return "刚刚"
    if secs < 90:
        return "刚刚"
    if secs < 3600:
        return f"{int(secs // 60)} 分钟前"
    if secs < 86400:
        return f"{int(secs // 3600)} 小时前"
    if delta.days < 30:
        return f"{delta.days} 天前"
    return when.strftime("%Y-%m-%d")


def paired_devices() -> list[dict]:
    base = "SYSTEM\\CurrentControlSet\\Services\\BTHPORT\\Parameters\\Devices"
    devs = []
    for mac in _reg_subkeys(base):
        vals = _reg_values(f"{base}\\{mac}")
        if not vals:
            continue
        name = _decode_name(vals.get("Name")) or _decode_name(vals.get("LEName"))
        if not name:
            continue
        cod = int(vals.get("COD") or 0)
        major = (cod >> 8) & 0x1F
        minor = (cod >> 2) & 0x3F
        lmp = int(vals.get("LmpVersion") or 0)
        devs.append({
            "mac": mac.upper(),
            "name": name,
            "cod": cod,
            "kind": MAJOR.get(major, f"类别{major}"),
            "subkind": AUDIO_MINOR.get(minor, "") if major == 4 else "",
            "is_audio": major == 4,
            "lmp": LMP_VERSION.get(lmp, f"未知({lmp})" if lmp else "未知"),
            "last": _filetime(vals.get("LastConnected")),
        })
    devs.sort(key=lambda d: (not d["is_audio"], -(d["last"].timestamp() if d["last"] else 0)))
    return devs


def _endpoints() -> list:
    return [d for d in list_devices() if not d.is_input and d.state == DEVICE_STATE_ACTIVE]


def annotate_bluetooth(devices: list) -> list:
    """给端点打上"它对应哪个已配对蓝牙设备"的标记。

    Windows 的蓝牙端点名字（如 `耳机 (DOME 2)`）里没有 Bluetooth 字样，
    只能靠配对记录反查，否则界面会把板载声卡误当成音箱。
    """
    try:
        paired = paired_devices()
    except Exception:
        return devices
    audio = [p for p in paired if p["is_audio"]]
    for d in devices:
        if d.is_input or d.paired_name:
            continue
        hit = next((p for p in audio if p["name"].lower() in d.name.lower()), None)
        if hit:
            d.paired_name = hit["name"]
    return devices


def _hands_free(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in ("hands-free", "免手操", "handsfree", "headset earphone"))


def _stereo(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in ("stereo", "立体声", "a2dp"))


def classify(eps: list, paired: list[dict]) -> tuple[list, list]:
    """把播放端点分成 (已连上的蓝牙端点, 其它)。"""
    bt, other = [], []
    for ep in eps:
        hit = next((p for p in paired if p["name"].lower() in ep.name.lower()), None)
        if hit:
            bt.append((ep, hit))
        else:
            other.append(ep)
    return bt, other


# ---------------------------------------------------------------- 报告
def build_report() -> tuple[str, bool | None]:
    lines: list[str] = []
    add = lines.append

    eps = _endpoints()
    paired = paired_devices()
    bt_eps, other = classify(eps, paired)
    connected = {p["name"] for _, p in bt_eps}

    osi = os_info()
    add("=== 系统 ===")
    add(f"{osi['name']} {osi['release']}  (Build {osi['build']})")
    add("")

    add("=== 蓝牙适配器 ===")
    radios = bluetooth_radios()
    for r in radios:
        if r["present"] and not r["problem"]:
            mark = "正常"
        elif r["present"]:
            mark = f"有问题（代码 {r['problem']}）"
        else:
            mark = "未使用/未连接"
        add(f"[{mark}] {r['name']}")
        add(f"         驱动 {r['driver_version'] or '?'} · {r['provider'] or '?'}")
        add(f"         {r['instance']}")
    if not radios:
        add("没有发现蓝牙适配器：可能被禁用或驱动未安装。")

    for w in wifi_modules():
        bt_ver = next((v for k, v in COMBO_BT.items() if k in w), None)
        add(f"组合模块：{w}" + (f"  （蓝牙 {bt_ver}）" if bt_ver else ""))
    add("")

    add("=== 已配对设备 ===")
    if not paired:
        add("读不到配对记录（可能需要管理员权限），下面只按当前端点判断。")
    audio_devs = [p for p in paired if p["is_audio"]]
    other_devs = [p for p in paired if not p["is_audio"]]
    if not audio_devs and other_devs:
        add("没有任何音频类已配对设备。")
    for p in audio_devs:
        state = "● 已连接" if p["name"] in connected else "○ 未连接"
        kind = p["subkind"] or p["kind"]
        add(f"{state}  {p['name']:<16} {kind:<12} 蓝牙 {p['lmp']:<4} 上次 {_human_ago(p['last'])}")
    if other_devs:
        add(f"（另有 {len(other_devs)} 个非音频设备：鼠标/键盘/手机等，已省略）")
    add("")

    add("=== 当前播放端点 ===")
    for ep, p in bt_eps:
        add(f"  [蓝牙] {ep.name}    ← 已配对设备 “{p['name']}”")
    for ep in other:
        add(f"         {ep.name}")
    add("")

    # ------------------------------------------------------------ 判定
    add("=== 结论 ===")
    verdict: bool | None
    if not any(r["present"] and not r["problem"] for r in radios):
        add("✘ 蓝牙适配器没有正常工作，先解决驱动/禁用问题。")
        verdict = False
    elif len(bt_eps) >= 2:
        hf = [ep.name for ep, _ in bt_eps if _hands_free(ep.name)]
        add(f"✔ 当前有 {len(bt_eps)} 只蓝牙音箱同时在线，硬件和驱动支持双连。")
        add("  直接双击 启动.bat，把这两只选成左/右声道即可。")
        if hf:
            add(f"  ⚠ 其中 {hf} 是“免手操”端点，要选 Stereo/立体声 那个。")
        verdict = True
    elif len(bt_eps) == 1:
        ep, p = bt_eps[0]
        others = [x["name"] for x in audio_devs if x["name"] != p["name"]]
        add(f"△ 只连上了 1 只：{ep.name}")
        add(f"  另一只（{'、'.join(others) or '没有其它已配对的音频设备'}）还没连上。")
        add("  先连一只 → 等 5 秒 → 再连另一只；仍然只有一只就加个 USB 蓝牙 5.3 适配器。")
        verdict = False
    else:
        add("✘ 现在没有任何蓝牙音箱连着（配对过 ≠ 已连接）。")
        if audio_devs:
            add(f"  去 设置 → 蓝牙和设备，把 {'、'.join(x['name'] for x in audio_devs)} 都点“连接”。")
        else:
            add("  还没有配对过蓝牙音箱，先去设置里配对两只。")
        verdict = False

    # 采样率一致性提醒
    if len(bt_eps) >= 2:
        from .wasapi import mix_format

        rates = {}
        for ep, _ in bt_eps:
            try:
                rates[ep.name] = mix_format(ep).sample_rate
            except Exception:
                pass
        if len(set(rates.values())) > 1:
            add(f"  ⚠ 两只音箱采样率不同：{rates}，程序会自动重采样，延迟差会略大。")

    return "\n".join(lines), verdict

    # 采样率一致性提醒（两台设备采样率不同会多一层重采样）
    rates = {}
    from .wasapi import mix_format

    for ep, _ in bt_eps:
        try:
            rates[ep.name] = mix_format(ep).sample_rate
        except Exception:
            pass
    if len(set(rates.values())) > 1:
        add(f"  ⚠ 两只音箱采样率不同：{rates}，程序会自动重采样，可能有极轻微延迟差。")

    return "\n".join(lines), verdict


def main() -> int:
    text, ok = build_report()
    print(text)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
