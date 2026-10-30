# -*- coding: utf-8 -*-
"""极简 WASAPI 封装（COM / ctypes + comtypes）。

只做四件事：
  1. 枚举播放/录音端点，拿到好读的名字
  2. 打开共享模式播放流，写 PCM
  3. 打开共享模式"回环捕获"（loopback），读走某个播放端点正在播放的声音
  4. 解析端点的混音格式（mix format）

共享模式下 Windows 音频引擎自己会做重采样/声道映射，所以对一个端点只能用
"它自己的混音格式"来开流，格式转换在 numpy 里做。
"""
from __future__ import annotations

import ctypes
from ctypes import POINTER, Structure, byref, c_longlong, c_ushort, c_void_p, cast, string_at
from ctypes.wintypes import DWORD, UINT, WORD
from dataclasses import dataclass, field

import comtypes
import numpy as np
from comtypes import CLSCTX_ALL, COMMETHOD, GUID, HRESULT, IUnknown, CoCreateInstance

# ---------------------------------------------------------------- 常量
eRender = 0
eCapture = 1
eConsole = 0

DEVICE_STATE_ACTIVE = 0x00000001
DEVICE_STATE_DISABLED = 0x00000002
DEVICE_STATE_NOTPRESENT = 0x00000004
DEVICE_STATE_UNPLUGGED = 0x00000008

STGM_READ = 0

AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000

AUDCLNT_BUFFERFLAGS_SILENT = 0x00000002

VT_LPWSTR = 31

KSDATAFORMAT_SUBTYPE_IEEE_FLOAT = GUID("{00000003-0000-0010-8000-00AA00389B71}")

CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IAudioClient = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")

PKEY_Device_FriendlyName = (GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}"), 14)
PKEY_Device_DeviceDesc = (GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}"), 2)


# ---------------------------------------------------------------- 结构体
class WAVEFORMATEX(Structure):
    _pack_ = 1
    _fields_ = [
        ("wFormatTag", WORD),
        ("nChannels", WORD),
        ("nSamplesPerSec", DWORD),
        ("nAvgBytesPerSec", DWORD),
        ("nBlockAlign", WORD),
        ("wBitsPerSample", WORD),
        ("cbSize", WORD),
    ]


class WAVEFORMATEXTENSIBLE(Structure):
    _pack_ = 1
    _fields_ = [
        ("Format", WAVEFORMATEX),
        ("wValidBitsPerSample", WORD),
        ("dwChannelMask", DWORD),
        ("SubFormat", GUID),
    ]


class PROPERTYKEY(Structure):
    _fields_ = [("fmtid", GUID), ("pid", DWORD)]


class PROPVARIANT(Structure):
    _fields_ = [
        ("vt", c_ushort),
        ("wReserved1", c_ushort),
        ("wReserved2", c_ushort),
        ("wReserved3", c_ushort),
        ("p", c_void_p),
        ("pad", c_void_p),
    ]


ole32 = ctypes.windll.ole32
ole32.CoTaskMemFree.argtypes = [c_void_p]
ole32.CoTaskMemFree.restype = None
ole32.PropVariantClear.argtypes = [POINTER(PROPVARIANT)]
ole32.PropVariantClear.restype = HRESULT


# ---------------------------------------------------------------- COM 接口
class IPropertyStore(IUnknown):
    _iid_ = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(DWORD), "cProps")),
        COMMETHOD([], HRESULT, "GetAt",
                  (["in"], DWORD, "iProp"),
                  (["out"], POINTER(PROPERTYKEY), "pkey")),
        COMMETHOD([], HRESULT, "GetValue",
                  (["in"], POINTER(PROPERTYKEY), "key"),
                  (["out"], POINTER(PROPVARIANT), "pv")),
        COMMETHOD([], HRESULT, "SetValue",
                  (["in"], POINTER(PROPERTYKEY), "key"),
                  (["in"], POINTER(PROPVARIANT), "pv")),
        COMMETHOD([], HRESULT, "Commit"),
    ]


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Activate",
                  (["in"], POINTER(GUID), "iid"),
                  (["in"], DWORD, "dwClsCtx"),
                  (["in"], c_void_p, "pActivationParams"),
                  (["out"], POINTER(POINTER(IUnknown)), "ppInterface")),
        COMMETHOD([], HRESULT, "OpenPropertyStore",
                  (["in"], DWORD, "stgmAccess"),
                  (["out"], POINTER(POINTER(IPropertyStore)), "ppProperties")),
        COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(ctypes.c_wchar_p), "ppstrId")),
        COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(DWORD), "pdwState")),
    ]


