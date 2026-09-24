"""設定ファイルの保存・読み込みと、改名前の保存先からの引き継ぎ。"""

from __future__ import annotations

from voice_normalizer_for_discord.settings import (
    default_config,
    gui_config_dir,
    load_config,
    save_config,
)


def test_save_and_load_roundtrip(tmp_path):
    config = default_config()
    config["discord"]["client_id"] = "123"
    config["discord"]["client_secret"] = 'a"b\\c'
    config["params"]["target_db"] = -30.0
    path = tmp_path / "config.toml"
    save_config(path, config)

    loaded = load_config(path)
    assert loaded["discord"]["client_secret"] == 'a"b\\c'
    assert loaded["params"]["target_db"] == -30.0
    assert loaded["params"]["percentile"] == 87.5
    assert loaded["ui"]["language"] == "auto"


def test_old_config_dir_is_migrated(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    old = tmp_path / "DiscordVoiceNormalizer"
    old.mkdir()
    (old / "token.json").write_text("{}", encoding="utf-8")

    new = gui_config_dir()

    assert new == tmp_path / "VoiceNormalizerForDiscord"
    assert (new / "token.json").exists()
    assert not old.exists()


def test_new_config_dir_wins_when_both_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    (tmp_path / "DiscordVoiceNormalizer").mkdir()
    (tmp_path / "VoiceNormalizerForDiscord").mkdir()

    assert gui_config_dir() == tmp_path / "VoiceNormalizerForDiscord"
    assert (tmp_path / "DiscordVoiceNormalizer").exists()  # 勝手に消さない
