"""ノーマライザ本体のエンジン(CLI / GUI 共用)。

バックグラウンドスレッドで動作し、状態・補正・警告を events キューへ
発行する。UI(CLI の logger / GUI の画面)はキューを消費するだけにする。

イベント形式: {"kind": str, ...}
  status  {state, text, channel?}  state: connecting | authorizing |
                                          waiting | monitoring
  account {name}                   ログイン中の Discord ユーザー名
  notice  {key, level, msg, args}  画面上部に出す注意(level: tip | warning)
  log     {level, text}            ログ行(level: info | warning | error)
  users   {users: [dict]}          メンバー一覧のスナップショット
  stats   {adopted, discarded, rate, chunks, loud, speak, mode}
  error   {code, msg, args}        致命的エラー(エンジンは停止する)
                                   code: no_discord | disconnected |
                                         redirect | auth | not_tester | other
  stopped {}                       エンジン終了

notice / error の msg は i18n のキー。UI 側で t(msg, **args) して表示する
(言語を切り替えたときに表示し直せるように)。
"""

from __future__ import annotations

import queue
import threading
import time
import urllib.error
from pathlib import Path
from typing import Callable

from .core import (
    BlockLoudnessMeter,
    ControllerConfig,
    EstimatorConfig,
    RawLoudnessEstimator,
    VolumeController,
)
from .discord import DiscordRPC, DiscordRPCError, DiscordRPCTimeout
from .discord import oauth
from .i18n import t

_POLL_INTERVAL_SEC = 2.0  # チャンネル状態の再取得 + 制御ループの周期
_SNAPSHOT_INTERVAL_SEC = 1.0
_STATS_LOG_INTERVAL_SEC = 60.0
_MAX_CHUNKS_PER_TICK = 100
_LOUD_BLOCK_DB = -50.0  # これを超えるブロックを「音あり」とみなす(診断用)
# これ以上途切れずに「話している」ままならオープンマイク(雑音まで送りっぱなし)とみなす
_STALE_SPEAKING_SEC = 30.0


class EngineError(Exception):
    """UI に分類付きで伝えるエラー。msg は i18n のキー。"""

    def __init__(self, code: str, msg: str, **args) -> None:
        super().__init__(t(msg, **args))
        self.code = code
        self.msg = msg
        self.args_ = args


class SpeakingGate:
    """「今ちょうど 1 人だけ喋っている」区間のみ採用する(SPEC §2-1)。

    「話している」ままの人がいると、他の人が話すたびに「同時発話」として
    すべて捨てられ、誰も測定できなくなる。実際の通話では次の 2 つで起きた:
      - 話している途中で抜けた / ミュートした(SPEAKING_STOP が来ない)
        → retain() で外す
      - マイク感度が高く、雑音まで拾って Discord 上でも話しっぱなし
        (オープンマイク)→ expire_stale() で外し、open_mic として記録する。
        声と雑音を区別できないので、その人は測定しない。本人が一度話し終わる
        (SPEAKING_STOP)と通常に戻る
    """

    def __init__(self, self_user_id: str, clock=time.monotonic) -> None:
        self._self_id = self_user_id
        self._clock = clock
        self._since: dict[str, float] = {}  # user_id -> 話し始めた時刻
        self.open_mic: set[str] = set()  # 話しっぱなしで測定から外している人
        self.adopted = 0
        self.discarded_overlap = 0

    def on_start(self, user_id: str) -> None:
        if user_id != self._self_id and user_id not in self.open_mic:
            self._since[user_id] = self._clock()

    def on_stop(self, user_id: str) -> None:
        self._since.pop(user_id, None)
        self.open_mic.discard(user_id)

    def clear(self) -> None:
        self._since.clear()
        self.open_mic.clear()

    def retain(self, can_speak: set[str]) -> list[str]:
        """今話せる人(通話にいて、ミュートしていない人)以外を外す。外した人を返す。"""
        gone = [uid for uid in self._since if uid not in can_speak]
        for uid in gone:
            del self._since[uid]
        self.open_mic &= can_speak
        return gone

    def expire_stale(self, max_sec: float) -> list[str]:
        """max_sec 以上途切れずに「話している」人をオープンマイクとして外す。

        Discord は話している途中の短い間でも STOP / START を送り直すので、
        普通の会話が max_sec 途切れないことはまずない。外した人を返す。
        """
        now = self._clock()
        stale = [uid for uid, t0 in self._since.items() if now - t0 >= max_sec]
        for uid in stale:
            del self._since[uid]
            self.open_mic.add(uid)
        return stale

    def speaking_ids(self) -> set[str]:
        return set(self._since)

    def sole_speaker(self) -> str | None:
        """単独発話者の user_id。0 人か 2 人以上なら None(カウントも更新)。"""
        n = len(self._since)
        if n == 1:
            self.adopted += 1
            return next(iter(self._since))
        if n >= 2:
            self.discarded_overlap += 1
        return None

    def discard_rate(self) -> float:
        total = self.adopted + self.discarded_overlap
        return (self.discarded_overlap / total) if total else 0.0