class IMMDeviceCollection(IUnknown):
    _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(UINT), "pcDevices")),
        COMMETHOD([], HRESULT, "Item",
                  (["in"], UINT, "nDevice"),
                  (["out"], POINTER(POINTER(IMMDevice)), "ppDevice")),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [
        COMMETHOD([], HRESULT, "EnumAudioEndpoints",
                  (["in"], DWORD, "dataFlow"),
                  (["in"], DWORD, "dwStateMask"),
                  (["out"], POINTER(POINTER(IMMDeviceCollection)), "ppDevices")),
        COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint",
                  (["in"], DWORD, "dataFlow"),
                  (["in"], DWORD, "role"),
                  (["out"], POINTER(POINTER(IMMDevice)), "ppEndpoint")),
        COMMETHOD([], HRESULT, "GetDevice",
                  (["in"], ctypes.c_wchar_p, "pwstrId"),
                  (["out"], POINTER(POINTER(IMMDevice)), "ppDevice")),
        COMMETHOD([], HRESULT, "RegisterEndpointNotificationCallback"),
        COMMETHOD([], HRESULT, "UnregisterEndpointNotificationCallback"),
    ]


class IAudioClient(IUnknown):
    _iid_ = IID_IAudioClient
    _methods_ = [
        COMMETHOD([], HRESULT, "Initialize",
                  (["in"], ctypes.c_int, "ShareMode"),
                  (["in"], DWORD, "StreamFlags"),
                  (["in"], c_longlong, "hnsBufferDuration"),
                  (["in"], c_longlong, "hnsPeriodicity"),
                  (["in"], POINTER(WAVEFORMATEX), "pFormat"),
                  (["in"], c_void_p, "AudioSessionGuid")),
        COMMETHOD([], HRESULT, "GetBufferSize", (["out"], POINTER(UINT), "pNumBufferFrames")),
        COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], POINTER(c_longlong), "phnsLatency")),
        COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], POINTER(UINT), "pNumPaddingFrames")),
        COMMETHOD([], HRESULT, "IsFormatSupported",
                  (["in"], ctypes.c_int, "ShareMode"),
                  (["in"], POINTER(WAVEFORMATEX), "pFormat"),
                  (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppClosestMatch")),
        COMMETHOD([], HRESULT, "GetMixFormat",
                  (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppDeviceFormat")),
        COMMETHOD([], HRESULT, "GetDevicePeriod",
                  (["out"], POINTER(c_longlong), "phnsDefaultDevicePeriod"),
                  (["out"], POINTER(c_longlong), "phnsMinimumDevicePeriod")),
        COMMETHOD([], HRESULT, "Start"),
        COMMETHOD([], HRESULT, "Stop"),
        COMMETHOD([], HRESULT, "Reset"),
        COMMETHOD([], HRESULT, "SetEventHandle", (["in"], c_void_p, "eventHandle")),
        COMMETHOD([], HRESULT, "GetService",
                  (["in"], POINTER(GUID), "riid"),
                  (["out"], POINTER(POINTER(IUnknown)), "ppv")),
    ]


class IAudioRenderClient(IUnknown):
    _iid_ = GUID("{F294ACFC-3146-4483-A7BF-ADDCA7C260E2}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetBuffer",
                  (["in"], UINT, "NumFramesRequested"),
                  (["out"], POINTER(c_void_p), "ppData")),
        COMMETHOD([], HRESULT, "ReleaseBuffer",
                  (["in"], UINT, "NumFramesWritten"),
                  (["in"], DWORD, "dwFlags")),
    ]


class IAudioCaptureClient(IUnknown):
    _iid_ = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetBuffer",
                  (["out"], POINTER(c_void_p), "ppData"),
                  (["out"], POINTER(UINT), "pNumFramesToRead"),
                  (["out"], POINTER(DWORD), "pdwFlags"),
                  (["out"], POINTER(ctypes.c_ulonglong), "pu64DevicePosition"),
                  (["out"], POINTER(ctypes.c_ulonglong), "pu64QPCPosition")),
        COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], UINT, "NumFramesRead")),
        COMMETHOD([], HRESULT, "GetNextPacketSize",
                  (["out"], POINTER(UINT), "pNumFramesInNextPacket")),
    ]


