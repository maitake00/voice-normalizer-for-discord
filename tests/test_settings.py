"""設定ファイルの保存・読み込みと、改名前の保存先からの引き継ぎ。"""

from __future__ import annotations

from voice_normalizer_for_discord.settings import (
    DEFAULT_PARAMS,
    default_config,
    effective_params,
    gui_config_dir,
    load_config,
    save_config,
)


def test_save_and_load_roundtrip(tmp_path):
    config = default_config()
    config["discord"]["client_id"] = 'a"b\\c'  # エスケープの確認
    config["discord"]["client_secret"] = "old"  # 以前の設定の名残は書き出さない
    config["params"]["target_db"] = -30.0
    path = tmp_path / "config.toml"
    save_config(path, config)

    loaded = load_config(path)
    assert loaded["discord"]["client_id"] == 'a"b\\c'
    assert "client_secret" not in loaded["discord"]
    assert loaded["params"]["target_db"] == -30.0
    # 変更していない値は書き出さず、読み込み時は既定値が使われる
    assert "percentile" not in loaded["params"]
    assert effective_params(loaded)["percentile"] == DEFAULT_PARAMS["percentile"]
    assert loaded["ui"]["language"] == "auto"


def test_old_default_written_by_earlier_versions_is_ignored(tmp_path):
    # 以前の版は変更していない値もすべて書き出していた(min_samples = 50 が既定値だった)
    path = tmp_path / "config.toml"
    path.write_text("[params]\nmin_samples = 50\ntarget_db = -24.0\n", encoding="utf-8")
    assert effective_params(load_config(path))["min_samples"] == DEFAULT_PARAMS["min_samples"]


def test_customized_value_is_kept(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[params]\nmin_samples = 30\n", encoding="utf-8")
    assert effective_params(load_config(path))["min_samples"] == 30


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
