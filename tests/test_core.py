"""core の収束テスト。IO は一切なし(SPEC §1, §9)。

既知の dB 差を持つ合成音声で複数話者を模し、
loudness → estimator → controller のループが目標へ収束することを検証する。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from voice_normalizer_for_discord.core import (
    BlockLoudnessMeter,
    ControllerConfig,
    EstimatorConfig,
    RawLoudnessEstimator,
    VolumeController,
)

FS = 48_000


def synth_voice(rng: np.random.Generator, seconds: float, rms_db: float) -> np.ndarray:
    """指定 RMS(dBFS)の白色ノイズで発話を模す。"""
    n = int(FS * seconds)
    x = rng.standard_normal(n)
    x = x / np.sqrt(np.mean(x * x))
    return x * 10.0 ** (rms_db / 20.0)


def apply_volume(signal: np.ndarray, volume_percent: int) -> np.ndarray:
    """Discord の volume% を線形ゲインとして適用する。"""
    return signal * (volume_percent / 100.0)


class TestLoudness:
    def test_relative_level_is_preserved(self):
        """入力を 20dB 下げれば測定値もちょうど 20dB 下がる。"""
        rng = np.random.default_rng(0)
        base = synth_voice(rng, 2.0, -20.0)

        meter1 = BlockLoudnessMeter(FS)
        meter2 = BlockLoudnessMeter(FS)
        loud = np.median(meter1.feed(base))
        quiet = np.median(meter2.feed(base * 0.1))

        assert loud - quiet == pytest.approx(20.0, abs=0.1)

    def test_blocks_are_100ms(self):
        meter = BlockLoudnessMeter(FS, block_ms=100)
        blocks = meter.feed(np.zeros(FS))  # 1 秒
        assert len(blocks) == 10

    def test_silence_does_not_crash(self):
        meter = BlockLoudnessMeter(FS)
        blocks = meter.feed(np.zeros(FS))
        assert all(b <= -100.0 for b in blocks)


class TestEstimator:
    def test_back_calculation_removes_own_gain(self):
        """自分がかけたゲインが違っても素の声量の推定は同じになる。

        ここが崩れるとフィードバックが発散する(SPEC §2-4)。
        """
        est = RawLoudnessEstimator(EstimatorConfig(min_samples=10))
        raw_db = -25.0
        for volume in (50, 100, 150, 200):
            measured = raw_db + 20.0 * math.log10(volume / 100.0)
            for _ in range(10):
                est.add_block("u1", measured, volume)

        assert est.estimate("u1") == pytest.approx(raw_db, abs=1e-9)

    def test_noise_frames_fall_below_percentile(self):
        """混入したノイズフレームは下側に落ちて無視される(SPEC §2-5)。"""
        est = RawLoudnessEstimator(EstimatorConfig(percentile=87.5, min_samples=10))
        for _ in range(70):
            est.add_block("u1", -25.0, 100)
        for _ in range(30):
            est.add_block("u1", -55.0, 100)  # 3 割がノイズ

        assert est.estimate("u1") == pytest.approx(-25.0, abs=1.0)

    def test_no_estimate_before_min_samples(self):
        """寡黙な人で推定が暴れるのを防ぐ(SPEC §2-6)。"""
        est = RawLoudnessEstimator(EstimatorConfig(min_samples=50))
        for _ in range(49):
            est.add_block("u1", -25.0, 100)
        assert est.estimate("u1") is None

        est.add_block("u1", -25.0, 100)
        assert est.estimate("u1") is not None

    def test_muted_user_is_skipped(self):
        est = RawLoudnessEstimator()
        est.add_block("u1", -25.0, 0)  # volume 0 は逆算不能なので破棄
        assert est.sample_count("u1") == 0

    def test_window_is_rolling(self):
        est = RawLoudnessEstimator(EstimatorConfig(window=100, min_samples=10))
        for _ in range(100):
            est.add_block("u1", -40.0, 100)
        for _ in range(100):
            est.add_block("u1", -20.0, 100)  # 古い値を追い出す

        assert est.estimate("u1") == pytest.approx(-20.0, abs=0.5)


class TestController:
    def test_deadband_prevents_micro_adjustments(self):
        ctl = VolumeController(ControllerConfig(target_db=-24.0, deadband_db=1.5))
        adj = ctl.update("u1", 100, -25.0)  # 誤差 +1.0dB はデッドバンド内
        assert not adj.changed

    def test_step_is_limited(self):
        """1 回の補正は max_step_db まで。"""
        ctl = VolumeController(ControllerConfig(target_db=-24.0, max_step_db=3.0))
        adj = ctl.update("u1", 100, -50.0)  # 誤差 +26dB
        applied_db = 20.0 * math.log10(adj.new_volume / 100.0)
        assert applied_db <= 3.0 + 0.1

    def test_pinned_at_200(self):
        """200% の壁。救えないので通知フラグを立てる(SPEC §4-5)。"""
        ctl = VolumeController(ControllerConfig(target_db=-24.0))
        volume = 100
        pinned = False
        for _ in range(50):
            adj = ctl.update("u1", volume, -50.0)
            volume = adj.new_volume
            pinned = pinned or adj.pinned_at_max

        assert volume == 200
        assert pinned

    def test_muted_user_untouched(self):
        ctl = VolumeController()
        adj = ctl.update("u1", 0, -30.0)
        assert adj.new_volume == 0 and not adj.changed


class TestConvergence:
    """合成音声によるエンドツーエンドの収束テスト(SPEC §9-2)。"""

    TARGET_DB = -24.0

    def _run_simulation(
        self,
        speakers: dict[str, float],
        rounds: int = 40,
        overlap_ratio: float = 0.0,
    ) -> tuple[dict[str, int], RawLoudnessEstimator, list[bool]]:
        """単独発話を交互に繰り返す通話をシミュレートする。

        speakers: user_id -> 素の声量(RMS dBFS)
        戻り値: (最終 volume%, estimator, pinned フラグ履歴)
        """
        rng = np.random.default_rng(42)
        est = RawLoudnessEstimator(EstimatorConfig(min_samples=30, window=600))
        ctl = VolumeController(
            ControllerConfig(target_db=self.TARGET_DB, deadband_db=1.5, max_step_db=3.0)
        )
        meter = BlockLoudnessMeter(FS)  # 実際の音声はミックス済み 1 本(SPEC §0)
        volumes = {uid: 100 for uid in speakers}
        pinned_history: list[bool] = []

        for round_no in range(rounds):
            for uid, raw_db in speakers.items():
                voice = synth_voice(rng, 1.0, raw_db)
                heard = apply_volume(voice, volumes[uid])
                for block_db in meter.feed(heard):
                    # overlap_ratio 分のブロックは「2 人以上が同時発話」
                    # として破棄されたとみなす(採用しない)
                    if rng.random() < overlap_ratio:
                        continue
                    est.add_block(uid, block_db, volumes[uid])

            for uid in speakers:
                raw_est = est.estimate(uid)
                if raw_est is None:
                    continue
                adj = ctl.update(uid, volumes[uid], raw_est)
                pinned_history.append(adj.pinned_at_max)
                if adj.changed:
                    volumes[uid] = adj.new_volume

        return volumes, est, pinned_history

    def _perceived_db(self, est: RawLoudnessEstimator, uid: str, volume: int) -> float:
        raw = est.estimate(uid)
        assert raw is not None
        return raw + 20.0 * math.log10(volume / 100.0)

    def test_speakers_converge_to_target(self):
        """既知の dB 差を持つ 3 話者が全員デッドバンド内へ収束する。"""
        speakers = {"quiet": -32.0, "normal": -24.0, "loud": -15.0}
        volumes, est, _ = self._run_simulation(speakers)

        for uid in speakers:
            perceived = self._perceived_db(est, uid, volumes[uid])
            assert perceived == pytest.approx(self.TARGET_DB, abs=2.0), (
                f"{uid}: perceived={perceived:.1f}dB volume={volumes[uid]}%"
            )

        # 静かな人は上げ、うるさい人は下げているはず
        assert volumes["quiet"] > 100
        assert volumes["loud"] < 100

    def test_feedback_does_not_diverge(self):
        """収束後も補正が振動・発散しない(素の声量の逆算の検証)。"""
        speakers = {"a": -28.0, "b": -18.0}
        volumes, est, _ = self._run_simulation(speakers, rounds=60)

        # さらに 20 ラウンド回しても volume がほぼ動かないこと
        volumes2, est2, _ = self._run_simulation(speakers, rounds=80)
        for uid in speakers:
            gain1 = 20.0 * math.log10(volumes[uid] / 100.0)
            gain2 = 20.0 * math.log10(volumes2[uid] / 100.0)
            assert abs(gain1 - gain2) < 2.0

    def test_convergence_with_overlap_discard(self):
        """同時発話による破棄(4 割)があっても収束する(SPEC §4-4)。"""
        speakers = {"quiet": -30.0, "loud": -16.0}
        volumes, est, _ = self._run_simulation(speakers, overlap_ratio=0.4)

        for uid in speakers:
            perceived = self._perceived_db(est, uid, volumes[uid])
            assert perceived == pytest.approx(self.TARGET_DB, abs=2.0)

    def test_very_quiet_speaker_pins_at_200(self):
        """200% でも救えない話者は張り付き、通知フラグが立つ。"""
        speakers = {"whisper": -48.0}
        volumes, _, pinned_history = self._run_simulation(speakers)

        assert volumes["whisper"] == 200
        assert any(pinned_history)
