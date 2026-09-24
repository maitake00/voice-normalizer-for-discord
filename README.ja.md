# Voice Normalizer for Discord

[English](README.md) | 日本語

Discord の通話で、相手ごとの音量を自動的に一定レベルへ揃えるツールです。変わるのはあなたの側で聞こえる音量だけです。

> **現在テスト版です。** 実際の通話での動作を検証中のため、挙動や初期値は変わる可能性があります。

## ダウンロード

[Releases](../../releases) から最新の `VoiceNormalizerForDiscord-vX.Y.Z.zip` をダウンロードし、展開して中の `はじめにお読みください.txt` を読んでください。

- 必要環境: Windows 11 推奨 / Discord のデスクトップアプリ(ブラウザ版は非対応)
- 配布している exe は、このリポジトリのソースから [GitHub Actions](.github/workflows/release.yml) で自動ビルドしたものです。ビルド証明(attestation)と SHA256 を添付しているので、ダウンロードしたファイルがこのリポジトリでビルドされたものか確認できます(手順は各 Release の説明を参照)
- 署名がないため、初回起動時に「Windows によって PC が保護されました」と表示されることがあります。[詳細情報] → [実行] で起動できます

## 仕組み — 音声は加工しない

Discord には話者ごとの音量を自動で揃える機能がなく、ユーザーごとの音量スライダー(0〜200%)を手動で調整するしかありません。また、Discord の出力はミックス済みの 1 本で、OS からは話者ごとに分離できません。

そこで本ツールは音声そのものには一切手を触れず、**音量を測って Discord 自身の「ユーザーの音量」設定を書き換えます**。スライダーを自動で動かしているのと同じです。

- 遅延ゼロ、音質劣化ゼロ
- 調整した音量は Discord 側に保存される(ツールを閉じても残る)

```
[capture]   Discord が再生する音声だけを取得(WASAPI プロセスループバック)
[speaking]  誰が喋っているか(Discord RPC の SPEAKING_START/STOP)
[core]      K 特性ラウドネスの推定 + 制御ループ(純粋ロジック)
[sink]      ユーザーごとの volume% を書き込む(Discord RPC)
```

「今ちょうど 1 人だけ喋っている」区間だけを測定し、その人の声量の高めのパーセンタイルを「その人の声の大きさ」とみなして、目標との差をデッドバンドと 1 回あたりの上限付きでゆっくり補正します。

## プライバシーと免責

- **音声はメモリ上で解析するだけで、保存も外部送信も一切しません。**
  音声に触れるのは [capture/windows_process.py](src/voice_normalizer_for_discord/capture/windows_process.py)(取得)と [core/loudness.py](src/voice_normalizer_for_discord/core/loudness.py)(dB 算出)のみで、算出後のサンプルは破棄されます。ネットワーク通信は Discord とのローカル RPC 接続と、Discord との OAuth トークン交換だけです。
  (`debug.frame_log` を有効にした場合のみ、dB 値の数値ログがローカルに保存されます。音声データは含まれません)
- Discord の公式ツールではありません。**自己責任でご利用ください。**

## 使い方

1. `VoiceNormalizerForDiscord.exe` を起動する
2. 初回だけ 3 ステップのセットアップ画面が出るので、案内に従って自分の Discord アプリを作り、Client ID / Client Secret を貼り付ける
   (未承認アプリは Discord RPC を使えないため、使う人それぞれが自分のアプリを作る必要があります。作成は無料で、アプリのオーナーは承認なしで RPC を使えます)
3. 初回だけ Discord の画面に確認ダイアログが出るので［認証］を押す
4. あとはボイスチャンネルで通話するだけ

起動すると自動で開始し、Discord が起動していないときや接続が切れたときは 5 秒ごとに自動で再接続します。通話を抜けたり別のチャンネルに移ったりしても自動で追従します。

画面の見方:

