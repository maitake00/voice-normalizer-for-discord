"""Discord クライアントとの連携(RPC / OAuth)。

sink 層はここに閉じ込め、将来 Vencord/BetterDiscord プラグイン版の
バックエンドと差し替えられる形を保つ(SPEC §6)。
"""

from .rpc import DiscordRPC, DiscordRPCError, DiscordRPCTimeout

__all__ = ["DiscordRPC", "DiscordRPCError", "DiscordRPCTimeout"]
