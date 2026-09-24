"""Windows: プロセス単位ループバック(WASAPI Process Loopback)。

Discord プロセスツリーが再生する音声「だけ」をキャプチャする(SPEC §4-2)。
ゲーム音・音楽など他プロセスの音は混入しない。

実装方式は OBS の「アプリケーション音声キャプチャ」や Microsoft 公式
ApplicationLoopback サンプルと同じ:
  ActivateAudioInterfaceAsync
    + VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK ("VAD\\Process_Loopback")
    + AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
    + PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE

制約(公式サンプル・実装例で既知のもの):
- Windows 10 build 20348+ / Windows 11 が必要
- GetMixFormat は E_NOTIMPL → フォーマットは自前指定し
  AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM で変換させる
- 対象プロセスが何も再生していない間はパケットが来ない(無音扱い)
"""

from __future__ import annotations

import ctypes
import logging
import queue
import threading
from ctypes import (
    POINTER,
    Structure,
    WINFUNCTYPE,
    byref,
    c_byte,
    c_int,
    c_long,
    c_ulong,
    c_ushort,
    c_void_p,
    c_wchar_p,
)
from ctypes.wintypes import DWORD, HANDLE, WORD

import numpy as np

logger = logging.getLogger(__name__)

try:
    import comtypes
    from comtypes import COMMETHOD, GUID, IUnknown
except ImportError:  # 非 Windows 環境(core のテストには不要)
    comtypes = None

try:
    import psutil
except ImportError:
    psutil = None


class ProcessCaptureError(Exception):
    pass


# ---- 定数 -------------------------------------------------------------

_VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"

_AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
_PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0

_AUDCLNT_SHAREMODE_SHARED = 0
_AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
_AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
_AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000
_AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000

_AUDCLNT_BUFFERFLAGS_SILENT = 0x2

_VT_BLOB = 65
_WAVE_FORMAT_PCM = 1

_S_OK = 0
_E_NOINTERFACE = ctypes.c_long(0x80004002).value

_CAPTURE_SAMPLERATE = 48_000
_CAPTURE_CHANNELS = 2
_CAPTURE_BITS = 16


# ---- ctypes 構造体 ----------------------------------------------------


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


class AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(Structure):
    _fields_ = [
        ("TargetProcessId", DWORD),
        ("ProcessLoopbackMode", c_int),
    ]


class AUDIOCLIENT_ACTIVATION_PARAMS(Structure):
    _fields_ = [
        ("ActivationType", c_int),
        ("ProcessLoopbackParams", AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS),
    ]


class _BLOB(Structure):
    _fields_ = [("cbSize", c_ulong), ("pBlobData", c_void_p)]


class PROPVARIANT(Structure):
    _fields_ = [
        ("vt", c_ushort),
        ("wReserved1", c_ushort),
        ("wReserved2", c_ushort),
        ("wReserved3", c_ushort),
        ("blob", _BLOB),
    ]


# ---- COM クライアント側インターフェース(comtypes) --------------------

