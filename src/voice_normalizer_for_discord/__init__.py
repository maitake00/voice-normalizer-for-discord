"""Voice Normalizer for Discord.

受信側で Discord 通話の話者ごとの音量を自動的に一定レベルへ揃える。
音声は加工せず、測定して Discord 自身の「ユーザーの音量」設定を
書き換えるフィードバック制御として動作する(SPEC §0)。
"""

__version__ = "0.1.0"