# ---------------------------------------------------------------- 小工具
def _addr(x) -> int:
    """把 comtypes 返回的各种指针/整数统一成整数地址。"""
    if x is None:
        return 0
    if isinstance(x, int):
        return x
    try:
        return ctypes.cast(x, c_void_p).value or 0
    except Exception:
        try:
            return ctypes.addressof(x)
        except Exception:
            return 0


def _read_lpwstr(value) -> str:
    """GetId 之类返回的 LPWSTR，统一成 str。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return ctypes.cast(value, ctypes.c_wchar_p).value or ""
    except Exception:
        return ""


# ---------------------------------------------------------------- 格式
@dataclass
class AudioFormat:
    sample_rate: int
    channels: int
    bits: int
    is_float: bool
    block_align: int
    raw: bytes = field(repr=False, default=b"")
    channel_mask: int = 0

    @property
    def dtype(self) -> np.dtype:
        if self.is_float and self.bits == 32:
            return np.dtype("<f4")
        if self.bits == 16:
            return np.dtype("<i2")
        if self.bits == 32:
            return np.dtype("<i4")
        raise RuntimeError(f"不支持的位深 {self.bits}")

    def to_float32_stereo(self, addr: int, nframes: int) -> np.ndarray:
        if nframes <= 0:
            return np.zeros((0, 2), np.float32)
        raw = string_at(addr, nframes * self.block_align)
        a = np.frombuffer(raw, dtype=self.dtype, count=nframes * self.channels)
        a = a.reshape(nframes, self.channels).astype(np.float32)
        if not self.is_float:
            a /= float(1 << (self.bits - 1))
        if self.channels == 1:
            a = np.repeat(a, 2, axis=1)
        elif self.channels > 2:
            a = a[:, :2]
        return np.ascontiguousarray(a, dtype=np.float32)

    def describe(self) -> str:
        kind = "float" if self.is_float else "int"
        return f"{self.sample_rate} Hz / {self.channels} ch / {self.bits} bit {kind}"


def _parse_format(addr: int) -> AudioFormat:
    wfx = cast(addr, POINTER(WAVEFORMATEX)).contents
    tag, bits, mask = wfx.wFormatTag, wfx.wBitsPerSample, 0
    is_float = tag == 3
    if tag == 0xFFFE and wfx.cbSize >= 22:
        ext = cast(addr, POINTER(WAVEFORMATEXTENSIBLE)).contents
        is_float = ext.SubFormat == KSDATAFORMAT_SUBTYPE_IEEE_FLOAT
        mask = int(ext.dwChannelMask)
    return AudioFormat(
        sample_rate=int(wfx.nSamplesPerSec),
        channels=int(wfx.nChannels),
        bits=int(bits),
        is_float=bool(is_float),
        block_align=int(wfx.nBlockAlign),
        raw=string_at(addr, 18 + int(wfx.cbSize)),
        channel_mask=mask,
    )


def _wfx_ptr(raw: bytes) -> POINTER(WAVEFORMATEX):
    """格式原始字节 -> 传给 Initialize 的指针（缓冲区需存活到调用返回）。"""
    buf = ctypes.create_string_buffer(raw, len(raw))
    return cast(buf, POINTER(WAVEFORMATEX))


# ---------------------------------------------------------------- 设备
@dataclass
class Device:
    index: int
    id: str
    name: str
    state: int
    is_input: bool
    paired_name: str = ""  # 若这是已配对蓝牙设备对应的端点，填它的配对名

    @property
    def is_bt(self) -> bool:
        if self.paired_name:
            return True
        n = self.name.lower()
        return any(k in n for k in ("bluetooth", "蓝牙", "hands-free", "headset", "stereo"))

    def label(self) -> str:
        return f"{self.name}"


def _enumerator():
    return CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL)


def _device_name(dev) -> str:
    try:
        store = dev.OpenPropertyStore(STGM_READ)
    except Exception:
        return "<未知设备>"
    for fmtid, pid in (PKEY_Device_FriendlyName, PKEY_Device_DeviceDesc):
        try:
            pv = store.GetValue(byref(PROPERTYKEY(fmtid, pid)))
        except Exception:
            continue
        try:
            if pv.vt == VT_LPWSTR and pv.p:
                name = cast(pv.p, ctypes.c_wchar_p).value or ""
                if name:
                    return name
        finally:
            try:
                ole32.PropVariantClear(byref(pv))
            except Exception:
                pass
    return "<未知设备>"


def list_devices(include_disabled: bool = False) -> list[Device]:
    """枚举播放端点（is_input=False）与录音端点（is_input=True）。"""
    comtypes.CoInitialize()
    enum = _enumerator()
    out: list[Device] = []
    mask = DEVICE_STATE_ACTIVE
    if include_disabled:
        mask |= DEVICE_STATE_DISABLED | DEVICE_STATE_UNPLUGGED | DEVICE_STATE_NOTPRESENT

    for flow, is_input in ((eRender, False), (eCapture, True)):
        coll = enum.EnumAudioEndpoints(flow, mask)
        for i in range(int(coll.GetCount())):
            dev = coll.Item(i)
            out.append(
                Device(
                    index=len(out),
                    id=_read_lpwstr(dev.GetId()),
                    name=_device_name(dev),
                    state=int(dev.GetState()),
                    is_input=is_input,
                )
            )
    return out


def default_device(is_input: bool = False) -> Device | None:
    comtypes.CoInitialize()
    try:
        dev = _enumerator().GetDefaultAudioEndpoint(eCapture if is_input else eRender, eConsole)
    except comtypes.COMError:
        return None
    return Device(-1, _read_lpwstr(dev.GetId()), _device_name(dev), int(dev.GetState()), is_input)


def _open(device_id: str):
    return _enumerator().GetDevice(ctypes.c_wchar_p(device_id))


def _audio_client(device_id: str):
    return _open(device_id).Activate(byref(IID_IAudioClient), CLSCTX_ALL, None).QueryInterface(
        IAudioClient
    )


def mix_format(device: Device) -> AudioFormat:
    comtypes.CoInitialize()
    return _parse_format(_addr(_audio_client(device.id).GetMixFormat()))


# ---------------------------------------------------------------- 默认设备
CLSID_CPolicyConfigClient = GUID("{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}")
IID_IPolicyConfig = GUID("{F8679F50-850A-41CF-9C72-430F290290C8}")


class IPolicyConfig(IUnknown):
    """未公开接口，只有 SetDefaultEndpoint 是我们真正调用的。

    前 10 个方法只是为了把 vtable 位置对上，签名不影响（从不调用）。
    """

    _iid_ = IID_IPolicyConfig
    _methods_ = [
        COMMETHOD([], HRESULT, "GetMixFormat",
                  (["in"], ctypes.c_wchar_p, "id"), (["out"], POINTER(c_void_p), "p")),
        COMMETHOD([], HRESULT, "GetDeviceFormat",
                  (["in"], ctypes.c_wchar_p, "id"), (["in"], ctypes.c_int, "b"),
                  (["out"], POINTER(c_void_p), "p")),
        COMMETHOD([], HRESULT, "ResetDeviceFormat", (["in"], ctypes.c_wchar_p, "id")),
        COMMETHOD([], HRESULT, "SetDeviceFormat",
                  (["in"], ctypes.c_wchar_p, "id"), (["in"], c_void_p, "a"), (["in"], c_void_p, "b")),
        COMMETHOD([], HRESULT, "GetProcessingPeriod",
                  (["in"], ctypes.c_wchar_p, "id"), (["in"], ctypes.c_int, "b"),
                  (["out"], POINTER(c_longlong), "a"), (["out"], POINTER(c_longlong), "c")),
        COMMETHOD([], HRESULT, "SetProcessingPeriod",
                  (["in"], ctypes.c_wchar_p, "id"), (["in"], POINTER(c_longlong), "p")),
        COMMETHOD([], HRESULT, "GetShareMode",
                  (["in"], ctypes.c_wchar_p, "id"), (["out"], POINTER(c_void_p), "p")),
        COMMETHOD([], HRESULT, "SetShareMode",
                  (["in"], ctypes.c_wchar_p, "id"), (["in"], c_void_p, "p")),
        COMMETHOD([], HRESULT, "GetPropertyValue",
                  (["in"], ctypes.c_wchar_p, "id"),
                  (["in"], POINTER(PROPERTYKEY), "key"),
                  (["out"], POINTER(PROPVARIANT), "pv")),
        COMMETHOD([], HRESULT, "SetPropertyValue",
                  (["in"], ctypes.c_wchar_p, "id"),
                  (["in"], POINTER(PROPERTYKEY), "key"),
                  (["in"], POINTER(PROPVARIANT), "pv")),
        COMMETHOD([], HRESULT, "SetDefaultEndpoint",
                  (["in"], ctypes.c_wchar_p, "id"), (["in"], ctypes.c_int, "role")),
        COMMETHOD([], HRESULT, "SetEndpointVisibility",
                  (["in"], ctypes.c_wchar_p, "id"), (["in"], ctypes.c_int, "visible")),
    ]


def set_default_device(device_id: str, role: int = eConsole) -> bool:
    """把系统默认播放设备切到指定端点（eConsole/eMultimedia/eCommunications 都设）。"""
    comtypes.CoInitialize()
    try:
        policy = CoCreateInstance(CLSID_CPolicyConfigClient, IPolicyConfig, CLSCTX_ALL)
        for r in (0, 1, 2):
            policy.SetDefaultEndpoint(device_id, r)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 播放流
class RenderStream:
    """共享模式播放流。"""

    def __init__(self, device: Device, buffer_ms: int = 200):
        self.device = device
        comtypes.CoInitialize()
        self.client = _audio_client(device.id)
        fmt = _parse_format(_addr(self.client.GetMixFormat()))
        self.format = fmt
        self.client.Initialize(
            AUDCLNT_SHAREMODE_SHARED, 0, int(buffer_ms * 10000), 0, _wfx_ptr(fmt.raw), None
        )
        self.buffer_frames = int(self.client.GetBufferSize())
        self.render = self.client.GetService(byref(IAudioRenderClient._iid_)).QueryInterface(
            IAudioRenderClient
        )
        self._started = False

    def start(self) -> None:
        if not self._started:
            self.client.Start()
            self._started = True

    def stop(self) -> None:
        if self._started:
            try:
                self.client.Stop()
            finally:
                self._started = False

    def padding(self) -> int:
        return int(self.client.GetCurrentPadding())

    def free_frames(self) -> int:
        return self.buffer_frames - self.padding()

    def write(self, nframes: int, stereo: np.ndarray | None) -> None:
        if nframes <= 0:
            return
        addr = _addr(self.render.GetBuffer(nframes))
        if not addr:
            return
        if stereo is None:
            ctypes.memset(addr, 0, nframes * self.format.block_align)
            self.render.ReleaseBuffer(nframes, AUDCLNT_BUFFERFLAGS_SILENT)
            return
        data = self._encode(stereo[:nframes])
        ctypes.memmove(addr, data, min(len(data), nframes * self.format.block_align))
        self.render.ReleaseBuffer(nframes, 0)

    def _encode(self, stereo: np.ndarray) -> bytes:
        fmt = self.format
        x = stereo
        if fmt.channels == 1:
            x = x.mean(axis=1, keepdims=True)
        elif fmt.channels > 2:
            x = np.concatenate([x, np.zeros((x.shape[0], fmt.channels - 2), np.float32)], axis=1)
        if fmt.is_float:
            return np.ascontiguousarray(x, dtype="<f4").tobytes()
        if fmt.bits == 16:
            return (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        return (np.clip(x, -1.0, 1.0) * 2147483647.0).astype("<i4").tobytes()

    def close(self) -> None:
        try:
            self.stop()
        except Exception:
            pass


# ---------------------------------------------------------------- 捕获流
class LoopbackCapture:
    """捕获某个播放端点正在播放的声音（WASAPI loopback）。"""

    def __init__(self, device: Device, buffer_ms: int = 500):
        self.device = device
        comtypes.CoInitialize()
        self.client = _audio_client(device.id)
        fmt = _parse_format(_addr(self.client.GetMixFormat()))
        self.format = fmt
        self.client.Initialize(
            AUDCLNT_SHAREMODE_SHARED,
            AUDCLNT_STREAMFLAGS_LOOPBACK,
            int(buffer_ms * 10000),
            0,
            _wfx_ptr(fmt.raw),
            None,
        )
        self.buffer_frames = int(self.client.GetBufferSize())
        self.capture = self.client.GetService(byref(IAudioCaptureClient._iid_)).QueryInterface(
            IAudioCaptureClient
        )
        self._started = False

    def start(self) -> None:
        if not self._started:
            self.client.Start()
            self._started = True

    def stop(self) -> None:
        if self._started:
            try:
                self.client.Stop()
            finally:
                self._started = False

    def read(self) -> np.ndarray | None:
        """读走当前所有可用帧，返回 (n,2) float32 或 None。"""
        chunks = []
        while True:
            packet = int(self.capture.GetNextPacketSize())
            if packet == 0:
                break
            addr, frames, flags, _pos, _qpc = self.capture.GetBuffer()
            frames = int(frames)
            try:
                if frames > 0:
                    if int(flags) & AUDCLNT_BUFFERFLAGS_SILENT:
                        chunks.append(np.zeros((frames, 2), np.float32))
                    else:
                        chunks.append(self.format.to_float32_stereo(_addr(addr), frames))
            finally:
                self.capture.ReleaseBuffer(frames)
        if not chunks:
            return None
        return chunks[0] if len(chunks) == 1 else np.concatenate(chunks, axis=0)

    def close(self) -> None:
        try:
            self.stop()
        except Exception:
            pass


# ---------------------------------------------------------------- 自检
def _selftest() -> int:
    import time

    print("=== 播放端点 ===")
    devs = list_devices()
    outs = [d for d in devs if not d.is_input]
    ins = [d for d in devs if d.is_input]
    dflt = default_device(False)
    for d in outs:
        mark = "*" if dflt and d.id == dflt.id else " "
        try:
            desc = mix_format(d).describe()
        except Exception as e:
            desc = f"<打不开: {e}>"
        print(f" {mark}[{d.index:2d}] {d.name}  <- {desc}")
    print("\n=== 录音端点 ===")
    for d in ins:
        print(f"  [{d.index:2d}] {d.name}")
    if not outs:
        print("\n没有可用的播放端点")
        return 1

    target = dflt if dflt else outs[0]
    print(f"\n=== 在【{target.name}】播放 1.5 秒 440Hz，同时回环捕获 ===")
    try:
        rs = RenderStream(target)
        cap = LoopbackCapture(target)
    except Exception:
        import traceback

        traceback.print_exc()
        return 3
    print(f"播放格式 {rs.format.describe()} / 捕获格式 {cap.format.describe()}")
    cap.start()
    rs.start()
    sr = cap.format.sample_rate
    t, got, peak = 0.0, 0, 0.0
    t0 = time.time()
    while time.time() - t0 < 1.5:
        n = rs.free_frames()
        if n > 0:
            n = min(n, 480)
            phase = (t + np.arange(n) / sr) * 2 * np.pi * 440
            tone = (0.2 * np.sin(phase)).astype(np.float32)
            rs.write(n, np.stack([tone, tone], axis=1))
            t += n / sr
        chunk = cap.read()
        if chunk is not None:
            got += len(chunk)
            peak = max(peak, float(np.max(np.abs(chunk))))
        time.sleep(0.004)
    rs.close()
    cap.close()
    print(f"捕获 {got} 帧 = {got / sr:.2f} 秒，峰值 {peak:.3f}")
    ok = got > sr * 0.2 and peak > 0.01
    print("自检：", "通过" if ok else "未捕获到声音（可能是虚拟设备或没有真实输出）")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(_selftest())
