"""UI 文言の日英対応の検査。"""

from __future__ import annotations

import re
import string
from pathlib import Path

import pytest

from voice_normalizer_for_discord import i18n

SRC = Path(__file__).resolve().parent.parent / "src" / "voice_normalizer_for_discord"
_KEY_PREFIXES = (
    "button|card|chip|cli|err|error|header|log|members|notice|settings|setup|status"
)
_KEY_RE = re.compile(rf'"((?:{_KEY_PREFIXES})\.[a-z0-9_.]+)"')


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


@pytest.fixture(autouse=True)
def _restore_language():
    yield
    i18n.set_language("auto")


def test_every_string_has_both_languages_with_same_placeholders():
    for key, entry in i18n._STRINGS.items():
        assert set(entry) == {"en", "ja"}, key
        assert entry["en"].strip() and entry["ja"].strip(), key
        assert _fields(entry["en"]) == _fields(entry["ja"]), key


def test_every_key_used_in_code_exists():
    used = set()
    for path in SRC.rglob("*.py"):
        if path.name == "i18n.py":
            continue
        used |= set(_KEY_RE.findall(path.read_text(encoding="utf-8")))
    assert used, "キーの抽出に失敗している"
    missing = sorted(k for k in used if k not in i18n._STRINGS)
    assert not missing, missing


def test_switching_language():
    i18n.set_language("ja")
    # 日本語では折り返し対策でスペースが改行しないスペース(U+00A0)になる
    assert i18n.t("button.start") == "▶ 開始"
    assert i18n.t("header.logged_in", name="a b") == "a b でログイン中"
    i18n.set_language("en")
    assert i18n.t("button.start") == "▶ Start"
    assert i18n.t("log.volume_changed", name="a", old=100, new=80, diff=-2.04) == (
        "a: volume 100% → 80% (off target by -2.0 dB)"
    )


def test_auto_picks_a_supported_language():
    assert i18n.set_language("auto") in i18n.SUPPORTED
    assert i18n.set_language("xx") in i18n.SUPPORTED


def test_unknown_key_is_returned_as_is():
    assert i18n.t("no.such.key") == "no.such.key"
