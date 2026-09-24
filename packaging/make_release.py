"""テスト配布用の zip を作る。

    python packaging/make_release.py            # exe をビルドしてから zip 化
    python packaging/make_release.py --no-build # 既存の dist の exe を使う

出力: release/VoiceNormalizerForDiscord-v<version>.zip
  VoiceNormalizerForDiscord/
    VoiceNormalizerForDiscord.exe
    README.txt                  (英語)
    はじめにお読みください.txt  (日本語)
    LICENSE.txt

利用者の設定・トークン(%APPDATA% 側)は exe に含まれないので、zip にも入らない。
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from voice_normalizer_for_discord import __version__  # noqa: E402

EXE_NAME = "VoiceNormalizerForDiscord.exe"
FOLDER = "VoiceNormalizerForDiscord"


def build_exe() -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--onefile",
            "--windowed",
            "--name",
            "VoiceNormalizerForDiscord",
            "--exclude-module",
            "PIL",
            "--exclude-module",
            "pytest",
            str(ROOT / "packaging" / "launcher.py"),
        ],
        cwd=ROOT,
        check=True,
    )


def notepad_text(text: str) -> bytes:
    """メモ帳で確実に読めるよう BOM 付き UTF-8 + CRLF にする。"""
    return text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8-sig")


def main() -> int:
    if "--no-build" not in sys.argv:
        build_exe()

    exe = ROOT / "dist" / EXE_NAME
    if not exe.exists():
        sys.exit(f"exe が見つかりません: {exe}")

    # GitHub Actions 上では GITHUB_REPOSITORY(owner/repo)が入る
    repo = os.environ.get("GITHUB_REPOSITORY")
    repo_url = f"https://github.com/{repo}" if repo else "(GitHub)"

    def tester_readme(lang: str) -> str:
        text = (ROOT / "packaging" / f"tester_readme.{lang}.txt").read_text(encoding="utf-8")
        return text.replace("{version}", __version__).replace("{repo_url}", repo_url)

    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")

    out_dir = ROOT / "release"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"VoiceNormalizerForDiscord-v{__version__}.zip"

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.write(exe, f"{FOLDER}/{EXE_NAME}")
        z.writestr(f"{FOLDER}/README.txt", notepad_text(tester_readme("en")))
        z.writestr(f"{FOLDER}/はじめにお読みください.txt", notepad_text(tester_readme("ja")))
        z.writestr(f"{FOLDER}/LICENSE.txt", notepad_text(license_text))

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"作成しました: {out} ({size_mb:.1f} MB)")
    with zipfile.ZipFile(out) as z:
        for info in z.infolist():
            print(f"  {info.filename}  ({info.file_size / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
