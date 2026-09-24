"""Windows: WASAPI デバイスループバックによる音声キャプチャ(フォールバック)。

通常は windows_process.py のプロセス単位ループバック(SPEC §4-2)が使われる。
これはプロセスループバックが利用できない環境
(Windows 10 build 20348 未満など)向けのフォールバックで、
既定出力デバイス全体を録音するため、ゲーム音や Go Live の音が混入する。
その場合は Discord の出力先を専用の仮想出力デバイスに割り当てて回避すること。
"""

from __future__ import annotations

import logging
import queue
import threading

import numpy as np

try:
    import pyaudiowpatch as pyaudio
except ImportError:  # テスト環境(core のテストはキャプチャ不要)
    pyaudio = None

logger = logging.getLogger(__name__)


class CaptureError(Exception):
    pass


class WasapiLoopbackCapture:
    """既定出力デバイスのループバックを 100ms 単位で読み出す。

    read() はモノラルへダウンミックスした float64 配列(-1.0〜1.0)を返す。
    """

    def __init__(self, chunk_ms: int = 100) -> None:
        if pyaudio is None:
            raise CaptureError("pyaudiowpatch is not installed (pip install pyaudiowpatch)")
        self._chunk_ms = chunk_ms
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=100)
        self._pa = None
        self._stream = None
        self._closed = threading.Event()
        self.samplerate: int = 0
        self.channels: int = 0

    def start(self) -> None:
        self._pa = pyaudio.PyAudio()
        try:
            wasapi_info = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError as e:
            raise CaptureError("WASAPI is not available") from e

        device = self._pa.get_device_info_by_index(
            wasapi_info["defaultOutputDevice"]
        )
        if not device.get("isLoopbackDevice"):
            for loopback in self._pa.get_loopback_device_info_generator():
                if device["name"] in loopback["name"]:
                    device = loopback
                    break
            else:
                raise CaptureError(
                    f"no loopback found for default output device {device['name']!r}"
                )

        self.samplerate = int(device["defaultSampleRate"])
        self.channels = int(device["maxInputChannels"])
        frames = int(self.samplerate * self._chunk_ms / 1000)

        logger.info(
            "device loopback started: %s (%d Hz, %d ch)",
            device["name"],
            self.samplerate,
            self.channels,
        )

        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.samplerate,
            frames_per_buffer=frames,
            input=True,
            input_device_index=device["index"],
            stream_callback=self._callback,
        )

    def _callback(self, in_data, frame_count, time_info, status):
        samples = np.frombuffer(in_data, dtype=np.int16).astype(np.float64)
        samples /= 32768.0
        if self.channels > 1:
            samples = samples.reshape(-1, self.channels).mean(axis=1)
        try:
            self._queue.put_nowait(samples)
        except queue.Full:
            # 消費が追いつかない場合は古いものから捨てる
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(samples)
            except (queue.Empty, queue.Full):
                pass
        return None, pyaudio.paContinue

    def read(self, timeout: float = 0.5) -> np.ndarray | None:
        """次のチャンクを返す。timeout 内に無ければ None。"""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        self._closed.set()
        if self._stream is not None:
            self._stream.stop_stream()
            self._stream.close()
        if self._pa is not None:
            self._pa.terminate()
