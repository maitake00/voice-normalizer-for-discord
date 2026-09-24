"""設定ファイル(config.toml)の読み書き。

GUI / exe 版は %APPDATA%\\VoiceNormalizerForDiscord\\config.toml を使う。
CLI は --config で任意のパスを指定できる。
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

DEFAULT_PARAMS: dict[str, float | int] = {
    "target_db": -24.0,
    "percentile": 87.5,
    "window": 600,
    "min_samples": 50,
    "deadband_db": 1.5,
    "max_step_db": 3.0,
}


_APP_DIR = "VoiceNormalizerForDiscord"
_OLD_APP_DIR = "DiscordVoiceNormalizer"  # 改名前(v0.1.0 のテストビルドまで)


def gui_config_dir() -> Path:
    base = Path(os.environ.get("APPDATA") or str(Path.home()))
    new = base / _APP_DIR
    old = base / _OLD_APP_DIR
    # 改名前の保存先があれば引き継ぐ(ID/Secret とログイン状態を失わないように)
    if not new.exists() and old.exists():
        try:
            old.rename(new)
        except OSError:
            return old
    return new


def load_config(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def default_config() -> dict:
    return {
        "discord": {"client_id": "", "client_secret": ""},
        "params": dict(DEFAULT_PARAMS),
        "ui": {"language": "auto"},
        "debug": {"frame_log": False},
    }


def save_config(path: Path, config: dict) -> None:
    """フラットな 4 セクションのみの単純な TOML を書き出す。"""
    discord = config.get("discord", {})
    params = {**DEFAULT_PARAMS, **config.get("params", {})}
    ui = config.get("ui", {})
    debug = config.get("debug", {})

    def _fmt(value) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
        return str(value)

    lines = ["[discord]"]
    lines.append(f'client_id = {_fmt(str(discord.get("client_id", "")))}')
    lines.append(f'client_secret = {_fmt(str(discord.get("client_secret", "")))}')
    lines.append("")
    lines.append("[params]")
    for key in DEFAULT_PARAMS:
        lines.append(f"{key} = {_fmt(params[key])}")
    lines.append("")
    lines.append("[ui]")
    lines.append(f'language = {_fmt(str(ui.get("language", "auto")))}')
    lines.append("")
    lines.append("[debug]")
    lines.append(f'frame_log = {_fmt(bool(debug.get("frame_log", False)))}')
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
