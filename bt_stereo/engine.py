# -*- coding: utf-8 -*-
"""左右声道分离引擎。

数据流：

    某个播放端点的回环捕获 ──► 环形缓冲 ──┬─► 左声道读取器 ──► 音箱 A（把左声道复制成双声道）
                                        └─► 右声道读取器 ──► 音箱 B（把右声道复制成双声道）

两只蓝牙音箱是两个独立的时钟，长时间播放会各自"跑快/跑慢"几十毫秒，所以每个
读取器都带一个慢速的比例微调（相当于 ±0.3% 的变速），把缓冲区水位拉回目标值，
避免爆音或逐渐错位。两只音箱的固定延迟差用 --delay-left / --delay-right 补。
"""
from __future__ import annotations

import ctypes
import threading
import time
from dataclasses import dataclass, field

import comtypes
import numpy as np

from .wasapi import Device, LoopbackCapture, RenderStream


class Ring:
    """定长环形缓冲，按绝对帧号寻址，允许多个读者独立读取。"""

    def __init__(self, capacity_frames: int):
        self.cap = int(capacity_frames)
        self.buf = np.zeros((self.cap, 2), np.float32)
        self.written = 0  # 累计写入帧数（绝对）
        self.lock = threading.Lock()

    def push(self, data: np.ndarray) -> None:
        n = len(data)
        if n == 0:
            return
        if n >= self.cap:
            data = data[-self.cap :]
            n = self.cap
        with self.lock:
            idx = (self.written + np.arange(n)) % self.cap
            self.buf[idx] = data
            self.written += n

    def available(self, pos: float) -> int:
        with self.lock:
            return max(0, int(self.written - pos))


class SideReader:
    """一个输出端的读取器：声道提取 + 变速补偿 + 固定延迟。"""

    def __init__(
        self,
        ring: Ring,
        out_rate: int,
        src_rate: int,
        side: str,
        delay_ms: float = 0.0,
        target_ms: float = 80.0,
        max_adj: float = 0.01,
    ):
        self.ring = ring
        self.side = side  # 'left' | 'right' | 'both'
        self.src_rate = src_rate
        self.out_rate = out_rate
        # 每个"输出帧"需要消耗多少"源帧"：源 48k -> 输出 44.1k 时是 1.088
        # （写反了会把声音拉慢/拉快，44.1k 的音箱会整体降调 8%）
        self.rate_ratio = src_rate / float(out_rate)
        self.correction = 1.0
        self.max_adj = max_adj
        # 水位以"源帧"计量，所以用 src_rate 换算
        self.target = target_ms * src_rate / 1000.0
        # 延迟补的是输出侧静音，用 out_rate
        self.pending = int(delay_ms * out_rate / 1000.0)
        self.pos = 0.0
        self.underruns = 0
        self.resyncs = 0
        self.priming = True
        self.min_fill = self.target * 0.3
        self._init_pos = False
        self._ran = False
        self._last_t = 0.0
        self._low_since = 0.0

    def _pick(self, frames: np.ndarray) -> np.ndarray:
        if self.side == "left":
            return np.repeat(frames[:, 0:1], 2, axis=1)
        if self.side == "right":
            return np.repeat(frames[:, 1:2], 2, axis=1)
        return frames

    def take(self, n: int, ring: Ring) -> np.ndarray:
        out = np.zeros((n, 2), np.float32)
        if self.pending > 0:
            skip = min(n, self.pending)
            self.pending -= skip
            if skip == n:
                return out
            start = skip
        else:
            start = 0

        with ring.lock:
            written = ring.written
            if not self._init_pos:
                self.pos = float(written)
                self._init_pos = True
            fill = written - self.pos

            if fill < -2:  # 被写者超越了（不应该发生）
                self.pos = float(written)
                fill = 0.0
            if fill > self.target + 0.5 * self.src_rate:  # 落后半秒以上，直接回到目标水位
                self.pos = float(written - int(self.target))
                self.resyncs += 1
                fill = float(self.target)

            # 预缓冲：源没有声音（或刚启动）时先输出静音，等水位攒到目标再开声。
            if self.priming:
                if fill >= self.target:
                    self.priming = False
                else:
                    return out
            else:
                # 关键：回环数据常常是"成块"到达的，瞬时低水位不能当成空闲，
                # 否则会反复停-等，把连续的音乐切成一串短促的碎片。
                # 只有低水位持续 300ms 以上，才认为是源真的没声音了，重新预缓冲。
                if fill >= self.min_fill:
                    self._low_since = 0.0
                else:
                    now = time.monotonic()
                    if self._low_since == 0.0:
                        self._low_since = now
                    elif now - self._low_since > 0.3:
                        self.priming = True
                        self._low_since = 0.0
                        if self._ran:
                            self.underruns += 1
                        return out

            # 水位误差 -> 轻微变速。目标是弥补两只音箱的时钟差（通常 0.1%~0.5%），
            # 但音高变化必须"滑行"，否则一按开始就能听出跑调。
            err = (fill - self.target) / max(self.target, 1.0)
            target_corr = float(
                np.clip(1.0 + err * 0.05, 1.0 - self.max_adj, 1.0 + self.max_adj)
            )
            now = time.monotonic()
            dt = min(0.2, now - self._last_t) if self._last_t else 0.01
            self._last_t = now
            max_step = 0.002 * dt  # 每秒最多 ±0.2%
            self.correction += float(
                np.clip(target_corr - self.correction, -max_step, max_step)
            )

            m = n - start
            step_unit = self.rate_ratio * self.correction
            advance = m * step_unit
            need = int(advance) + 2
            if fill < need:
                # 缓冲不够：能放多少放多少，剩下的用静音补齐，避免整块掉音
                m = int(max(0.0, (fill - 2)) / step_unit)
                if m <= 0:
                    self.priming = True
                    return out
                advance = m * step_unit
            if m <= 0:
                return out

            step = advance / m
            idx = self.pos + np.arange(m) * step
            base = np.floor(idx).astype(np.int64)
            frac = (idx - base).astype(np.float32)[:, None]
            i0 = (base % ring.cap).astype(np.int64)
            i1 = ((base + 1) % ring.cap).astype(np.int64)
            frames = ring.buf[i0] * (1.0 - frac) + ring.buf[i1] * frac
            self.pos += advance
            self._ran = True

        out[start : start + m] = self._pick(frames)
        return out

    def reset(self) -> None:
        """设备重连后重新对齐：回到当前写入位置，重新预缓冲。"""
        self.pos = 0.0
        self._init_pos = False
        self.priming = True
        self.correction = 1.0
        self._last_t = 0.0


