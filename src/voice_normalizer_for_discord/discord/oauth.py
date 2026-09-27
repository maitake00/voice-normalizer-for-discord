"""OAuth2 トークン交換とローカルキャッシュ。

RPC の AUTHORIZE で得た認可コードをアクセストークンに交換する。
client_secret は使わず PKCE で交換する(アプリ側で「Public Client」を
オンにしておく)。secret を配布物に埋め込まずに済み、利用者も secret を
扱わなくてよい。
トークンはユーザーのローカルにのみ保存し、外部送信は一切しない。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://discord.com/api/oauth2/token"
# Developer Portal 側で同じ Redirect URI を登録しておくこと
REDIRECT_URI = "http://127.0.0.1"

SCOPES = ["rpc", "rpc.voice.read", "rpc.voice.write"]

# 配布用の Discord アプリ(Public Client)。未承認アプリなので、使えるのは
# アプリの持ち主と、Developer Portal の App Testers に登録された人(最大 50 人)だけ。
# 登録されていない人は、自分のアプリの Client ID を設定すれば使える。
DEFAULT_CLIENT_ID = "1526180023088840725"


def make_pkce() -> tuple[str, str]:
    """(code_verifier, code_challenge[S256]) を作る。"""
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _post_token(fields: dict[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(fields).encode("ascii")
    req = urllib.request.Request(
        _TOKEN_URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            # 既定の Python-urllib UA は Cloudflare に弾かれる(403 / 1010)
            "User-Agent": "VoiceNormalizerForDiscord/0.1 (Windows)",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    data["_obtained_at"] = time.time()
    return data


def exchange_code(client_id: str, code: str, code_verifier: str) -> dict[str, Any]:
    return _post_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
        }
    )


def refresh_token(client_id: str, refresh: str) -> dict[str, Any]:
    return _post_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
        }
    )


def load_cached_token(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_token(path: Path, token: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(token, indent=2), encoding="utf-8")


def is_expired(token: dict[str, Any]) -> bool:
    obtained = token.get("_obtained_at", 0)
    expires_in = token.get("expires_in", 0)
    return time.time() > obtained + expires_in - 300  # 5 分の余裕
