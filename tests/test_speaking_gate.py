"""SpeakingGate: 単独発話の判定と、STOP を取りこぼした人の片付け。"""

from __future__ import annotations

from voice_normalizer_for_discord.engine import NormalizerEngine, SpeakingGate


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_sole_speaker_and_overlap():
    gate = SpeakingGate("me")
    assert gate.sole_speaker() is None
    gate.on_start("a")
    assert gate.sole_speaker() == "a"
    gate.on_start("b")
    assert gate.sole_speaker() is None and gate.discarded_overlap == 1
    gate.on_stop("a")
    assert gate.sole_speaker() == "b"


def test_own_voice_is_ignored():
    gate = SpeakingGate("me")
    gate.on_start("me")
    assert gate.speaking_ids() == set()


def test_retain_drops_people_who_cannot_speak():
    gate = SpeakingGate("me")
    gate.on_start("a")
    gate.on_start("b")
    assert gate.retain({"b"}) == ["a"]
    assert gate.speaking_ids() == {"b"}


def test_stale_speaking_expires_but_restart_refreshes():
    clock = FakeClock()
    gate = SpeakingGate("me", clock=clock)
    gate.on_start("stuck")
    gate.on_start("talker")
    clock.now = 50
    gate.on_start("talker")  # 話し直すと時刻が更新される
    clock.now = 61
    assert gate.expire_stale(60) == ["stuck"]
    assert gate.speaking_ids() == {"talker"}


def test_read_voice_states_marks_muted_and_deafened_as_silenced():
    channel = {
        "voice_states": [
            {"user": {"id": "me"}, "volume": 100},
            {"user": {"id": "a", "username": "a"}, "volume": 120,
             "voice_state": {"self_mute": True}},
            {"user": {"id": "b", "username": "b"}, "volume": 100,
             "voice_state": {"self_deaf": True}},
            {"user": {"id": "c", "username": "c"}, "volume": 80, "mute": True,
             "voice_state": {}},
            {"user": {"id": "d", "username": "d"}, "volume": 100},
        ]
    }
    volumes, names, muted, silenced = NormalizerEngine._read_voice_states(channel, "me")
    assert set(volumes) == {"a", "b", "c", "d"}
    assert muted == {"c"}  # 自分がローカルミュートした人(話すことはできる)
    assert silenced == {"a", "b"}