@dataclass
class EngineConfig:
    source: Device
    left: Device
    right: Device
    mode: str = "lr"  # lr | swap | duplicate
    gain: float = 1.0
    left_delay_ms: float = 0.0
    right_delay_ms: float = 0.0
    target_ms: float = 120.0
    ring_seconds: float = 3.0


@dataclass
class EngineStats:
    running: bool = False
    level: float = 0.0
    captured_frames: int = 0
    underruns_left: int = 0
    underruns_right: int = 0
    fill_ms_left: float = 0.0
    fill_ms_right: float = 0.0
    error: str = ""
    left_state: str = "正常"
    right_state: str = "正常"
    capture_state: str = "正常"


class StereoEngine:
    def __init__(self, cfg: EngineConfig):
        self.cfg = cfg
        self.ring = Ring(int(48000 * max(cfg.ring_seconds, 1.0)))
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._stats = EngineStats()
        self._lock = threading.Lock()
        self._readers: dict[str, SideReader] = {}
        self._streams: dict[str, RenderStream] = {}
        self._src_rate = 48000
        self._timer_raised = False

    # ---------------------------------------------------------------- 生命周期
    def start(self) -> None:
        if self._stats.running:
            return
        # Windows 默认定时器精度是 15.6ms，音频线程的 sleep 会被拖成"一阵一阵"，
        # 听感上就是卡顿/爆音。提到 1ms 能显著改善（很多播放器也这么做）。
        try:
            ctypes.windll.winmm.timeBeginPeriod(1)
            self._timer_raised = True
        except Exception:
            self._timer_raised = False
        comtypes.CoInitialize()
        try:
            src_rate = self._probe_rate(self.cfg.source)
        finally:
            comtypes.CoUninitialize()

        mode = self.cfg.mode
        left_side = "both" if mode == "duplicate" else ("right" if mode == "swap" else "left")
        right_side = "both" if mode == "duplicate" else ("left" if mode == "swap" else "right")

        left_rate = self._probe_rate(self.cfg.left)
        right_rate = self._probe_rate(self.cfg.right)
        self._src_rate = src_rate

        self._readers = {
            "left": SideReader(self.ring, left_rate, src_rate, left_side,
                               self.cfg.left_delay_ms, self.cfg.target_ms),
            "right": SideReader(self.ring, right_rate, src_rate, right_side,
                                self.cfg.right_delay_ms, self.cfg.target_ms),
        }
        self._stop.clear()
        self._stats = EngineStats(running=True, error="")
        self._threads = [
            threading.Thread(target=self._capture_worker, name="capture", daemon=True),
            threading.Thread(target=self._render_worker, args=("left", self.cfg.left),
                             name="render-left", daemon=True),
            threading.Thread(target=self._render_worker, args=("right", self.cfg.right),
                             name="render-right", daemon=True),
        ]
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2.0)
        self._threads = []
        for s in list(self._streams.values()):
            s.close()
        self._streams.clear()
        if self._timer_raised:
            try:
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass
            self._timer_raised = False
        with self._lock:
            self._stats.running = False

    @property
    def running(self) -> bool:
        return self._stats.running

    def stats(self) -> EngineStats:
        with self._lock:
            st = EngineStats(**self._stats.__dict__)
        sr_l = self._readers.get("left")
        sr_r = self._readers.get("right")
        if sr_l:
            st.underruns_left, st.fill_ms_left = sr_l.underruns, self._fill_ms(sr_l, "left")
        if sr_r:
            st.underruns_right, st.fill_ms_right = sr_r.underruns, self._fill_ms(sr_r, "right")
        return st

    def _fill_ms(self, reader: SideReader, side: str) -> float:
        # 环形缓冲里存的是"源帧"，用源采样率换算才对
        rate = float(reader.src_rate or 48000)
        return max(0.0, self.ring.available(reader.pos) / rate * 1000.0)

    @staticmethod
    def _probe_rate(dev: Device) -> int:
        """取端点的采样率；设备此刻不在位也不算致命，先按 48k 起步。"""
        from .wasapi import mix_format

        try:
            return mix_format(dev).sample_rate
        except Exception:
            return 48000

    # ---------------------------------------------------------------- 线程
    def _resolve(self, device: Device) -> Device | None:
        """按名字重新找端点。蓝牙重连后 WASAPI 的设备 id 会变，不能缓存。"""
        from .wasapi import DEVICE_STATE_ACTIVE, list_devices

        try:
            for d in list_devices():
                if not d.is_input and d.state == DEVICE_STATE_ACTIVE and d.name == device.name:
                    return d
        except Exception:
            pass
        return None

    def _set_state(self, key: str, text: str) -> None:
        with self._lock:
            setattr(self._stats, key, text)

    def _capture_worker(self) -> None:
        comtypes.CoInitialize()
        cap = None
        try:
            while not self._stop.is_set():
                if cap is None:
                    dev = self._resolve(self.cfg.source)
                    if dev is None:
                        self._set_state("capture_state", "音源离线")
                        time.sleep(1.0)
                        continue
                    try:
                        cap = LoopbackCapture(dev, buffer_ms=200)
                        cap.start()
                        self._set_state("capture_state", "正常")
                    except Exception:
                        cap = None
                        self._set_state("capture_state", "音源被占用")
                        time.sleep(1.0)
                        continue
                try:
                    chunk = cap.read()
                except Exception:
                    try:
                        cap.close()
                    except Exception:
                        pass
                    cap = None
                    self._set_state("capture_state", "重连中")
                    time.sleep(0.3)
                    continue

                if chunk is not None and len(chunk):
                    if self.cfg.gain != 1.0:
                        chunk = chunk * self.cfg.gain
                    self.ring.push(chunk)
                    lvl = float(np.sqrt(np.mean(chunk * chunk)))
                    with self._lock:
                        self._stats.captured_frames += len(chunk)
                        self._stats.level = lvl
                else:
                    with self._lock:
                        self._stats.level *= 0.90
                time.sleep(0.004)
        finally:
            if cap is not None:
                cap.close()
            comtypes.CoUninitialize()

    def _render_worker(self, side: str, device: Device) -> None:
        comtypes.CoInitialize()
        stream = None
        reader = self._readers[side]
        key = f"{side}_state"
        target_frames = int(self.cfg.target_ms * self._src_rate / 1000.0)
        try:
            while not self._stop.is_set():
                if stream is None:
                    dev = self._resolve(device)
                    if dev is None:
                        self._set_state(key, "音箱离线")
                        time.sleep(1.0)
                        continue
                    try:
                        stream = RenderStream(dev, buffer_ms=260)
                        stream.start()
                    except Exception:
                        stream = None
                        self._set_state(key, "设备被占用")
                        time.sleep(1.0)
                        continue
                    self._streams[side] = stream
                    reader.reset()  # 重连后重新对齐，别把旧数据倒出来
                    self._set_state(key, "正常")
                    min_chunk = max(1, int(stream.format.sample_rate * 0.012))
                    # 预热：先用静音把设备缓冲填满，等环形缓冲攒到目标水位。
                    # 否则第一次会取走整段缓冲，水位掉到 0，之后一直贴着欠载跑。
                    deadline = time.time() + 2.0
                    while not self._stop.is_set() and time.time() < deadline:
                        if self.ring.written >= target_frames:
                            break
                        free = stream.free_frames()
                        if free > 0:
                            stream.write(free, None)
                        time.sleep(0.002)

                try:
                    free = stream.free_frames()
                    # 攒到 12ms 以上再写：调用次数少一个数量级，Python 线程调度压力小，
                    # 蓝牙端不容易被"喂得太碎"导致断音。
                    if free < min_chunk:
                        time.sleep(0.002)
                        continue
                    frames = reader.take(free, self.ring)
                    stream.write(free, frames)
                    time.sleep(0.001)
                except Exception:
                    # 单只音箱掉线：只关这一路，另一路继续出声，然后自动重连
                    try:
                        stream.close()
                    except Exception:
                        pass
                    stream = None
                    self._streams.pop(side, None)
                    self._set_state(key, "重连中")
                    time.sleep(0.3)
        finally:
            if stream is not None:
                stream.close()
            self._streams.pop(side, None)
            comtypes.CoUninitialize()