- 上部のカードに今の状態と、次にすることを表示します。調整中は「音声を受信中」「話し声を検出」で動作状況も確認できます
- メンバーごとのカードに、Discord の音量(%)と状態(聞き取り中 → 調整中 → ✓ ちょうどいい音量)を表示します。話している人は緑の枠になります
- 「数値を表示」をオンにすると、声の大きさ(dB)や目標との差を表示します
- ［設定］で「目標の音量」「揃え方」(下記のトレードオフ)「言語」(日本語 / 英語。既定は Windows の表示言語)を変えられます

設定は `%APPDATA%\VoiceNormalizerForDiscord\config.toml` に保存されます。

**重要**: Discord の［ユーザー設定］→［音声・ビデオ］→ **［減衰］は 0% にしてください**。ON だと「誰かが喋ると他の音を下げる」処理で測定値が狂い、正しく揃いません(ON のときは画面で警告します)。

## 揃え方のトレードオフ(重要)

これは技術的な正解がない、**ポリシーの選択**です。「揃え方」の設定は、各人の声のどの部分に合わせるか(`percentile` パラメータ)を決めます。

- **高め(90 パーセンタイル付近)** → 大声のピークが揃う。耳は守られるが、ボソボソ喋る人は相変わらず聞こえにくい
- **低め(中央値付近)** → 小声の人が聞こえるようになる。代わりにその人が叫んだ瞬間は大きくなる

既定値(87.5)は「耳を守る」側に寄せています。通話する相手に合わせて調整してください。

## 既知の制限

- **Go Live(配信)の音声は除外できません**。Discord 自身が再生しているため、プロセス単位では区別できず、視聴中は測定に影響します
- 200% でも目標に届かない人は救えません(Discord の上限)。その場合「本人にマイク音量を上げてもらってください」と表示します
- 2 人以上が同時に話している区間は測定しません。除外した割合はログで確認できます
- Discord の音だけを取り出せない PC(プロセスループバックには Windows 10 build 20348 以降 / Windows 11 が必要)では、出力全体の音で測る方式に自動で切り替わり、警告を表示します。その場合はゲームや音楽が測定に影響します

## 開発者向け

### テスト

コアロジック(`core/`)は OS・IO から完全に分離された純粋関数群で、合成音声による収束テストがあります。エンジンには、Discord と音声デバイスを偽物に差し替えた結合テストがあります。

```powershell
pip install -e .[dev]
pytest
```

### exe / 配布用 zip のビルド

```powershell
pip install -e .[dev]
python packaging\make_release.py
# → dist\VoiceNormalizerForDiscord.exe と release\VoiceNormalizerForDiscord-v<version>.zip
```

公開用のビルドは手元では行いません。`v*` タグを push すると、[release.yml](.github/workflows/release.yml) がテスト → ビルド → SHA256・ビルド証明の添付 → Release 作成 を行います。

### CLI

Discord デスクトップアプリを起動した状態で:

```powershell
pip install .
copy config.example.toml config.toml
# config.toml に client_id / client_secret を記入
voice-normalizer-for-discord --config config.toml
```

### パラメータ

設定できるのは以下のみです([config.example.toml](config.example.toml))。

| 名前 | 説明 | 既定値 |
|---|---|---|
| `target_db` | 目標ラウドネス | -24.0 |
| `percentile` | 声の大きさとみなすパーセンタイル | 87.5 |
| `window` | ヒストグラムの窓長(100 ms のブロック数) | 600 |
| `min_samples` | 補正を始める最低サンプル数 | 50 |
| `deadband_db` | これより小さい差は補正しない | 1.5 |
| `max_step_db` | 1 回の補正の上限 | 3.0 |

### 音声の取り込み方式

OBS の「アプリケーション音声キャプチャ」と同じ **WASAPI プロセスループバック**(`ActivateAudioInterfaceAsync` + `AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS`)で、**Discord のプロセスツリーが再生する音声だけ**を取り込みます。ゲームなど他のアプリの音は入りません。

## ライセンス

[MIT](LICENSE)
