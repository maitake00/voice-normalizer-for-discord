"""エンジンの結合テスト。Discord と音声デバイスを偽物に差し替えて動かす。

- 話者の音量が目標へ収束し、SET_USER_VOICE_SETTINGS が呼ばれること
- 通話を抜ける / 別チャンネルに入ると購読が切り替わること
"""

from __future__ import annotations

import json
import queue
import threading
import time

import numpy as np
import pytest

from voice_normalizer_for_discord import engine as engine_mod
from voice_normalizer_for_discord.engine import NormalizerEngine

SELF_ID = "me"


class FakeRPC:
    def __init__(self, client_id: str) -> None:
        self.events: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        self.channel: tuple[str, str] | None = None  # (id, name)
        self.volumes: dict[str, int] = {}
        self.sub_log: list[tuple[str, str, str]] = []

    def connect(self):
        return {"user": {"id": SELF_ID, "username": SELF_ID}}

    def authenticate(self, access_token):
        return {"user": {"id": SELF_ID, "username": SELF_ID}}

    def authorize(self, scopes):
        raise AssertionError("キャッシュ済みトークンがあるので呼ばれないはず")

    def get_voice_settings(self):
        return {}

    def get_selected_voice_channel(self):
        with self.lock:
            if self.channel is None:
                return None
            cid, name = self.channel
            states = [{"user": {"id": SELF_ID, "username": SELF_ID}, "volume": 100}]
            for uid, vol in self.volumes.items():
                states.append({"user": {"id": uid, "username": uid}, "volume": vol})
            return {"id": cid, "name": name, "voice_states": states}

    def set_user_volume(self, user_id, volume):
        with self.lock:
            self.volumes[user_id] = volume

    def subscribe(self, event, args=None):
        self.sub_log.append(("sub", event, (args or {}).get("channel_id")))

    def unsubscribe(self, event, args=None):
        self.sub_log.append(("unsub", event, (args or {}).get("channel_id")))

    def close(self):
        pass


class FakeCapture:
    """現在の話者の声を、Discord に設定された volume% を掛けて出力する。"""

    samplerate = 48_000

    def __init__(self, rpc: FakeRPC, raw_db: dict[str, float]) -> None:
        self.rpc = rpc
        self.raw_db = raw_db
        self.speaker: str | None = None
        self._rng = np.random.default_rng(0)

    def read(self, timeout=0.5):
        time.sleep(0.0005)
        n = self.samplerate // 10
        speaker = self.speaker
        if speaker is None:
            return np.zeros(n)
        with self.rpc.lock:
            vol = self.rpc.volumes[speaker]
        x = self._rng.standard_normal(n)
        return x * 10.0 ** (self.raw_db[speaker] / 20.0) * (vol / 100.0)

    def stop(self):
        pass


@pytest.fixture
def fast_engine(monkeypatch):
    monkeypatch.setattr(engine_mod, "_POLL_INTERVAL_SEC", 0.02)
    monkeypatch.setattr(engine_mod, "_SNAPSHOT_INTERVAL_SEC", 0.02)


def _make_engine(tmp_path, rpc: FakeRPC, capture: FakeCapture) -> NormalizerEngine:
    token = {"access_token": "x", "expires_in": 10**9, "_obtained_at": time.time()}
    (tmp_path / "token.json").write_text(json.dumps(token), encoding="utf-8")
    config = {
        "discord": {"client_id": "1", "client_secret": "s"},
        "params": {"target_db": -24.0, "min_samples": 30},
    }
    return NormalizerEngine(
        config,
        tmp_path,
        rpc_factory=lambda _cid: rpc,
        capture_factory=lambda: (capture, "process"),
    )


def _wait(cond, timeout=10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def _drain(eng: NormalizerEngine) -> list[dict]:
    out = []
    while True:
        try:
            out.append(eng.events.get_nowait())
        except queue.Empty:
            return out


def test_loud_speaker_is_turned_down_to_target(tmp_path, fast_engine):
    rpc = FakeRPC("1")
    rpc.channel = ("c1", "一般")
    rpc.volumes = {"loud": 100, "silent": 100}
    capture = FakeCapture(rpc, {"loud": -18.0})
    eng = _make_engine(tmp_path, rpc, capture)
    eng.start()
    try:
        assert _wait(lambda: ("sub", "SPEAKING_START", "c1") in rpc.sub_log)
        rpc.events.put({"evt": "SPEAKING_START", "data": {"user_id": "loud"}})
        capture.speaker = "loud"
        # 補正が入り、しばらく経って落ち着くまで待つ
        assert _wait(lambda: rpc.volumes["loud"] < 100)
        time.sleep(2.0)
    finally:
        eng.request_stop()
        eng.join(5)

    events = _drain(eng)
    assert not [e for e in events if e["kind"] == "error"]
    users = [e for e in events if e["kind"] == "users" and e["users"]][-1]["users"]
    loud = next(u for u in users if u["id"] == "loud")
    silent = next(u for u in users if u["id"] == "silent")

    assert loud["volume"] < 100
    assert loud["error_db"] is not None
    assert abs(loud["error_db"]) <= loud["deadband_db"] + 0.5
    # 一度も話していない人には触らない
    assert silent["volume"] == 100 and silent["samples"] == 0
    assert events[-1]["kind"] == "stopped"


def test_follows_leaving_and_switching_channels(tmp_path, fast_engine):
    rpc = FakeRPC("1")
    capture = FakeCapture(rpc, {})
    eng = _make_engine(tmp_path, rpc, capture)
    collected: list[dict] = []

    def seen_waiting() -> bool:
        collected.extend(_drain(eng))
        return any(e["kind"] == "status" and e["state"] == "waiting" for e in collected)

    eng.start()
    try:
        assert _wait(seen_waiting)

        with rpc.lock:
            rpc.channel = ("c1", "一般")
        assert _wait(lambda: ("sub", "SPEAKING_START", "c1") in rpc.sub_log)

        with rpc.lock:
            rpc.channel = None
        assert _wait(lambda: ("unsub", "SPEAKING_START", "c1") in rpc.sub_log)

        with rpc.lock:
            rpc.channel = ("c2", "ゲーム")
        assert _wait(lambda: ("sub", "SPEAKING_START", "c2") in rpc.sub_log)
    finally:
        eng.request_stop()
        eng.join(5)

    collected.extend(_drain(eng))
    states = [
        (e["state"], e.get("channel"))
        for e in collected
        if e["kind"] == "status"
    ]
    assert ("monitoring", "一般") in states
    assert ("monitoring", "ゲーム") in states
    assert states.index(("monitoring", "一般")) < states.index(("monitoring", "ゲーム"))
    assert [s for s, _ in states].count("waiting") >= 2  # 最初 + 抜けたとき


def test_discord_not_running_is_reported(tmp_path):
    from voice_normalizer_for_discord.discord import DiscordRPCError

    class NoDiscord(FakeRPC):
        def connect(self):
            raise DiscordRPCError("見つかりません")

    rpc = NoDiscord("1")
    eng = _make_engine(tmp_path, rpc, FakeCapture(rpc, {}))
    eng.start()
    eng.join(5)
    errors = [e for e in _drain(eng) if e["kind"] == "error"]
    assert errors and errors[0]["code"] == "no_discord"