class NormalizerEngine:
    """接続 → 認証 → 測定 → 補正 の常駐ループ。

    rpc_factory / capture_factory はテストで Discord と音声デバイスを
    差し替えるための継ぎ目。capture_factory は (capture, mode) を返す。
    """

    def __init__(
        self,
        config: dict,
        config_dir: Path,
        rpc_factory: Callable[[str], DiscordRPC] = DiscordRPC,
        capture_factory: Callable[[], tuple[object, str]] | None = None,
    ) -> None:
        self.config = config
        self.config_dir = config_dir
        self.events: queue.Queue[dict] = queue.Queue()
        self._rpc_factory = rpc_factory
        self._capture_factory = capture_factory or self._start_capture
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- 公開 API ----

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def request_stop(self) -> None:
        self._stop.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # ---- イベント発行 ----

    def _emit(self, kind: str, **data) -> None:
        self.events.put({"kind": kind, **data})

    def _status(self, state: str, text: str, **extra) -> None:
        self._emit("status", state=state, text=text, **extra)

    def _log(self, level: str, text: str) -> None:
        self._emit("log", level=level, text=text)

    def _notice(self, key: str, level: str, msg: str, **args) -> None:
        self._emit("notice", key=key, level=level, msg=msg, args=args)

    # ---- 認証まわり ----

    def _client_id(self) -> str:
        """設定が空なら配布用アプリ(App Testers に登録された人が使える)。"""
        return str(self.config.get("discord", {}).get("client_id") or oauth.DEFAULT_CLIENT_ID)

    def _authenticate(self, rpc: DiscordRPC) -> dict:
        """キャッシュ済みトークン → リフレッシュ → 再認可 の順に試す。"""
        client_id = self._client_id()
        uses_default_app = client_id == oauth.DEFAULT_CLIENT_ID
        token_path = self.config_dir / "token.json"

        token = oauth.load_cached_token(token_path)
        if token and oauth.is_expired(token) and token.get("refresh_token"):
            try:
                token = oauth.refresh_token(client_id, token["refresh_token"])
                oauth.save_token(token_path, token)
            except OSError:
                token = None

        if token and not oauth.is_expired(token):
            try:
                return rpc.authenticate(token["access_token"])
            except DiscordRPCError:
                self._log("info", t("log.token_invalid"))

        self._status("authorizing", t("status.authorizing.title"))
        verifier, challenge = oauth.make_pkce()
        try:
            code = rpc.authorize(oauth.SCOPES, code_challenge=challenge)
        except DiscordRPCTimeout as e:
            raise EngineError("auth", "err.auth_timeout") from e
        except DiscordRPCError as e:
            # Portal にリダイレクト URL が無いと Discord は
            # 「Missing "redirect_uri" in request」を返す
            if "redirect_uri" in str(e):
                raise EngineError("redirect", "err.redirect") from e
            # 配布用アプリは App Testers に登録された人しか認可できない
            if uses_default_app:
                raise EngineError("not_tester", "err.not_tester", detail=str(e)) from e
            raise EngineError("auth", "err.auth_failed", detail=str(e)) from e

        try:
            token = oauth.exchange_code(client_id, code, verifier)
        except urllib.error.HTTPError as e:
            # Public Client がオフのアプリは secret なしの交換を拒否する
            if e.code in (400, 401) and not uses_default_app:
                raise EngineError("auth", "err.not_public") from e
            raise EngineError("auth", "err.token_http", code=e.code) from e
        except OSError as e:
            raise EngineError("other", "err.offline", detail=str(e)) from e
        oauth.save_token(token_path, token)
        try:
            return rpc.authenticate(token["access_token"])
        except DiscordRPCError as e:
            raise EngineError("auth", "err.login_failed", detail=str(e)) from e

    def _check_attenuation(self, rpc: DiscordRPC) -> None:
        """アテニュエーションが ON だと測定値が汚染される(SPEC §4-1)。"""
        try:
            settings = rpc.get_voice_settings() or {}
        except DiscordRPCError as e:
            self._log("warning", t("log.voice_settings_failed", detail=e))
            return
        attenuation = settings.get("attenuation") or {}
        value = attenuation.get("attenuation")
        if value is None:
            self._log("info", t("log.attenuation_unknown"))
        elif value > 0:
            self._notice("attenuation", "warning", "notice.attenuation", value=value)

    # ---- キャプチャ ----

    def _start_capture(self) -> tuple[object, str]:
        """Discord プロセスのみのループバックを優先し、不可ならデバイス全体へ。"""
        from .capture.windows_process import (  # 遅延 import(OS 依存)
            ProcessCaptureError,
            ProcessLoopbackCapture,
            find_discord_pid,
        )

        try:
            capture = ProcessLoopbackCapture(find_discord_pid())
            capture.start()
            self._log("info", t("log.capture_process"))
            return capture, "process"
        except ProcessCaptureError as e:
            self._log("warning", t("log.capture_fallback", detail=e))
            self._notice("capture", "warning", "notice.capture")

        from .capture.windows import WasapiLoopbackCapture

        capture = WasapiLoopbackCapture()
        capture.start()
        return capture, "device"

    # ---- メインループ ----

    def _run(self) -> None:
        self._rpc = None
        self._capture = None
        self._frame_log = None
        try:
            self._main()
        except EngineError as e:
            self._emit("error", code=e.code, msg=e.msg, args=e.args_)
        except DiscordRPCError as e:
            self._emit(
                "error",
                code="disconnected",
                msg="err.disconnected_detail",
                args={"detail": str(e)},
            )
        except Exception as e:  # noqa: BLE001 - UI へ通知して終了する
            self._emit("error", code="other", msg="err.unexpected", args={"detail": repr(e)})
        finally:
            if self._capture is not None:
                try:
                    self._capture.stop()
                except Exception:  # noqa: BLE001
                    pass
            if self._rpc is not None:
                self._rpc.close()
            if self._frame_log is not None:
                self._frame_log.close()
            self._emit("stopped")

    def _main(self) -> None:
        params = self.config.get("params", {})
        est = RawLoudnessEstimator(
            EstimatorConfig(
                percentile=params.get("percentile", 87.5),
                window=params.get("window", 600),
                min_samples=params.get("min_samples", 50),
            )
        )
        ctl = VolumeController(
            ControllerConfig(
                target_db=params.get("target_db", -24.0),
                deadband_db=params.get("deadband_db", 1.5),
                max_step_db=params.get("max_step_db", 3.0),
            )
        )

        self._status("connecting", t("status.connecting.title"))
        rpc = self._rpc_factory(self._client_id())
        try:
            rpc.connect()
        except DiscordRPCError as e:
            raise EngineError("no_discord", "err.no_discord") from e
        self._rpc = rpc

        auth = self._authenticate(rpc)
        self_id = auth["user"]["id"]
        username = auth["user"].get("global_name") or auth["user"].get("username")
        self._emit("account", name=username)
        self._log("info", t("log.logged_in", name=username))

        self._check_attenuation(rpc)

        capture, mode = self._capture_factory()
        self._capture = capture
        meter = BlockLoudnessMeter(capture.samplerate)
        gate = SpeakingGate(self_id)

        if self.config.get("debug", {}).get("frame_log"):
            frame_log_path = self.config_dir / "frames.csv"
            self._frame_log = frame_log_path.open("a", encoding="utf-8")
            self._log("info", t("log.frame_log", path=frame_log_path))

        channel_id: str | None = None
        volumes: dict[str, int] = {}
        names: dict[str, str] = {}
        known_names: dict[str, str] = {}  # 抜けた人の名前もログに出せるように
        muted: set[str] = set()
        pinned: set[str] = set()
        last_error: dict[str, float] = {}

        # 診断カウンター(「採用 0」の原因切り分け用)
        diag_chunks = 0  # capture から届いた音声チャンク数
        diag_loud = 0  # 音がある(-50dB 超)ブロック数
        diag_speak = 0  # 受信した SPEAKING_START 数

        self._status("waiting", t("status.waiting.title"))
        last_poll = float("-inf")
        last_snapshot = time.monotonic()
        last_stats_log = time.monotonic()

        while not self._stop.is_set():
            # RPC イベントを反映
            while not rpc.events.empty():
                evt = rpc.events.get_nowait()
                name, data = evt.get("evt"), evt.get("data", {})
                if name == "_DISCONNECTED":
                    raise EngineError("disconnected", "err.disconnected")
                if channel_id is None:
                    continue
                if name == "SPEAKING_START":
                    diag_speak += 1
                    gate.on_start(data["user_id"])
                elif name == "SPEAKING_STOP":
                    gate.on_stop(data["user_id"])

            # 届いている音声をまとめて処理 → 単独発話ブロックだけ採用
            chunk = capture.read(timeout=0.05)
            n = 0
            while chunk is not None:
                diag_chunks += 1
                for block_db in meter.feed(chunk):
                    if block_db > _LOUD_BLOCK_DB:
                        diag_loud += 1
                    if channel_id is None:
                        continue
                    uid = gate.sole_speaker()
                    if self._frame_log is not None:
                        self._frame_log.write(
                            f"{time.time():.3f},{uid or ''},{block_db:.2f},"
                            f"{volumes.get(uid, '') if uid else ''}\n"
                        )
                    # 現在の volume% が分からない人は逆算できないので採用しない
                    if uid is not None and uid in volumes:
                        est.add_block(uid, block_db, volumes[uid])
                n += 1
                if n >= _MAX_CHUNKS_PER_TICK:
                    break
                chunk = capture.read(timeout=0)

            now = time.monotonic()

            # チャンネル状態の再取得 + 制御ループ
            if now - last_poll >= _POLL_INTERVAL_SEC:
                last_poll = now
                current = rpc.get_selected_voice_channel()
                current_id = current.get("id") if current else None

                if current_id != channel_id:
                    if channel_id is not None:
                        for evt_name in ("SPEAKING_START", "SPEAKING_STOP"):
                            try:
                                rpc.unsubscribe(evt_name, {"channel_id": channel_id})
                            except DiscordRPCError:
                                pass
                    gate.clear()
                    pinned.clear()
                    last_error.clear()
                    channel_id = current_id
                    if current_id is not None:
                        for evt_name in ("SPEAKING_START", "SPEAKING_STOP"):
                            rpc.subscribe(evt_name, {"channel_id": current_id})
                        channel_name = current.get("name") or "Voice"
                        self._status(
                            "monitoring",
                            t("status.monitoring.title_channel", channel=channel_name),
                            channel=channel_name,
                        )
                    else:
                        self._status("waiting", t("status.left"))

                volumes, names, muted, silenced = self._read_voice_states(current, self_id)
                known_names.update(names)
                # 「話している」ままの人を外す(抜けた・ミュートした / オープンマイク)
                for uid in gate.retain(set(volumes) - silenced):
                    self._log("info", t("log.speaking_reset", name=known_names.get(uid, uid)))
                for uid in gate.expire_stale(_STALE_SPEAKING_SEC):
                    self._log(
                        "warning",
                        t("log.open_mic", name=known_names.get(uid, uid),
                          sec=f"{_STALE_SPEAKING_SEC:.0f}"),
                    )
                if channel_id is not None:
                    self._control_step(
                        rpc, est, ctl, volumes, names, muted, pinned, last_error
                    )

            # UI 用スナップショット
            if now - last_snapshot >= _SNAPSHOT_INTERVAL_SEC:
                last_snapshot = now
                self._emit_users(est, gate, volumes, names, muted, pinned, last_error, ctl)
                self._emit(
                    "stats",
                    adopted=gate.adopted,
                    discarded=gate.discarded_overlap,
                    rate=gate.discard_rate(),
                    chunks=diag_chunks,
                    loud=diag_loud,
                    speak=diag_speak,
                    mode=mode,
                )

            # 破棄率 + 診断カウンター(SPEC §4-4)
            if channel_id is not None and now - last_stats_log >= _STATS_LOG_INTERVAL_SEC:
                last_stats_log = now
                self._log(
                    "info",
                    t(
                        "log.stats",
                        adopted=gate.adopted,
                        discarded=gate.discarded_overlap,
                        rate=f"{gate.discard_rate() * 100:.0f}",
                        chunks=diag_chunks,
                        loud=diag_loud,
                        speak=diag_speak,
                    ),
                )

    def _control_step(
        self, rpc, est, ctl, volumes, names, muted, pinned, last_error
    ) -> None:
        for uid in list(volumes):
            raw = est.estimate(uid)
            if raw is None or uid in muted:
                continue
            adj = ctl.update(uid, volumes[uid], raw)
            last_error[uid] = adj.error_db
            if adj.changed:
                rpc.set_user_volume(uid, adj.new_volume)
                self._log(
                    "info",
                    t(
                        "log.volume_changed",
                        name=names.get(uid, uid),
                        old=volumes[uid],
                        new=adj.new_volume,
                        diff=adj.error_db,
                    ),
                )
                volumes[uid] = adj.new_volume
            if adj.pinned_at_max and uid not in pinned:
                pinned.add(uid)
                self._log("warning", t("log.pinned", name=names.get(uid, uid)))
            elif not adj.pinned_at_max:
                pinned.discard(uid)

    @staticmethod
    def _read_voice_states(
        channel: dict | None, self_id: str
    ) -> tuple[dict[str, int], dict[str, str], set[str], set[str]]:
        """チャンネル内の他メンバーの状態を読む。

        戻り値: (volume%, 表示名, 自分がローカルミュートした人, 話せない人)
        「話せない人」は本人のミュート・スピーカーミュート・サーバーミュート中の人。
        """
        volumes: dict[str, int] = {}
        names: dict[str, str] = {}
        muted: set[str] = set()
        silenced: set[str] = set()
        if not channel:
            return volumes, names, muted, silenced
        for vs in channel.get("voice_states", []):
            user = vs.get("user", {})
            uid = user.get("id")
            if not uid or uid == self_id:
                continue
            volumes[uid] = round(vs.get("volume", 100))
            names[uid] = (
                vs.get("nick") or user.get("global_name") or user.get("username") or uid
            )
            if vs.get("mute"):  # 自分側のローカルミュート
                muted.add(uid)
            state = vs.get("voice_state") or {}
            if any(state.get(k) for k in ("self_mute", "mute", "self_deaf", "deaf", "suppress")):
                silenced.add(uid)
        return volumes, names, muted, silenced

    def _emit_users(
        self, est, gate, volumes, names, muted, pinned, last_error, ctl
    ) -> None:
        speaking = gate.speaking_ids()
        users = []
        for uid in volumes:
            users.append(
                {
                    "id": uid,
                    "name": names.get(uid, uid),
                    "volume": volumes[uid],
                    "raw_db": est.estimate(uid),
                    "samples": est.sample_count(uid),
                    "min_samples": est.config.min_samples,
                    "error_db": last_error.get(uid),
                    "deadband_db": ctl.config.deadband_db,
                    "speaking": uid in speaking,
                    "open_mic": uid in gate.open_mic,
                    "muted": uid in muted,
                    "pinned": uid in pinned,
                }
            )
        self._emit("users", users=users)
