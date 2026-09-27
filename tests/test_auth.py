"""認証まわり: PKCE、標準アプリの Client ID、テスター未登録時の分類。"""

from __future__ import annotations

import base64
import hashlib
import queue

from voice_normalizer_for_discord.discord import DiscordRPCError, oauth
from voice_normalizer_for_discord.engine import NormalizerEngine


def test_pkce_challenge_is_s256_of_verifier():
    verifier, challenge = oauth.make_pkce()
    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    assert challenge == expected.rstrip(b"=").decode()
    assert oauth.make_pkce()[0] != verifier  # 毎回違う


class RejectingRPC:
    """AUTHORIZE を拒否する Discord(テスター未登録などを模す)。"""

    created_with: list[str] = []

    def __init__(self, client_id: str) -> None:
        RejectingRPC.created_with.append(client_id)
        self.events: queue.Queue = queue.Queue()
        self.challenges: list[str | None] = []

    def connect(self):
        return {"user": {"id": "me", "username": "me"}}

    def authorize(self, scopes, code_challenge=None):
        self.challenges.append(code_challenge)
        raise DiscordRPCError("AUTHORIZE failed: code=4000 not allowed")

    def close(self):
        pass


def _run(tmp_path, discord_config: dict) -> tuple[list[dict], RejectingRPC]:
    RejectingRPC.created_with = []
    rpcs: list[RejectingRPC] = []

    def factory(cid):
        rpc = RejectingRPC(cid)
        rpcs.append(rpc)
        return rpc

    eng = NormalizerEngine(
        {"discord": discord_config}, tmp_path, rpc_factory=factory,
        capture_factory=lambda: (_ for _ in ()).throw(AssertionError("not reached")),
    )
    eng.start()
    eng.join(5)
    events = []
    while not eng.events.empty():
        events.append(eng.events.get_nowait())
    return events, rpcs[0]


def test_empty_client_id_uses_default_app_and_sends_pkce(tmp_path):
    events, rpc = _run(tmp_path, {"client_id": "", "client_secret": ""})
    assert RejectingRPC.created_with == [oauth.DEFAULT_CLIENT_ID]
    assert rpc.challenges and rpc.challenges[0]  # PKCE の challenge を渡している
    errors = [e for e in events if e["kind"] == "error"]
    assert errors[0]["code"] == "not_tester"


def test_own_app_rejection_is_a_normal_auth_error(tmp_path):
    events, _ = _run(tmp_path, {"client_id": "1234567890123456789"})
    assert RejectingRPC.created_with == ["1234567890123456789"]
    errors = [e for e in events if e["kind"] == "error"]
    assert errors[0]["code"] == "auth"
