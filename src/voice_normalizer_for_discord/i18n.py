"""UI 文言の日英切り替え。

言語は "auto"(Windows の表示言語)/ "en" / "ja"。日本語以外の環境では英語になる。
文言は t(key, **kwargs) で取り出す。未知のキーはキーそのものを返す。
"""

from __future__ import annotations

import locale

SUPPORTED = ("en", "ja")


def detect_language() -> str:
    """Windows の表示言語が日本語なら "ja"、それ以外は "en"。"""
    try:
        import ctypes

        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "ja" if (langid & 0x3FF) == 0x11 else "en"
    except (AttributeError, OSError):
        name = (locale.getlocale()[0] or "").lower()
        return "ja" if name.startswith(("ja", "japanese")) else "en"


_lang = detect_language()


def set_language(preference: str) -> str:
    """preference は "auto" / "en" / "ja"。実際に使う言語を返す。"""
    global _lang
    _lang = preference if preference in SUPPORTED else detect_language()
    return _lang


def get_language() -> str:
    return _lang


def t(key: str, **kwargs) -> str:
    entry = _STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(_lang) or entry["en"]
    if _lang == "ja":
        # Tk は半角スペースでしか折り返さないため、日本語文中のスペース
        # (「Discord の」など)で不自然に改行される。改行しないスペースにする
        text = text.replace(" ", " ")
    return text.format(**kwargs) if kwargs else text


