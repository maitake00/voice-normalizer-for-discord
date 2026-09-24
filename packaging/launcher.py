"""PyInstaller 用エントリポイント(GUI 版)。"""

import sys

from voice_normalizer_for_discord.gui import main

if __name__ == "__main__":
    sys.exit(main())
