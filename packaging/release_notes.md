Test version of a tool that automatically evens out each person's volume in Discord calls.
(日本語の説明は下にあります)

## Download

Download `VoiceNormalizerForDiscord-{version}.zip` from **Assets** below, extract it, and read `README.txt` inside.

- Windows 11 recommended / requires the Discord desktop app
- Everyone needs to create their own Discord application (free, 2-3 minutes; the steps are in the zip and in the app)
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
- 使う人それぞれが、自分用の Discord アプリを作る必要があります(無料・2〜3 分。手順は zip 内と起動画面にあります)
- 通話の音声を保存・送信することはありません。変わるのはあなたの側で聞こえる音量だけです
- この exe は、このリポジトリのソースコードから GitHub Actions で自動ビルドしたものです
- 署名がないため「Windows によって PC が保護されました」と表示されることがあります。[詳細情報] → [実行] で起動できます
- ダウンロードしたファイルの確認方法は、上の「Verifying your download」を参照してください

不具合や感想は [Issues](https://github.com/{repo}/issues) へどうぞ。