_STRINGS: dict[str, dict[str, str]] = {
    # ---- 汎用 ----
    "raw": {"en": "{text}", "ja": "{text}"},
    # ---- ヘッダー ----
    "header.logged_in": {"en": "Logged in as {name}", "ja": "{name} でログイン中"},
    "button.start": {"en": "▶ Start", "ja": "▶ 開始"},
    "button.stop": {"en": "■ Stop", "ja": "■ 停止"},
    "button.settings": {"en": "Settings", "ja": "設定"},
    "button.review_setup": {"en": "Review setup", "ja": "設定を見直す"},
    # ---- 状態カード ----
    "status.stopped.title": {"en": "Stopped", "ja": "停止中"},
    "status.stopped.sub": {
        "en": "Press [Start] to begin evening out volumes.",
        "ja": "［開始］を押すと、音量の自動調整を始めます",
    },
    "status.connecting.title": {
        "en": "Connecting to Discord…",
        "ja": "Discord に接続しています…",
    },
    "status.no_discord.title": {"en": "Discord not found", "ja": "Discord が見つかりません"},
    "status.no_discord.sub": {
        "en": "Please start the Discord app. It will connect automatically.",
        "ja": "Discord アプリを起動してください。起動すると自動でつながります",
    },
    "status.retry_suffix": {
        "en": " (checking every {sec} seconds)",
        "ja": "（{sec} 秒ごとに確認しています）",
    },
    "status.authorizing.title": {
        "en": "Click [Authorize] in the Discord window",
        "ja": "Discord の画面で［認証］を押してください",
    },
    "status.authorizing.sub": {
        "en": "This is needed only once. Look for the prompt in your Discord window.",
        "ja": "初回だけ必要です。Discord のウィンドウに確認画面が出ています",
    },
    "status.waiting.title": {"en": "Waiting for a voice call", "ja": "通話を待っています"},
    "status.waiting.sub": {
        "en": "It starts automatically when you join a voice channel.",
        "ja": "ボイスチャンネルに参加すると、自動で始まります",
    },
    "status.left": {
        "en": "Left the call. It resumes when you join one.",
        "ja": "通話を抜けました。参加すると再開します",
    },
    "status.monitoring.title": {"en": "Adjusting", "ja": "調整中"},
    "status.monitoring.title_channel": {
        "en": "Adjusting in {channel}",
        "ja": "{channel} で調整中",
    },
    "status.monitoring.sub": {
        "en": "Each time someone speaks alone, their volume is nudged toward the target.",
        "ja": "メンバーが一人ずつ話すと、その人の音量が少しずつ揃っていきます",
    },
    "chip.audio_ok": {"en": "● Receiving audio", "ja": "● 音声を受信中"},
    "chip.audio_none": {
        "en": "● No audio from Discord",
        "ja": "● Discord の音声が届いていません",
    },
    "chip.voice_ok": {"en": "● Voices detected", "ja": "● 話し声を検出"},
    "chip.voice_none": {"en": "● No one has spoken yet", "ja": "● まだ誰も話していません"},
    "chip.mode_process": {"en": "Measuring Discord audio only", "ja": "Discord の音だけを測定"},
    "chip.mode_device": {"en": "Measuring all PC audio", "ja": "PC 全体の音で測定中"},
    # ---- エラー表示 ----
    "error.title.disconnected": {"en": "Connection lost", "ja": "接続が切れました"},
    "error.title.check_setup": {"en": "Please check your setup", "ja": "設定を確認してください"},
    "error.title.generic": {"en": "Something went wrong", "ja": "エラーが発生しました"},
    "error.title.config_load": {"en": "Could not load settings", "ja": "設定を読み込めません"},
    "error.retrying": {
        "en": "{text}. Reconnecting in {sec} seconds.",
        "ja": "{text}。{sec} 秒後に自動で再接続します",
    },
    # ---- メンバー ----
    "members.title": {"en": "Members", "ja": "メンバー"},
    "members.show_numbers": {"en": "Show numbers", "ja": "数値を表示"},
    "members.stats": {
        "en": "Used {adopted} · Skipped (overlap) {discarded}",
        "ja": "採用 {adopted} ・ 同時発話で除外 {discarded}",
    },
    "members.empty_monitoring": {
        "en": "Other members will appear here when they join.",
        "ja": "ほかのメンバーが参加すると、ここに表示されます",
    },
    "members.empty_waiting": {
        "en": "Join a voice call to see its members here.",
        "ja": "通話に参加すると、メンバーがここに表示されます",
    },
    "card.muted": {"en": "Muted by you, so not adjusted", "ja": "ミュート中のため調整しません"},
    "card.pinned": {
        "en": "Still quiet at 200% (ask them to turn up their mic)",
        "ja": "200%でも小さめです（本人にマイク音量を上げてもらってください）",
    },
    "card.learning": {
        "en": "Learning their voice… {pct}% (progresses while they speak alone)",
        "ja": "声を聞き取り中… {pct}%（この人が一人で話すと進みます）",
    },
    "card.ready": {"en": "Ready", "ja": "準備できました"},
    "card.good": {"en": "✓ Volume is just right", "ja": "✓ ちょうどいい音量です"},
    "card.raising": {"en": "Turning up gradually", "ja": "少しずつ大きくしています"},
    "card.lowering": {"en": "Turning down gradually", "ja": "少しずつ小さくしています"},
    "card.detail": {
        "en": "Loudness {raw} · Off target {diff} · Samples {samples}",
        "ja": "声の大きさ {raw} ・ 目標との差 {diff} ・ サンプル {samples}",
    },
    # ---- ログ ----
    "log.show": {"en": "▸ Show log", "ja": "▸ 詳細ログを表示"},
    "log.hide": {"en": "▾ Hide log", "ja": "▾ 詳細ログを隠す"},
    "log.copy": {"en": "Copy log", "ja": "ログをコピー"},
    "log.copied": {"en": "Copied", "ja": "コピーしました"},
    "log.state_header": {"en": "Status: {state}", "ja": "状態: {state}"},
    "log.settings_saved": {"en": "Settings saved", "ja": "設定を保存しました"},
    "log.logged_in": {"en": "Logged in as {name}", "ja": "{name} としてログインしました"},
    "log.token_invalid": {
        "en": "Saved login is no longer valid. Authorizing again.",
        "ja": "保存済みのログイン情報が無効でした。再認証します",
    },
    "log.voice_settings_failed": {
        "en": "Could not read Discord's voice settings: {detail}",
        "ja": "音声設定を取得できませんでした: {detail}",
    },
    "log.attenuation_unknown": {
        "en": "Could not read Discord's Attenuation setting (0% recommended)",
        "ja": "Discord の［減衰］設定は取得できませんでした(0% 推奨)",
    },
    "log.capture_process": {
        "en": "Audio capture: Discord only",
        "ja": "音声の取り込み: Discord の音だけ",
    },
    "log.capture_fallback": {
        "en": "Could not capture Discord's audio alone: {detail}",
        "ja": "Discord の音だけを取り込めませんでした: {detail}",
    },
    "log.frame_log": {
        "en": "Recording measurement frames to {path}",
        "ja": "測定フレームを記録: {path}",
    },
    "log.volume_changed": {
        "en": "{name}: volume {old}% → {new}% (off target by {diff:+.1f} dB)",
        "ja": "{name} の音量を {old}% → {new}% に変更 (目標との差 {diff:+.1f}dB)",
    },
    "log.pinned": {
        "en": "{name} is still too quiet at 200%. Ask them to turn up their microphone.",
        "ja": "{name} は 200% でも目標に届きません。本人にマイク音量を上げてもらってください",
    },
    "log.stats": {
        "en": "Stats: used {adopted} / skipped (overlap) {discarded} ({rate}%) / "
        "audio chunks {chunks} / non-silent blocks {loud} / speaking events {speak}",
        "ja": "統計: 採用 {adopted} / 同時発話で除外 {discarded} (除外率 {rate}%) / "
        "音声チャンク {chunks} / 音ありブロック {loud} / 発話イベント {speak}",
    },
    # ---- お知らせ(画面上部の帯) ----
    "notice.attenuation": {
        "en": "Discord's Attenuation is set to {value}%. Set it to 0% in User Settings → "
        "Voice & Video → Attenuation, otherwise volumes can't be measured correctly.",
        "ja": "Discord の［減衰］が {value}% になっています。［ユーザー設定］→［音声・ビデオ］→"
        "［減衰］を 0% にしてください。このままだと音量を正しく測れません",
    },
    "notice.capture": {
        "en": "This PC can't capture Discord's audio alone, so all PC audio is measured. "
        "Games or music playing at the same time will affect the result.",
        "ja": "この PC では Discord の音だけを取り出せないため、PC 全体の音で測っています。"
        "ゲームや音楽を流していると正しく測れません",
    },
    # ---- エンジンのエラー ----
    "err.no_discord": {"en": "Discord is not running", "ja": "Discord が起動していません"},
    "err.disconnected": {"en": "Lost connection to Discord", "ja": "Discord との接続が切れました"},
    "err.disconnected_detail": {
        "en": "Lost connection to Discord ({detail})",
        "ja": "Discord との接続が切れました ({detail})",
    },
    "err.redirect": {
        "en": "No redirect URL is registered in your Discord application. "
        "Check step 2 of the setup.",
        "ja": "Discord のアプリにリダイレクト URL が登録されていません。"
        "設定のステップ 2 を確認してください",
    },
    "err.auth_timeout": {
        "en": "[Authorize] was not clicked in Discord. Press [Start] to try again.",
        "ja": "Discord の画面で［認証］が押されませんでした。もう一度［開始］を押してください",
    },
    "err.auth_failed": {
        "en": "Authorization in Discord failed: {detail}",
        "ja": "Discord での認証に失敗しました: {detail}",
    },
    "err.bad_secret": {
        "en": "The Client Secret seems to be wrong. Paste it again in the setup.",
        "ja": "Client Secret が正しくないようです。設定から貼り付け直してください",
    },
    "err.token_http": {
        "en": "Failed to get a login token (HTTP {code})",
        "ja": "ログイン情報の取得に失敗しました (HTTP {code})",
    },
    "err.offline": {
        "en": "Could not connect to the internet: {detail}",
        "ja": "インターネットに接続できませんでした: {detail}",
    },
    "err.login_failed": {
        "en": "Failed to log in to Discord: {detail}",
        "ja": "Discord へのログインに失敗しました: {detail}",
    },
    "err.unexpected": {"en": "Unexpected error: {detail}", "ja": "予期しないエラー: {detail}"},
    # ---- セットアップ画面 ----
    "setup.title": {"en": "Getting started (one-time setup)", "ja": "はじめに（最初の 1 回だけ）"},
    "setup.intro": {
        "en": "This tool changes volumes through Discord's own interface, so you need "
        "your own \"Discord application\". It's free and takes a minute or two.",
        "ja": "このツールは Discord の機能を使って音量を変えるため、あなた専用の"
        "「Discord アプリ」が必要です。無料で、1〜2 分で作れます。",
    },
    "setup.step1.title": {"en": "Create a Discord application", "ja": "Discord アプリを作る"},
    "setup.step1.desc": {
        "en": "Open the Developer Portal with the button below and click "
        "[New Application] in the top right. Any name is fine.",
        "ja": "下のボタンで Developer Portal を開き、右上の［New Application］を"
        "押して作成します（名前は自由です）。",
    },
    "setup.step1.button": {"en": "Open Developer Portal", "ja": "Developer Portal を開く"},
    "setup.step2.title": {"en": "Add the redirect URL", "ja": "リダイレクト URL を登録する"},
    "setup.step2.desc": {
        "en": "Open [OAuth2] in the left menu, click [Add Redirect] under [Redirects], "
        "paste the URL below, then click [Save Changes].",
        "ja": "左メニューの［OAuth2］を開き、［Redirects］の［Add Redirect］に"
        "下の URL を貼り付けて［Save Changes］を押します。",
    },
    "setup.copy": {"en": "Copy", "ja": "コピー"},
    "setup.copied": {"en": "Copied", "ja": "コピーしました"},
    "setup.step3.title": {"en": "Paste the ID and secret", "ja": "ID とシークレットを貼り付ける"},
    "setup.step3.desc": {
        "en": "On the same [OAuth2] page, copy the Client ID and paste it below. "
        "For the Client Secret, click [Reset Secret] to reveal it, then copy and paste it.",
        "ja": "同じ［OAuth2］ページの Client ID をコピーして貼り付けます。"
        "Client Secret は［Reset Secret］を押すと表示されるので、それを"
        "コピーして貼り付けます。",
    },
    "setup.paste": {"en": "Paste", "ja": "貼り付け"},
    "setup.show": {"en": "Show", "ja": "表示"},
    "setup.save": {"en": "Save and start", "ja": "保存して開始"},
    "setup.back": {"en": "Back", "ja": "戻る"},
    "setup.note": {
        "en": "Your ID and secret are stored only on this PC and never sent anywhere else. "
        "Call audio is never recorded or sent.",
        "ja": "ID とシークレットはこの PC の中だけに保存され、外部には送信されません。"
        "通話の音声も保存・送信しません。",
    },
    "setup.err_id": {
        "en": "The Client ID is a long number (e.g. 1234567890123456789). "
        "Please copy it again.",
        "ja": "Client ID は数字だけの長い番号です（例: 1234567890123456789）。"
        "コピーし直してください。",
    },
    "setup.err_secret": {
        "en": "The Client Secret is too short. Copy the whole string shown after "
        "[Reset Secret].",
        "ja": "Client Secret が短すぎます。［Reset Secret］で表示された文字列を"
        "丸ごとコピーしてください。",
    },
    # ---- 設定ダイアログ ----
    "settings.title": {"en": "Settings", "ja": "設定"},
    "settings.target.title": {"en": "Target volume", "ja": "目標の音量"},
    "settings.target.desc": {
        "en": "Everyone's volume is evened out to this level.",
        "ja": "全員の音量をこの大きさに揃えます",
    },
    "settings.target.quieter": {"en": "Quieter", "ja": "小さめ"},
    "settings.target.louder": {"en": "Louder", "ja": "大きめ"},
    "settings.target.value_default": {"en": "{v} dB (default)", "ja": "{v} dB（標準）"},
    "settings.target.value": {
        "en": "{v} dB (default: {d} dB)",
        "ja": "{v} dB（標準は {d} dB）",
    },
    "settings.style.title": {"en": "Balancing", "ja": "揃え方"},
    "settings.style.desc": {
        "en": "For people whose loudness varies, choose which part of their voice to match.",
        "ja": "声の大きさが場面で変わる人を、どの声に合わせるかを選びます",
    },
    "settings.style.loud": {
        "en": "Match their louder moments (easy on the ears, recommended)",
        "ja": "大きい声を基準に揃える（耳にやさしい・おすすめ）",
    },
    "settings.style.balanced": {"en": "Balanced", "ja": "バランスよく揃える"},
    "settings.style.quiet": {
        "en": "Make quiet speakers easier to hear (shouting will get loud)",
        "ja": "小さい声の人も聞こえやすくする（大声の瞬間は大きくなります）",
    },
    "settings.language.title": {"en": "Language / 言語", "ja": "言語 / Language"},
    "settings.language.auto": {
        "en": "Automatic (Windows display language)",
        "ja": "自動（Windows の表示言語）",
    },
    "settings.language.en": {"en": "English", "ja": "English"},
    "settings.language.ja": {"en": "日本語", "ja": "日本語"},
    "settings.tip": {
        "en": "Tip: In Discord, set User Settings → Voice & Video → Attenuation to 0%. "
        "Otherwise volumes can't be measured correctly.",
        "ja": "ヒント: Discord の［ユーザー設定］→［音声・ビデオ］→［減衰］は 0% に"
        "してください。ON のままだと音量を正しく測れません。",
    },
    "settings.redo": {"en": "Redo Discord app setup", "ja": "Discord アプリの設定をやり直す"},
    "settings.cancel": {"en": "Cancel", "ja": "キャンセル"},
    "settings.save": {"en": "Save", "ja": "保存"},
    # ---- CLI ----
    "cli.description": {
        "en": "Automatically evens out each speaker's volume in Discord calls",
        "ja": "Discord 通話の話者ごとの音量を自動的に一定レベルへ揃える",
    },
    "cli.config_help": {
        "en": "config file (default: ./config.toml)",
        "ja": "設定ファイル(既定: ./config.toml)",
    },
    "cli.no_config": {
        "en": "Config file not found: {path}\nCopy config.example.toml and fill in "
        "client_id / client_secret (see the README).",
        "ja": "設定ファイルが見つかりません: {path}\nconfig.example.toml をコピーして "
        "client_id / client_secret を設定してください(README を参照)。",
    },
    "cli.exiting": {"en": "Exiting", "ja": "終了します"},
}
