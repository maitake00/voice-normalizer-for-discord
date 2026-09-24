"""ユーザーごとのローリングヒストグラム + パーセンタイル推定(SPEC §2)。

肝は「素の声量の逆算」:
    L_raw = L_measured - 20*log10(volume / 100)
測定値は自分がかけたゲイン込みなので、これをしないとフィードバックが発散する。
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class EstimatorConfig:
    """初期値はすべて暫定。v0.1 の実測で決める(SPEC §2, §7)。"""

    percentile: float = 87.5  # 声量とみなすパーセンタイル(85〜90 あたりから実測)
    window: int = 600  # 保持するブロック数(100ms × 600 = 60 秒)
    min_samples: int = 50  # 補正を開始する最低サンプル数


class RawLoudnessEstimator:
    """単独発話ブロックの測定値から、ユーザーごとの「素の声量」を推定する。

    - 測定値から現在の volume% ゲインを差し引いた raw 値を蓄積する
    - 平均ではなく高めのパーセンタイルを使う。混入したノイズフレームは
      下側に落ちて無視される(SPEC §2-5)
    - min_samples に達するまで推定値を返さない(寡黙な人で推定が暴れる
      のを防ぐ。SPEC §2-6)
    """

    def __init__(self, config: EstimatorConfig | None = None) -> None:
        self.config = config or EstimatorConfig()
        self._histograms: dict[str, deque[float]] = {}

    def add_block(self, user_id: str, measured_db: float, volume_percent: int) -> None:
        """単独発話ブロック 1 つ分の測定値を蓄積する。

        volume_percent が 0 のユーザーは逆算不能(かつ意図的なミュートの
        可能性が高い)ため破棄する。
        """
        if volume_percent <= 0:
            return
        raw_db = measured_db - 20.0 * math.log10(volume_percent / 100.0)
        hist = self._histograms.get(user_id)
        if hist is None:
            hist = deque(maxlen=self.config.window)
            self._histograms[user_id] = hist
        hist.append(raw_db)

    def estimate(self, user_id: str) -> float | None:
        """ユーザーの素の声量(dB)。サンプル不足なら None。"""
        hist = self._histograms.get(user_id)
        if hist is None or len(hist) < self.config.min_samples:
            return None
        # ヒストグラムは高々 window 個なので毎回計算しても十分軽い
        sorted_vals = sorted(hist)
        rank = (self.config.percentile / 100.0) * (len(sorted_vals) - 1)
        lo = int(math.floor(rank))
        hi = int(math.ceil(rank))
        if lo == hi:
            return sorted_vals[lo]
        frac = rank - lo
        return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac

    def sample_count(self, user_id: str) -> int:
        hist = self._histograms.get(user_id)
        return 0 if hist is None else len(hist)

    def user_ids(self) -> list[str]:
        return list(self._histograms)

    def reset(self, user_id: str) -> None:
        self._histograms.pop(user_id, None)
