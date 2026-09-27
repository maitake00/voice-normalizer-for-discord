Test version of a tool that automatically evens out each person's volume in Discord calls.
(日本語の説明は下にあります)

## Download

Download `VoiceNormalizerForDiscord-{version}.zip` from **Assets** below, extract it, and read `README.txt` inside.

- Windows 11 recommended / requires the Discord desktop app
- On first launch, choose how to use it:
  - **Invited as a tester** (Discord friends of the person who shared this): accept the invitation email, then just click [Authorize] in Discord.
  - **Use my own Discord application** (everyone else): no friend request or invitation needed; the app guides you through a 1-2 minute setup.
- Call audio is never recorded or sent anywhere. Only what you hear changes.

## About this file

- The exe is built automatically from this repository's source code by GitHub Actions (see the Actions tab for the build log).
- Because it is not code-signed, Windows may show "Windows protected your PC". Click [More info] → [Run anyway].

## Verifying your download (optional)

- Check that the file wasn't corrupted or modified: run the following in PowerShell and compare it with the value in the matching `.sha256` file.
  ```
  Get-FileHash .\VoiceNormalizerForDiscord-{version}.zip
  ```
- Check that it was built by this repository, using the [GitHub CLI](https://cli.github.com/):
  ```
  gh attestation verify VoiceNormalizerForDiscord-{version}.zip --repo {repo}
  ```

Please report problems and feedback in [Issues](https://github.com/{repo}/issues).

---

## 日本語

Discord の通話で、相手ごとの音量を自動で揃えるツールのテスト版です。

下の **Assets** から `VoiceNormalizerForDiscord-{version}.zip` をダウンロードし、展開してから中の `はじめにお読みください.txt` を読んでください。

- Windows 11 推奨 / Discord のデスクトップアプリが必要です
- 初めて起動すると、使い方を選ぶ画面が出ます
  - **テスターとして招待された**(配布した人の Discord フレンド): 届いた招待メールを承認し、あとは Discord の画面で［認証］を押すだけです
  - **自分の Discord アプリで使う**(それ以外の人): フレンド登録や招待は不要です。画面の案内に従って 1〜2 分で準備できます
- 通話の音声を保存・送信することはありません。変わるのはあなたの側で聞こえる音量だけです
- この exe は、このリポジトリのソースコードから GitHub Actions で自動ビルドしたものです
- 署名がないため「Windows によって PC が保護されました」と表示されることがあります。[詳細情報] → [実行] で起動できます
- ダウンロードしたファイルの確認方法は、上の「Verifying your download」を参照してください

不具合や感想は [Issues](https://github.com/{repo}/issues) へどうぞ。
