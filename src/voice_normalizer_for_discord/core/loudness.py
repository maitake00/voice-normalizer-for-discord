"""K-weighting フィルタとブロックラウドネス算出。

BS.1770 から K-weighting フィルタ「のみ」借用する(SPEC §5)。
絶対ゲート・相対ゲートは実装しない。ゲートは speaking フラグと
パーセンタイル推定(estimator)が担う。
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import lfilter

# BS.1770 の K-weighting を構成する 2 段のフィルタのパラメータ。
# 任意のサンプリングレートに対して係数を再計算する(48kHz 固定係数を使わない)。
_PRE_SHELF_F0 = 1681.9744509555319
_PRE_SHELF_GAIN_DB = 3.99984385397
_PRE_SHELF_Q = 0.7071752369554196
_RLB_HIGHPASS_F0 = 38.13547087602444
_RLB_HIGHPASS_Q = 0.5003270373238773

# ブロックの平均二乗がこれ未満なら無音とみなす下限値
_SILENCE_FLOOR = 1e-12
SILENCE_DB = -120.0


def _high_shelf(fs: float) -> tuple[np.ndarray, np.ndarray]:
    a_gain = 10.0 ** (_PRE_SHELF_GAIN_DB / 40.0)
    w0 = 2.0 * math.pi * _PRE_SHELF_F0 / fs
    alpha = math.sin(w0) / (2.0 * _PRE_SHELF_Q)
    cos_w0 = math.cos(w0)
    sqrt_a2 = 2.0 * math.sqrt(a_gain) * alpha

    b = np.array(
        [
            a_gain * ((a_gain + 1) + (a_gain - 1) * cos_w0 + sqrt_a2),
            -2.0 * a_gain * ((a_gain - 1) + (a_gain + 1) * cos_w0),
            a_gain * ((a_gain + 1) + (a_gain - 1) * cos_w0 - sqrt_a2),
        ]
    )
    a = np.array(
        [
            (a_gain + 1) - (a_gain - 1) * cos_w0 + sqrt_a2,
            2.0 * ((a_gain - 1) - (a_gain + 1) * cos_w0),
            (a_gain + 1) - (a_gain - 1) * cos_w0 - sqrt_a2,
        ]
    )
    return b / a[0], a / a[0]


def _high_pass(fs: float) -> tuple[np.ndarray, np.ndarray]:
    w0 = 2.0 * math.pi * _RLB_HIGHPASS_F0 / fs
    alpha = math.sin(w0) / (2.0 * _RLB_HIGHPASS_Q)
    cos_w0 = math.cos(w0)

    b = np.array([(1 + cos_w0) / 2.0, -(1 + cos_w0), (1 + cos_w0) / 2.0])
    a = np.array([1 + alpha, -2.0 * cos_w0, 1 - alpha])
    return b / a[0], a / a[0]


class KWeightingFilter:
    """ストリーミング入力に K-weighting を適用する(状態保持)。"""

    def __init__(self, fs: float) -> None:
        self._sections = [_high_shelf(fs), _high_pass(fs)]
        self._state = [np.zeros(2) for _ in self._sections]

    def process(self, samples: np.ndarray) -> np.ndarray:
        y = np.asarray(samples, dtype=np.float64)
        for i, (b, a) in enumerate(self._sections):
            y, self._state[i] = lfilter(b, a, y, zi=self._state[i])
        return y

    def reset(self) -> None:
        self._state = [np.zeros(2) for _ in self._sections]


class BlockLoudnessMeter:
    """モノラル音声を固定長ブロックに切り、K-weighted ラウドネス(dB)を返す。

    100ms ブロックごとに dB を算出する(SPEC §2-3)。
    """

    def __init__(self, fs: int, block_ms: int = 100) -> None:
        if fs <= 0:
            raise ValueError("fs must be positive")
        self.fs = fs
        self.block_size = max(1, int(fs * block_ms / 1000))
        self._filter = KWeightingFilter(fs)
        self._buffer = np.empty(0, dtype=np.float64)

    def feed(self, samples: np.ndarray) -> list[float]:
        """サンプルを追加し、完成したブロックのラウドネス(dB)を返す。"""
        filtered = self._filter.process(samples)
        self._buffer = np.concatenate([self._buffer, filtered])

        blocks: list[float] = []
        while self._buffer.size >= self.block_size:
            block, self._buffer = (
                self._buffer[: self.block_size],
                self._buffer[self.block_size :],
            )
            blocks.append(self._block_db(block))
        return blocks

    @staticmethod
    def _block_db(block: np.ndarray) -> float:
        mean_square = float(np.mean(block * block))
        if mean_square < _SILENCE_FLOOR:
            return SILENCE_DB
        return -0.691 + 10.0 * math.log10(mean_square)
