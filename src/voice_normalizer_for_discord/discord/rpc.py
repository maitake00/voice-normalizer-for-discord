"""Discord ローカル RPC(IPC 名前付きパイプ)クライアント。

SPEAKING_START/STOP の購読と SET_USER_VOICE_SETTINGS の書き込みに使う。
未承認アプリの制約(SPEC §6)のため、ユーザー自身が作成した
Discord Application の Client ID/Secret で動作する前提。
"""

from __future__ import annotations

import ctypes
import json
import logging
import msvcrt
import queue
import struct
import threading
import time
import uuid
from ctypes import wintypes
from typing import Any

logger = logging.getLogger(__name__)

_OP_HANDSHAKE = 0
_OP_FRAME = 1
_OP_CLOSE = 2
_OP_PING = 3
_OP_PONG = 4

_COMMAND_TIMEOUT_SEC = 15.0


class DiscordRPCError(Exception):
    pass


class DiscordRPCTimeout(DiscordRPCError):
    """コマンドの応答が時間内に来なかった(AUTHORIZE で認証が押されなかった等)。"""


class DiscordRPC:
    """Discord デスクトップクライアントへの IPC 接続。

    【重要】同期ハンドルの名前付きパイプは、ブロッキング ReadFile 中に
    同じハンドルへの WriteFile がカーネルで直列化されて詰まる。
    そのため送受信とも単一の I/O スレッドで行い、読み取りは
    PeekNamedPipe で「読めるときだけ」読む(ブロッキング read をしない)。
    コマンド応答は nonce で対応付け、イベント(SPEAKING_START 等)は
    ``events`` キューに積まれる。
    """

    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self._pipe = None
        self._handle = None  # PeekNamedPipe 用の Win32 ハンドル
        self._outgoing: queue.Queue[bytes] = queue.Queue()
        self._pending: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._io_thread: threading.Thread | None = None
        self._closed = threading.Event()

    # ---- 接続 -------------------------------------------------------

    def connect(self) -> dict[str, Any]:
        """パイプを探して handshake する。READY ペイロードを返す。"""
        for i in range(10):
            path = rf"\\.\pipe\discord-ipc-{i}"
            try:
                self._pipe = open(path, "r+b", buffering=0)
                break
            except OSError:
                continue
        if self._pipe is None:
            raise DiscordRPCError("Discord desktop client not found")

        # handshake は I/O スレッド起動前なので同期送受信でよい
        self._write_now(_OP_HANDSHAKE, {"v": 1, "client_id": self.client_id})
        op, payload = self._read_packet_blocking()
        if op == _OP_CLOSE:
            raise DiscordRPCError(f"handshake rejected: {payload}")
        if payload.get("evt") != "READY":
            raise DiscordRPCError(f"did not receive READY: {payload}")

        self._handle = msvcrt.get_osfhandle(self._pipe.fileno())
        self._io_thread = threading.Thread(target=self._io_loop, daemon=True)
        self._io_thread.start()
        return payload.get("data", {})

    def close(self) -> None:
        self._closed.set()
        if self._pipe is not None:
            try:
                self._pipe.close()
            except OSError:
                pass

    # ---- コマンド ---------------------------------------------------

    def authorize(self, scopes: list[str]) -> str:
        """Discord クライアント上に承認ダイアログを出し、認可コードを得る。

        注意(実測で確認した Discord の仕様):
        - args に redirect_uri を含めると
          「Redirect URI cannot be used in the RPC OAuth2 Authorization flow」
        - 一方、Developer Portal 側にリダイレクト URI が 1 つも登録されて
          いないと「Missing "redirect_uri" in request」で即エラーになり、
          承認ダイアログ自体が表示されない
        つまり Portal への登録が必須で、リクエストには含めない。
        ユーザーが「認証」を押すまで応答が来ないため、タイムアウトは長めに取る。
        """
        data = self._command(
            "AUTHORIZE",
            {"client_id": self.client_id, "scopes": scopes},
            timeout=120.0,
        )
        return data["code"]

    def authenticate(self, access_token: str) -> dict[str, Any]:
        return self._command("AUTHENTICATE", {"access_token": access_token})

    def get_voice_settings(self) -> dict[str, Any]:
        return self._command("GET_VOICE_SETTINGS")

    def get_selected_voice_channel(self) -> dict[str, Any] | None:
        return self._command("GET_SELECTED_VOICE_CHANNEL")

    def set_user_volume(self, user_id: str, volume: int) -> None:
        self._command(
            "SET_USER_VOICE_SETTINGS",
            {"user_id": user_id, "volume": int(volume)},
        )

    def subscribe(self, event: str, args: dict[str, Any] | None = None) -> None:
        self._request({"cmd": "SUBSCRIBE", "evt": event, "args": args or {}})

    def unsubscribe(self, event: str, args: dict[str, Any] | None = None) -> None:
        self._request({"cmd": "UNSUBSCRIBE", "evt": event, "args": args or {}})

    # ---- 内部 -------------------------------------------------------

    def _command(
        self,
        cmd: str,
        args: dict[str, Any] | None = None,
        timeout: float = _COMMAND_TIMEOUT_SEC,
    ) -> Any:
        resp = self._request({"cmd": cmd, "args": args or {}}, timeout=timeout)
        return resp.get("data")

    def _request(
        self,
        payload: dict[str, Any],
        timeout: float = _COMMAND_TIMEOUT_SEC,
    ) -> dict[str, Any]:
        nonce = str(uuid.uuid4())
        payload["nonce"] = nonce
        slot: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[nonce] = slot
        try:
            self._send(_OP_FRAME, payload)
            try:
                resp = slot.get(timeout=timeout)
            except queue.Empty:
                raise DiscordRPCTimeout(f"{payload.get('cmd')} timed out") from None
        finally:
            with self._pending_lock:
                self._pending.pop(nonce, None)

        if resp.get("evt") == "ERROR":
            data = resp.get("data", {})
            raise DiscordRPCError(
                f"{payload.get('cmd')} failed: "
                f"code={data.get('code')} {data.get('message')}"
            )
        return resp

    def _io_loop(self) -> None:
        """送受信を 1 スレッドに集約する。

        ブロッキング read を行うと同じハンドルへの write が詰まるため、
        PeekNamedPipe で到着済みバイト数を確認してから読む。
        """
        recv_buf = bytearray()
        while not self._closed.is_set():
            try:
                busy = False

                # 送信キューを掃き出す
                while True:
                    try:
                        packet = self._outgoing.get_nowait()
                    except queue.Empty:
                        break
                    self._pipe.write(packet)
                    busy = True

                # 到着している分だけ読む(ブロックしない)
                available = self._peek_available()
                if available > 0:
                    recv_buf += self._pipe.read(available)
                    busy = True
                    if not self._drain_packets(recv_buf):
                        return

                if not busy:
                    time.sleep(0.01)
            except (OSError, DiscordRPCError):
                if not self._closed.is_set():
                    logger.warning("RPC connection lost")
                    self.events.put({"evt": "_DISCONNECTED", "data": {}})
                return

    def _drain_packets(self, recv_buf: bytearray) -> bool:
        """バッファ内の完成パケットを処理する。継続なら True。"""
        while len(recv_buf) >= 8:
            op, length = struct.unpack("<II", recv_buf[:8])
            if len(recv_buf) < 8 + length:
                break
            body = bytes(recv_buf[8 : 8 + length])
            del recv_buf[: 8 + length]
            payload = json.loads(body.decode("utf-8"))

            if op == _OP_PING:
                self._enqueue_packet(_OP_PONG, payload)
            elif op == _OP_CLOSE:
                logger.warning("RPC closed by Discord: %s", payload)
                self.events.put({"evt": "_DISCONNECTED", "data": payload})
                return False
            elif op == _OP_FRAME:
                nonce = payload.get("nonce")
                slot = None
                if nonce:
                    with self._pending_lock:
                        slot = self._pending.get(nonce)
                if slot is not None:
                    slot.put(payload)
                elif payload.get("evt"):
                    self.events.put(payload)
        return True

    def _peek_available(self) -> int:
        available = wintypes.DWORD(0)
        ok = ctypes.windll.kernel32.PeekNamedPipe(
            wintypes.HANDLE(self._handle),
            None,
            0,
            None,
            ctypes.byref(available),
            None,
        )
        if not ok:
            raise DiscordRPCError("pipe closed")
        return available.value

    def _send(self, op: int, payload: dict[str, Any]) -> None:
        """パケットを I/O スレッドの送信キューへ積む。"""
        self._outgoing.put(self._pack(op, payload))

    def _enqueue_packet(self, op: int, payload: dict[str, Any]) -> None:
        self._outgoing.put(self._pack(op, payload))

    @staticmethod
    def _pack(op: int, payload: dict[str, Any]) -> bytes:
        body = json.dumps(payload).encode("utf-8")
        return struct.pack("<II", op, len(body)) + body

    def _write_now(self, op: int, payload: dict[str, Any]) -> None:
        """I/O スレッド起動前(handshake)専用の同期送信。"""
        self._pipe.write(self._pack(op, payload))

    def _read_packet_blocking(self) -> tuple[int, dict[str, Any]]:
        """I/O スレッド起動前(handshake)専用の同期受信。"""
        header = self._read_exact(8)
        op, length = struct.unpack("<II", header)
        body = self._read_exact(length)
        return op, json.loads(body.decode("utf-8"))

    def _read_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self._pipe.read(n - len(buf))
            if not chunk:
                raise DiscordRPCError("pipe closed")
            buf += chunk
        return buf
