"""目標との差分から volume% を決定する制御ループ(SPEC §2-7)。

- デッドバンド ±1.5dB(微差では動かさない)
- 1 回の補正は ±3dB まで、EMA でゆっくり収束
- 200% に張り付くユーザーは救えない → pinned_at_max で通知する
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# EMA の平滑化係数。設定可能パラメータは SPEC §2 の表のみと決めているため、
# これは公開設定にしない(説明できないパラメータを増やさない)。
_EMA_ALPHA = 0.5

MIN_VOLUME = 1  # 0 にすると素の声量が逆算不能になるため下限は 1
MAX_VOLUME = 200  # Discord の上限(SPEC §4-5)


@dataclass(frozen=True)
class ControllerConfig:
    target_db: float = -24.0  # 目標ラウドネス(暫定。v0.1 で実測して決める)
    deadband_db: float = 1.5
    max_step_db: float = 3.0


@dataclass(frozen=True)
class Adjustment:
    new_volume: int
    changed: bool
    pinned_at_max: bool  # 200% でも目標に届かない → マイクゲインを上げてもらう
    error_db: float  # 目標との差分(ログ用)


def _gain_db(volume_percent: int) -> float:
    return 20.0 * math.log10(volume_percent / 100.0)


class VolumeController:
    def __init__(self, config: ControllerConfig | None = None) -> None:
        self.config = config or ControllerConfig()
        self._ema_step: dict[str, float] = {}

    def update(self, user_id: str, current_volume: int, raw_db: float) -> Adjustment:
        """推定された素の声量から次の volume% を決める。

        current_volume は Discord に現在設定されている値(0〜200)。
        raw_db は estimator の推定値(ゲイン差し引き済みの素の声量)。
        """
        cfg = self.config
        if current_volume <= 0:
            # ミュート中のユーザーには触らない
            return Adjustment(current_volume, False, False, 0.0)

        perceived_db = raw_db + _gain_db(current_volume)
        error_db = cfg.target_db - perceived_db

        if abs(error_db) <= cfg.deadband_db:
            self._ema_step.pop(user_id, None)
            return Adjustment(current_volume, False, False, error_db)

        step = max(-cfg.max_step_db, min(cfg.max_step_db, error_db))
        prev = self._ema_step.get(user_id, 0.0)
        smoothed = _EMA_ALPHA * step + (1.0 - _EMA_ALPHA) * prev
        self._ema_step[user_id] = smoothed

        new_gain_db = _gain_db(current_volume) + smoothed
        new_volume = round(100.0 * 10.0 ** (new_gain_db / 20.0))
        new_volume = max(MIN_VOLUME, min(MAX_VOLUME, new_volume))

        pinned = new_volume >= MAX_VOLUME and error_db > cfg.deadband_db
        return Adjustment(
            new_volume=new_volume,
            changed=new_volume != current_volume,
            pinned_at_max=pinned,
            error_db=error_db,
        )

    def reset(self, user_id: str) -> None:
        self._ema_step.pop(user_id, None)