if comtypes is not None:
    from ctypes import HRESULT

    class IActivateAudioInterfaceAsyncOperation(IUnknown):
        _iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
        _methods_ = [
            COMMETHOD(
                [],
                HRESULT,
                "GetActivateResult",
                (["out"], POINTER(HRESULT), "activateResult"),
                (["out"], POINTER(POINTER(IUnknown)), "activatedInterface"),
            ),
        ]

    class IAudioClient(IUnknown):
        _iid_ = GUID("{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}")
        _methods_ = [
            COMMETHOD(
                [],
                HRESULT,
                "Initialize",
                (["in"], DWORD, "ShareMode"),
                (["in"], DWORD, "StreamFlags"),
                (["in"], ctypes.c_longlong, "hnsBufferDuration"),
                (["in"], ctypes.c_longlong, "hnsPeriodicity"),
                (["in"], POINTER(WAVEFORMATEX), "pFormat"),
                (["in"], POINTER(GUID), "AudioSessionGuid"),
            ),
            COMMETHOD(
                [], HRESULT, "GetBufferSize",
                (["out"], POINTER(ctypes.c_uint32), "pNumBufferFrames"),
            ),
            COMMETHOD(
                [], HRESULT, "GetStreamLatency",
                (["out"], POINTER(ctypes.c_longlong), "phnsLatency"),
            ),
            COMMETHOD(
                [], HRESULT, "GetCurrentPadding",
                (["out"], POINTER(ctypes.c_uint32), "pNumPaddingFrames"),
            ),
            COMMETHOD(
                [], HRESULT, "IsFormatSupported",
                (["in"], DWORD, "ShareMode"),
                (["in"], POINTER(WAVEFORMATEX), "pFormat"),
                (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppClosestMatch"),
            ),
            COMMETHOD(
                [], HRESULT, "GetMixFormat",
                (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppDeviceFormat"),
            ),
            COMMETHOD(
                [], HRESULT, "GetDevicePeriod",
                (["out"], POINTER(ctypes.c_longlong), "phnsDefaultDevicePeriod"),
                (["out"], POINTER(ctypes.c_longlong), "phnsMinimumDevicePeriod"),
            ),
            COMMETHOD([], HRESULT, "Start"),
            COMMETHOD([], HRESULT, "Stop"),
            COMMETHOD([], HRESULT, "Reset"),
            COMMETHOD(
                [], HRESULT, "SetEventHandle",
                (["in"], HANDLE, "eventHandle"),
            ),
            COMMETHOD(
                [], HRESULT, "GetService",
                (["in"], POINTER(GUID), "riid"),
                (["out"], POINTER(POINTER(IUnknown)), "ppv"),
            ),
        ]

    class IAudioCaptureClient(IUnknown):
        _iid_ = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")
        _methods_ = [
            COMMETHOD(
                [], HRESULT, "GetBuffer",
                (["out"], POINTER(POINTER(c_byte)), "ppData"),
                (["out"], POINTER(ctypes.c_uint32), "pNumFramesToRead"),
                (["out"], POINTER(DWORD), "pdwFlags"),
                (["out"], POINTER(ctypes.c_uint64), "pu64DevicePosition"),
                (["out"], POINTER(ctypes.c_uint64), "pu64QPCPosition"),
            ),
            COMMETHOD(
                [], HRESULT, "ReleaseBuffer",
                (["in"], ctypes.c_uint32, "NumFramesRead"),
            ),
            COMMETHOD(
                [], HRESULT, "GetNextPacketSize",
                (["out"], POINTER(ctypes.c_uint32), "pNumFramesInNextPacket"),
            ),
        ]

    _IID_IAGILEOBJECT = GUID("{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}")


# ---- 完了ハンドラ(COM サーバー側を素の ctypes vtable で実装) ----------
#
# ActivateAudioInterfaceAsync は完了通知を COM コールバックで返す。
# comtypes の COMObject 内部仕様に依存しないよう、vtable を自前で組む。

_QI_FUNC = WINFUNCTYPE(c_long, c_void_p, POINTER(GUID), POINTER(c_void_p))
_ADDREF_FUNC = WINFUNCTYPE(c_ulong, c_void_p)
_RELEASE_FUNC = WINFUNCTYPE(c_ulong, c_void_p)
_ACTIVATE_COMPLETED_FUNC = WINFUNCTYPE(c_long, c_void_p, c_void_p)


class _HandlerVtbl(Structure):
    _fields_ = [
        ("QueryInterface", _QI_FUNC),
        ("AddRef", _ADDREF_FUNC),
        ("Release", _RELEASE_FUNC),
        ("ActivateCompleted", _ACTIVATE_COMPLETED_FUNC),
    ]


class _HandlerObj(Structure):
    _fields_ = [("lpVtbl", POINTER(_HandlerVtbl))]


class _CompletionHandler:
    """IActivateAudioInterfaceCompletionHandler + IAgileObject の最小実装。

    寿命は Python 側の参照で管理する(AddRef/Release はダミー)。
    activation が完了するまでインスタンスを保持し続けること。
    """

    _IID_HANDLER = "{41D949AB-9862-444A-80F6-C261334DA5EB}"
    _IID_IUNKNOWN = "{00000000-0000-0000-C000-000000000046}"
    _IID_AGILE = "{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}"

    def __init__(self) -> None:
        self.done = threading.Event()

        def query_interface(this, riid, ppv):
            iid = str(riid.contents).upper()
            if iid in (self._IID_IUNKNOWN, self._IID_HANDLER, self._IID_AGILE):
                ppv[0] = this
                return _S_OK
            ppv[0] = None
            return _E_NOINTERFACE

        def add_ref(this):
            return 2

        def release(this):
            return 1

        def activate_completed(this, operation):
            self.done.set()
            return _S_OK

        # コールバックと構造体は GC されないよう属性に保持
        self._callbacks = (
            _QI_FUNC(query_interface),
            _ADDREF_FUNC(add_ref),
            _RELEASE_FUNC(release),
            _ACTIVATE_COMPLETED_FUNC(activate_completed),
        )
        self._vtbl = _HandlerVtbl(*self._callbacks)
        self._obj = _HandlerObj(ctypes.pointer(self._vtbl))

    def as_pointer(self) -> c_void_p:
        return ctypes.cast(ctypes.pointer(self._obj), c_void_p)


# ---- Discord プロセスの発見 --------------------------------------------

_DISCORD_EXE_NAMES = (
    "discord.exe",
    "discordptb.exe",
    "discordcanary.exe",
    "discorddevelopment.exe",
)


def find_discord_pid() -> int:
    """Discord プロセスツリーのルート PID を返す。

    INCLUDE_TARGET_PROCESS_TREE でツリーごとキャプチャするため、
    親が Discord ではない(=ルートの)プロセスを選ぶ。
    """
    if psutil is None:
        raise ProcessCaptureError("psutil is not installed (pip install psutil)")
    candidates = []
    for proc in psutil.process_iter(["pid", "name", "ppid"]):
        name = (proc.info["name"] or "").lower()
        if name in _DISCORD_EXE_NAMES:
            candidates.append(proc)
    if not candidates:
        raise ProcessCaptureError("Discord process not found")
    pids = {p.info["pid"] for p in candidates}
    for proc in candidates:
        if proc.info["ppid"] not in pids:
            return proc.info["pid"]
    return candidates[0].info["pid"]


# ---- キャプチャ本体 ----------------------------------------------------


class ProcessLoopbackCapture:
    """対象プロセスツリーの再生音声を 16bit/48kHz でキャプチャし、
    モノラル float64(-1.0〜1.0)のチャンクとして供給する。

    WasapiLoopbackCapture と同じインターフェース
    (start / read / stop / samplerate)を持つ。
    """

    def __init__(self, target_pid: int) -> None:
        if comtypes is None:
            raise ProcessCaptureError("comtypes is not installed (pip install comtypes)")
        self.target_pid = target_pid
        self.samplerate = _CAPTURE_SAMPLERATE
        self.channels = _CAPTURE_CHANNELS
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self._stop = threading.Event()
        self._started = threading.Event()
        self._start_error: Exception | None = None
        self._thread: threading.Thread | None = None

    # -- 公開 API --

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._started.wait(timeout=10):
            self._stop.set()
            raise ProcessCaptureError("capture initialization timed out")
        if self._start_error is not None:
            raise ProcessCaptureError(
                f"could not start process loopback: {self._start_error}"
            ) from self._start_error
        logger.info(
            "process loopback started: PID %d tree only (%d Hz)",
            self.target_pid,
            self.samplerate,
        )

    def read(self, timeout: float = 0.5) -> np.ndarray | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)

    # -- キャプチャスレッド --

    def _run(self) -> None:
        kernel32 = ctypes.windll.kernel32
        event_handle = None
        audio_client = None
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        except OSError:
            pass  # 既に初期化済み(RPC_E_CHANGED_MODE 等)は続行

        try:
            audio_client = self._activate()

            wfx = WAVEFORMATEX(
                wFormatTag=_WAVE_FORMAT_PCM,
                nChannels=_CAPTURE_CHANNELS,
                nSamplesPerSec=_CAPTURE_SAMPLERATE,
                nAvgBytesPerSec=_CAPTURE_SAMPLERATE
                * _CAPTURE_CHANNELS
                * _CAPTURE_BITS
                // 8,
                nBlockAlign=_CAPTURE_CHANNELS * _CAPTURE_BITS // 8,
                wBitsPerSample=_CAPTURE_BITS,
                cbSize=0,
            )
            # プロセスループバックは GetMixFormat 非対応のため
            # 自前フォーマット + AUTOCONVERTPCM で初期化する
            audio_client.Initialize(
                _AUDCLNT_SHAREMODE_SHARED,
                _AUDCLNT_STREAMFLAGS_LOOPBACK
                | _AUDCLNT_STREAMFLAGS_EVENTCALLBACK
                | _AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM
                | _AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY,
                0,
                0,
                byref(wfx),
                None,
            )

            event_handle = kernel32.CreateEventW(None, False, False, None)
            audio_client.SetEventHandle(event_handle)

            capture_unknown = audio_client.GetService(
                byref(IAudioCaptureClient._iid_)
            )
            capture_client = capture_unknown.QueryInterface(IAudioCaptureClient)

            audio_client.Start()
            self._started.set()

            block_align = wfx.nBlockAlign
            while not self._stop.is_set():
                kernel32.WaitForSingleObject(event_handle, 200)
                while True:
                    n_next = capture_client.GetNextPacketSize()
                    if n_next == 0:
                        break
                    data_ptr, n_frames, flags, _pos, _qpc = (
                        capture_client.GetBuffer()
                    )
                    if n_frames:
                        if flags & _AUDCLNT_BUFFERFLAGS_SILENT:
                            mono = np.zeros(n_frames, dtype=np.float64)
                        else:
                            raw = ctypes.string_at(
                                data_ptr, n_frames * block_align
                            )
                            samples = np.frombuffer(
                                raw, dtype=np.int16
                            ).astype(np.float64)
                            samples /= 32768.0
                            mono = samples.reshape(
                                -1, _CAPTURE_CHANNELS
                            ).mean(axis=1)
                        self._enqueue(mono)
                    capture_client.ReleaseBuffer(n_frames)
        except Exception as e:  # noqa: BLE001 - スレッド境界で握って通知する
            if not self._started.is_set():
                self._start_error = e
                self._started.set()
            else:
                logger.error("capture thread stopped: %s", e)
        finally:
            if audio_client is not None:
                try:
                    audio_client.Stop()
                except Exception:  # noqa: BLE001
                    pass
            if event_handle:
                kernel32.CloseHandle(event_handle)
            comtypes.CoUninitialize()

    def _activate(self):
        """ActivateAudioInterfaceAsync で IAudioClient を得る。"""
        loopback_params = AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(
            TargetProcessId=self.target_pid,
            ProcessLoopbackMode=_PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE,
        )
        activation_params = AUDIOCLIENT_ACTIVATION_PARAMS(
            ActivationType=_AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK,
            ProcessLoopbackParams=loopback_params,
        )
        prop = PROPVARIANT()
        prop.vt = _VT_BLOB
        prop.blob.cbSize = ctypes.sizeof(activation_params)
        prop.blob.pBlobData = ctypes.cast(
            ctypes.pointer(activation_params), c_void_p
        )

        handler = _CompletionHandler()
        operation = POINTER(IActivateAudioInterfaceAsyncOperation)()

        activate = ctypes.windll.mmdevapi.ActivateAudioInterfaceAsync
        activate.restype = c_long
        activate.argtypes = [
            c_wchar_p,
            POINTER(GUID),
            POINTER(PROPVARIANT),
            c_void_p,
            POINTER(POINTER(IActivateAudioInterfaceAsyncOperation)),
        ]
        hr = activate(
            _VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
            byref(IAudioClient._iid_),
            byref(prop),
            handler.as_pointer(),
            byref(operation),
        )
        if hr != _S_OK:
            raise ProcessCaptureError(
                f"ActivateAudioInterfaceAsync failed (hr=0x{hr & 0xFFFFFFFF:08X}); "
                "Windows 10 build 20348 or later is required"
            )
        if not handler.done.wait(timeout=5):
            raise ProcessCaptureError("audio interface activation timed out")

        activate_hr, unknown = operation.GetActivateResult()
        if activate_hr != _S_OK:
            raise ProcessCaptureError(
                f"audio interface activation failed (hr=0x{activate_hr & 0xFFFFFFFF:08X})"
            )
        return unknown.QueryInterface(IAudioClient)

    def _enqueue(self, chunk: np.ndarray) -> None:
        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(chunk)
            except (queue.Empty, queue.Full):
                pass
