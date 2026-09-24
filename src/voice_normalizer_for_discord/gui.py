"""GUI 版(tkinter)。exe に固めて配布する想定のエントリポイント。

- 初回起動: 3 ステップのセットアップ(Developer Portal の案内 + ID/Secret 入力)
- 以降: 起動すると自動で開始。状態・メンバーごとの音量をカードで表示
- Discord 未起動や切断時は自動で再接続する
- 表示言語は日本語 / 英語(既定は Windows の表示言語に合わせる)

設定は %APPDATA%\\VoiceNormalizerForDiscord\\config.toml に保存する。
"""

from __future__ import annotations

import platform
import queue
import sys
import time
import tkinter as tk
import webbrowser
from tkinter import ttk

from . import __version__
from .discord.oauth import REDIRECT_URI
from .engine import NormalizerEngine
from .i18n import set_language, t
from .settings import default_config, gui_config_dir, load_config, save_config

APP_NAME = "Voice Normalizer for Discord"
PORTAL_URL = "https://discord.com/developers/applications"

FONT = "Yu Gothic UI"

# Discord 風のダークテーマ
C = {
    "bg": "#1e1f22",
    "panel": "#2b2d31",
    "card": "#313338",
    "input": "#1e1f22",
    "border": "#3f4147",
    "btn": "#4e5058",
    "btn_hover": "#6d6f78",
    "text": "#f2f3f5",
    "muted": "#b5bac1",
    "faint": "#80848e",
    "accent": "#5865f2",
    "accent_hover": "#4752c4",
    "green": "#23a55a",
    "yellow": "#f0b232",
    "red": "#f23f43",
    "red_hover": "#da373c",
    "warn_bg": "#3a3120",
    "tip_bg": "#262a45",
}

_RETRY_SEC = 5
_RECOVERABLE = {"no_discord", "disconnected", "other"}

# state → (点の色, 見出しのキー, 説明のキー)
_STATUS_STYLE = {
    "stopped": ("faint", "status.stopped.title", "status.stopped.sub"),
    "connecting": ("accent", "status.connecting.title", None),
    "no_discord": ("yellow", "status.no_discord.title", "status.no_discord.sub"),
    "authorizing": ("yellow", "status.authorizing.title", "status.authorizing.sub"),
    "waiting": ("accent", "status.waiting.title", "status.waiting.sub"),
    "monitoring": ("green", "status.monitoring.title", "status.monitoring.sub"),
}

# 揃え方(percentile)の選択肢
_PERCENTILE_CHOICES = [
    (87.5, "settings.style.loud"),
    (70.0, "settings.style.balanced"),
    (50.0, "settings.style.quiet"),
]

_LANGUAGE_CHOICES = [
    ("auto", "settings.language.auto"),
    ("en", "settings.language.en"),
    ("ja", "settings.language.ja"),
]

_TARGET_DEFAULT = -24.0
_MAX_LOG_LINES = 500


class _Scale:
    """高 DPI 環境でピクセル寸法を拡大する。"""

    factor = 1.0


def px(value: float) -> int:
    return max(1, int(round(value * _Scale.factor)))


# ---- 小さな部品 ---------------------------------------------------------


class FlatButton(tk.Button):
    _KINDS = {
        "primary": ("accent", "accent_hover", "#ffffff"),
        "secondary": ("btn", "btn_hover", "text"),
        "danger": ("red", "red_hover", "#ffffff"),
    }

    def __init__(self, parent, text, command, kind="primary", size=10):
        super().__init__(
            parent,
            text=text,
            command=command,
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            font=(FONT, size, "bold"),
            padx=px(14),
            pady=px(5),
        )
        self.set_kind(kind)
        self.bind("<Enter>", lambda _e: self._hover(True))
        self.bind("<Leave>", lambda _e: self._hover(False))

    def set_kind(self, kind: str) -> None:
        bg, hover, fg = self._KINDS[kind]
        self._bg = C[bg]
        self._hv = C[hover]
        fg = C.get(fg, fg)
        self.configure(
            bg=self._bg,
            fg=fg,
            activebackground=self._hv,
            activeforeground=fg,
            disabledforeground=C["faint"],
        )

    def _hover(self, on: bool) -> None:
        if str(self["state"]) != "disabled":
            self.configure(bg=self._hv if on else self._bg)


class Dot(tk.Canvas):
    def __init__(self, parent, size, bg):
        s = px(size)
        super().__init__(parent, width=s, height=s, bg=bg, highlightthickness=0, bd=0)
        self._oval = self.create_oval(1, 1, s - 1, s - 1, fill=C["faint"], outline="")

    def set(self, color: str) -> None:
        self.itemconfigure(self._oval, fill=color)


class Bar(tk.Canvas):
    """横棒メーター。marker は目盛り線の位置(0〜1)。"""

    def __init__(self, parent, width, height, bg):
        w, h = px(width), px(height)
        super().__init__(parent, width=w, height=h, bg=bg, highlightthickness=0, bd=0)
        # 注意: self._w は tkinter がウィジェット名に使うので別名にする
        self._bar_w, self._bar_h = w, h
        self.create_rectangle(0, 0, w, h, fill=C["input"], outline="")
        self._fill = self.create_rectangle(0, 0, 0, h, fill=C["accent"], outline="")
        self._marker = None

    def set(self, frac: float, color: str, marker: float | None = None) -> None:
        frac = max(0.0, min(1.0, frac))
        self.coords(self._fill, 0, 0, int(self._bar_w * frac), self._bar_h)
        self.itemconfigure(self._fill, fill=color)
        if marker is not None:
            x = int(self._bar_w * marker)
            if self._marker is None:
                self._marker = self.create_line(x, 0, x, self._bar_h, fill=C["muted"])
            else:
                self.coords(self._marker, x, 0, x, self._bar_h)
            self.tag_raise(self._marker)


class ScrollArea(tk.Frame):
    """縦スクロールできる領域。中身が収まるときはスクロールバーを隠す。"""

    def __init__(self, parent, bg):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.pack(side="left", fill="both", expand=True)
        self._vsb_shown = False
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", self._on_wheel))
        self.canvas.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))

    def _on_inner(self, _e=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._update_vsb()

    def _on_canvas(self, e) -> None:
        self.canvas.itemconfigure(self._win, width=e.width)
        self._update_vsb()

    def _update_vsb(self) -> None:
        need = self.inner.winfo_reqheight() > self.canvas.winfo_height()
        if need and not self._vsb_shown:
            self.vsb.pack(side="right", fill="y")
            self._vsb_shown = True
        elif not need and self._vsb_shown:
            self.vsb.pack_forget()
            self._vsb_shown = False
            self.canvas.yview_moveto(0)

    def _on_wheel(self, e) -> None:
        if self._vsb_shown:
            self.canvas.yview_scroll(int(-e.delta / 120), "units")


def _label(parent, text="", size=10, color="text", bold=False, bg=None, **kw):
    return tk.Label(
        parent,
        text=text,
        font=(FONT, size, "bold" if bold else "normal"),
        fg=C[color],
        bg=bg or parent["bg"],
        anchor="w",
        justify="left",
        **kw,
    )


def _entry(parent, var, show=""):
    return tk.Entry(
        parent,
        textvariable=var,
        show=show,
        bg=C["input"],
        fg=C["text"],
        insertbackground=C["text"],
        relief="flat",
        highlightthickness=1,
        highlightbackground=C["border"],
        highlightcolor=C["accent"],
        font=(FONT, 10),
    )


def _check(parent, text, variable, command=None):
    bg = parent["bg"]
    return tk.Checkbutton(
        parent,
        text=text,
        variable=variable,
        command=command,
        bg=bg,
        fg=C["muted"],
        selectcolor=C["input"],
        activebackground=bg,
        activeforeground=C["text"],
        font=(FONT, 9),
        bd=0,
        highlightthickness=0,
    )


def _radio(parent, text, variable, value):
    bg = parent["bg"]
    return tk.Radiobutton(
        parent,
        text=text,
        variable=variable,
        value=value,
        bg=bg,
        fg=C["text"],
        selectcolor=C["input"],
        activebackground=bg,
        activeforeground=C["text"],
        font=(FONT, 10),
        anchor="w",
        justify="left",
        bd=0,
        highlightthickness=0,
    )


# ---- メンバーカード -----------------------------------------------------


class MemberCard:
    def __init__(self, parent):
        bg = C["card"]
        self.frame = tk.Frame(
            parent,
            bg=bg,
            padx=px(14),
            pady=px(10),
            highlightthickness=px(1.5),
            highlightbackground=bg,
            highlightcolor=bg,
        )
        self.dot = Dot(self.frame, 10, bg)
        self.name = _label(self.frame, size=11, bold=True)
        self.vol = tk.Label(
            self.frame, font=(FONT, 13, "bold"), fg=C["text"], bg=bg, anchor="e"
        )
        self.state = _label(self.frame, size=9, color="muted", wraplength=px(300))
        self.bar = Bar(self.frame, 120, 6, bg)
        self.detail = _label(self.frame, size=8, color="faint")

        self.dot.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, px(10)))
        self.name.grid(row=0, column=1, sticky="w")
        self.vol.grid(row=0, column=2, sticky="e")
        self.state.grid(row=1, column=1, sticky="w", pady=(px(2), 0))
        self.bar.grid(row=1, column=2, sticky="e", pady=(px(2), 0))
        self.detail.grid(row=2, column=1, columnspan=2, sticky="w", pady=(px(4), 0))
        self.frame.columnconfigure(1, weight=1)
        self.frame.pack(fill="x", pady=px(4))

    def update(self, u: dict, show_numbers: bool) -> None:
        err = u["error_db"]
        bar_color = C["accent"]
        if u["muted"]:
            text, color = t("card.muted"), "faint"
            bar_color = C["faint"]
        elif u["pinned"]:
            text = t("card.pinned")
            color, bar_color = "yellow", C["yellow"]
        elif u["samples"] < u["min_samples"]:
            pct = int(100 * u["samples"] / max(1, u["min_samples"]))
            text, color = t("card.learning", pct=pct), "muted"
            bar_color = C["faint"]
        elif err is None:
            text, color = t("card.ready"), "muted"
        elif abs(err) <= u["deadband_db"]:
            text, color = t("card.good"), "green"
            bar_color = C["green"]
        elif err > 0:
            text, color = t("card.raising"), "accent"
        else:
            text, color = t("card.lowering"), "accent"

        self.name.configure(text=u["name"])
        self.vol.configure(text=f"{u['volume']}%")
        self.state.configure(text=text, fg=C[color])
        self.bar.set(u["volume"] / 200.0, bar_color, marker=0.5)

        edge = C["green"] if u["speaking"] else C["card"]
        self.frame.configure(highlightbackground=edge, highlightcolor=edge)
        self.dot.set(C["green"] if u["speaking"] else C["faint"])

        if show_numbers:
            raw = f"{u['raw_db']:.1f} dB" if u["raw_db"] is not None else "–"
            diff = f"{err:+.1f} dB" if err is not None else "–"
            self.detail.configure(
                text=t("card.detail", raw=raw, diff=diff, samples=u["samples"])
            )
            self.detail.grid()
        else:
            self.detail.grid_remove()

    def destroy(self) -> None:
        self.frame.destroy()


# ---- アプリ本体 ---------------------------------------------------------


class NormalizerGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(APP_NAME)
        root.configure(bg=C["bg"])
        root.geometry(f"{px(560)}x{px(720)}")
        root.minsize(px(460), px(560))
        self._setup_style()

        self.config_dir = gui_config_dir()
        self.config_path = self.config_dir / "config.toml"
        try:
            self.config = load_config(self.config_path)
        except OSError:
            self.config = default_config()
        set_language(self.config.get("ui", {}).get("language", "auto"))

        self.engine: NormalizerEngine | None = None
        self._want_running = False
        self._restart_pending = False
        self._retry_id: str | None = None
        self._state = "stopped"
        self._channel: str | None = None
        self._account: str | None = None
        self._error_info: tuple | None = None  # (title_key, msg, args, retry, action)
        self._last_error_text = ""
        self._last_users: list[dict] = []
        self._last_stats: dict | None = None
        self._cards: dict[str, MemberCard] = {}
        self._notice_data: dict[str, tuple[str, str, dict]] = {}
        self._notices: dict[str, tk.Frame] = {}
        self._dismissed: set[str] = set()
        self._log_lines: list[tuple[str, str]] = []
        self._log_shown = False
        self._last_chunks = -1
        self._last_chunk_t = 0.0
        self._wrap_labels: list[tuple[tk.Label, int]] = []

        self.show_numbers = tk.BooleanVar(value=False)

        self.main = self._build_main()
        self.setup = self._build_setup()

        root.bind("<Configure>", self._on_resize)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        if self._has_credentials():
            self._show_main()
            self._start()
        else:
            self._show_setup()

        self._poll_events()

    def _setup_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        # 矢印なし・つまみだけの細いスクロールバー
        style.layout(
            "Vertical.TScrollbar",
            [(
                "Vertical.Scrollbar.trough",
                {
                    "sticky": "ns",
                    "children": [
                        ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})
                    ],
                },
            )],
        )
        style.configure(
            "Vertical.TScrollbar",
            gripcount=0,
            background=C["btn"],
            darkcolor=C["btn"],
            lightcolor=C["btn"],
            troughcolor=C["bg"],
            bordercolor=C["bg"],
            relief="flat",
            width=px(8),
        )
        style.map("Vertical.TScrollbar", background=[("active", C["btn_hover"])])

    # ==== 画面の組み立て ===================================================

    def _build_main(self) -> tk.Frame:
        main = tk.Frame(self.root, bg=C["bg"], padx=px(16), pady=px(14))

        # ヘッダー
        header = tk.Frame(main, bg=C["bg"])
        header.pack(fill="x")
        titles = tk.Frame(header, bg=C["bg"])
        titles.pack(side="left")
        _label(titles, APP_NAME, size=12, bold=True).pack(anchor="w")
        self.account_label = _label(titles, "", size=9, color="faint")
        self.account_label.pack(anchor="w")
        self.toggle_btn = FlatButton(header, t("button.start"), self._toggle)
        self.toggle_btn.pack(side="right")
        FlatButton(header, t("button.settings"), self._open_settings, kind="secondary").pack(
            side="right", padx=(0, px(8))
        )

        # 状態カード
        card = tk.Frame(main, bg=C["panel"], padx=px(18), pady=px(16))
        card.pack(fill="x", pady=(px(14), 0))
        row = tk.Frame(card, bg=C["panel"])
        row.pack(fill="x")
        self.status_dot = Dot(row, 14, C["panel"])
        self.status_dot.pack(side="left", padx=(0, px(10)))
        self.status_title = _label(row, "", size=14, bold=True)
        self.status_title.pack(side="left", fill="x", expand=True)
        self.status_sub = _label(card, "", size=10, color="muted")
        self.status_sub.pack(fill="x", pady=(px(6), 0))
        self._wrap_labels.append((self.status_sub, 72))
        self.status_action = FlatButton(
            card, t("button.review_setup"), self._show_setup, kind="secondary"
        )

        self.chips = tk.Frame(card, bg=C["panel"])
        self.chip_audio = self._chip(self.chips)
        self.chip_voice = self._chip(self.chips)
        self.chip_mode = self._chip(self.chips)

        # 注意の帯(減衰 ON など)
        self.notice_box = tk.Frame(main, bg=C["bg"])
        self.notice_box.pack(fill="x")

        # メンバー見出し
        mh = tk.Frame(main, bg=C["bg"])
        mh.pack(fill="x", pady=(px(16), px(4)))
        _label(mh, t("members.title"), size=11, bold=True).pack(side="left")
        _check(mh, t("members.show_numbers"), self.show_numbers, self._refresh_cards).pack(
            side="right"
        )
        self.stats_label = _label(mh, "", size=8, color="faint")
        self.stats_label.pack(side="right", padx=(0, px(10)))

        # 下部: 詳細ログ(折りたたみ)。メンバー欄より先に pack して下に固定する
        bottom = tk.Frame(main, bg=C["bg"])
        bottom.pack(side="bottom", fill="x", pady=(px(8), 0))
        log_row = tk.Frame(bottom, bg=C["bg"])
        log_row.pack(fill="x")
        self.log_toggle = _label(log_row, "", size=9, color="faint", cursor="hand2")
        self.log_toggle.pack(side="left")
        self.log_toggle.bind("<Button-1>", lambda _e: self._toggle_log())
        self.log_copy = _label(log_row, t("log.copy"), size=9, color="faint", cursor="hand2")
        self.log_copy.pack(side="right")
        self.log_copy.bind("<Button-1>", lambda _e: self._copy_log())
        self.log_text = tk.Text(
            bottom,
            height=8,
            bg=C["input"],
            fg=C["muted"],
            relief="flat",
            bd=0,
            font=(FONT, 9),
            wrap="word",
            state="disabled",
            padx=px(8),
            pady=px(6),
        )
        self.log_text.tag_configure("warning", foreground=C["yellow"])
        self.log_text.tag_configure("error", foreground=C["red"])
        self._render_log_toggle()

        # メンバー一覧
        self.members = ScrollArea(main, C["bg"])
        self.members.pack(fill="both", expand=True)
        self.empty_label = _label(
            self.members.inner, "", size=10, color="faint", pady=px(20)
        )
        self._update_empty()
        return main

    def _chip(self, parent) -> tk.Label:
        return tk.Label(
            parent,
            text="",
            font=(FONT, 9),
            bg=C["input"],
            fg=C["muted"],
            padx=px(8),
            pady=px(3),
        )

    def _build_setup(self) -> tk.Frame:
        outer = tk.Frame(self.root, bg=C["bg"])
        area = ScrollArea(outer, C["bg"])
        area.pack(fill="both", expand=True)
        f = tk.Frame(area.inner, bg=C["bg"], padx=px(20), pady=px(18))
        f.pack(fill="both", expand=True)

        _label(f, t("setup.title"), size=15, bold=True).pack(anchor="w")
        intro = _label(f, t("setup.intro"), size=10, color="muted")
        intro.pack(fill="x", pady=(px(6), px(10)))
        self._wrap_labels.append((intro, 60))

        body = self._step(f, 1, t("setup.step1.title"), t("setup.step1.desc"))
        FlatButton(
            body, t("setup.step1.button"), lambda: webbrowser.open(PORTAL_URL)
        ).pack(anchor="w")

        body = self._step(f, 2, t("setup.step2.title"), t("setup.step2.desc"))
        row = tk.Frame(body, bg=C["panel"])
        row.pack(fill="x")
        uri_var = tk.StringVar(value=REDIRECT_URI)
        uri = _entry(row, uri_var)
        uri.configure(state="readonly", readonlybackground=C["input"])
        uri.pack(side="left", fill="x", expand=True, ipady=px(4))
        self.copy_btn = FlatButton(
            row, t("setup.copy"), self._copy_redirect, kind="secondary", size=9
        )
        self.copy_btn.pack(side="left", padx=(px(8), 0))

        body = self._step(f, 3, t("setup.step3.title"), t("setup.step3.desc"))
        d = self.config.get("discord", {})
        self.client_id_var = tk.StringVar(value=str(d.get("client_id", "")))
        self.client_secret_var = tk.StringVar(value=str(d.get("client_secret", "")))
        self._paste_row(body, "Client ID", self.client_id_var)
        self._paste_row(body, "Client Secret", self.client_secret_var, secret=True)

        self.setup_error = _label(f, "", size=9, color="red")
        self.setup_error.pack(fill="x", pady=(px(10), 0))
        self._wrap_labels.append((self.setup_error, 60))

        buttons = tk.Frame(f, bg=C["bg"])
        buttons.pack(fill="x", pady=(px(10), 0))
        FlatButton(buttons, t("setup.save"), self._save_setup, size=11).pack(side="left")
        self.setup_back = FlatButton(
            buttons, t("setup.back"), self._show_main, kind="secondary"
        )

        note = _label(f, t("setup.note"), size=9, color="faint")
        note.pack(fill="x", pady=(px(14), 0))
        self._wrap_labels.append((note, 60))
        return outer

    def _step(self, parent, num: int, title: str, desc: str) -> tk.Frame:
        card = tk.Frame(parent, bg=C["panel"], padx=px(16), pady=px(14))
        card.pack(fill="x", pady=px(6))
        head = tk.Frame(card, bg=C["panel"])
        head.pack(fill="x")
        s = px(26)
        circle = tk.Canvas(head, width=s, height=s, bg=C["panel"], highlightthickness=0, bd=0)
        circle.create_oval(1, 1, s - 1, s - 1, fill=C["accent"], outline="")
        circle.create_text(s // 2, s // 2, text=str(num), fill="#ffffff", font=(FONT, 10, "bold"))
        circle.pack(side="left", padx=(0, px(10)))
        _label(head, title, size=11, bold=True).pack(side="left")
        d = _label(card, desc, size=9, color="muted")
        d.pack(fill="x", pady=(px(6), px(10)))
        self._wrap_labels.append((d, 100))
        body = tk.Frame(card, bg=C["panel"])
        body.pack(fill="x")
        return body

    def _paste_row(self, parent, caption, var, secret=False) -> tk.Entry:
        _label(parent, caption, size=9, color="muted").pack(anchor="w", pady=(px(4), px(2)))
        row = tk.Frame(parent, bg=C["panel"])
        row.pack(fill="x")
        entry = _entry(row, var, show="•" if secret else "")
        entry.pack(side="left", fill="x", expand=True, ipady=px(4))
        FlatButton(
            row, t("setup.paste"), lambda: self._paste_into(var), kind="secondary", size=9
        ).pack(side="left", padx=(px(8), 0))
        if secret:
            shown = tk.BooleanVar(value=False)
            _check(
                row,
                t("setup.show"),
                shown,
                lambda: entry.configure(show="" if shown.get() else "•"),
            ).pack(side="left", padx=(px(6), 0))
        return entry

    # ==== 言語の切り替え ====================================================

    def _apply_language(self) -> None:
        """画面を作り直して、今の状態を新しい言語で表示し直す。"""
        on_setup = self.setup.winfo_ismapped()
        self.main.destroy()
        self.setup.destroy()
        self._cards = {}
        self._notices = {}
        self._wrap_labels = []

        self.main = self._build_main()
        self.setup = self._build_setup()
        self._restore_log()
        if on_setup:
            self._show_setup()
        else:
            self._show_main()

        if self._account:
            self.account_label.configure(text=t("header.logged_in", name=self._account))
        if self._state == "error" and self._error_info is not None:
            self._render_error()
        else:
            self._set_state(self._state, channel=self._channel)
        for key in list(self._notice_data):
            self._render_notice(key)
        if self._last_stats is not None and self._state == "monitoring":
            self._update_stats(self._last_stats)
        self._refresh_cards()
        self._refresh_toggle()
        self.root.update_idletasks()
        self._apply_wrap(self.root.winfo_width())

    # ==== 画面切り替え ======================================================

    def _has_credentials(self) -> bool:
        d = self.config.get("discord", {})
        return bool(str(d.get("client_id", "")).strip()) and bool(
            str(d.get("client_secret", "")).strip()
        )

    def _show_main(self) -> None:
        self.setup.pack_forget()
        self.main.pack(fill="both", expand=True)

    def _show_setup(self) -> None:
        self.main.pack_forget()
        d = self.config.get("discord", {})
        self.client_id_var.set(str(d.get("client_id", "")))
        self.client_secret_var.set(str(d.get("client_secret", "")))
        self.setup_error.configure(text="")
        if self._has_credentials():
            self.setup_back.pack(side="left", padx=(px(8), 0))
        else:
            self.setup_back.pack_forget()
        self.setup.pack(fill="both", expand=True)

    def _copy_redirect(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(REDIRECT_URI)
        self.copy_btn.configure(text=t("setup.copied"))
        btn = self.copy_btn
        self.root.after(1500, lambda: btn.winfo_exists() and btn.configure(text=t("setup.copy")))

    def _paste_into(self, var: tk.StringVar) -> None:
        try:
            var.set(self.root.clipboard_get().strip())
        except tk.TclError:
            pass

    def _save_setup(self) -> None:
        client_id = self.client_id_var.get().strip()
        client_secret = self.client_secret_var.get().strip()
        if not client_id.isdigit() or len(client_id) < 15:
            self.setup_error.configure(text=t("setup.err_id"))
            return
        if len(client_secret) < 20:
            self.setup_error.configure(text=t("setup.err_secret"))
            return

        old_id = str(self.config.get("discord", {}).get("client_id", ""))
        self.config.setdefault("discord", {})
        self.config["discord"]["client_id"] = client_id
        self.config["discord"]["client_secret"] = client_secret
        save_config(self.config_path, self.config)
        if old_id != client_id:
            # 別アプリの ID に変わったので古いログイン情報は使えない
            (self.config_dir / "token.json").unlink(missing_ok=True)

        self._show_main()
        self._want_running = True
        self._restart_engine()

    # ==== 設定ダイアログ ====================================================

    def _open_settings(self) -> None:
        win = tk.Toplevel(self.root, bg=C["panel"])
        win.title(t("settings.title"))
        win.transient(self.root)
        win.resizable(False, False)
        win.grab_set()
        body = tk.Frame(win, bg=C["panel"], padx=px(22), pady=px(18))
        body.pack(fill="both", expand=True)
        params = self.config.get("params", {})

        # 目標の音量
        _label(body, t("settings.target.title"), size=11, bold=True).pack(anchor="w")
        _label(body, t("settings.target.desc"), size=9, color="muted").pack(
            anchor="w", pady=(px(2), px(6))
        )
        target = float(params.get("target_db", _TARGET_DEFAULT))
        target_var = tk.DoubleVar(value=round(target))
        value_label = _label(body, "", size=9, color="muted")

        def on_target(_v=None):
            v = round(target_var.get())
            if v == _TARGET_DEFAULT:
                value_label.configure(text=t("settings.target.value_default", v=v))
            else:
                value_label.configure(
                    text=t("settings.target.value", v=v, d=f"{_TARGET_DEFAULT:.0f}")
                )

        row = tk.Frame(body, bg=C["panel"])
        row.pack(fill="x")
        _label(row, t("settings.target.quieter"), size=9, color="faint").pack(side="left")
        tk.Scale(
            row,
            from_=min(-40, round(target)),
            to=max(-12, round(target)),
            resolution=1,
            orient="horizontal",
            variable=target_var,
            showvalue=0,
            length=px(300),
            width=px(10),
            sliderlength=px(22),
            command=on_target,
            bg=C["accent"],  # tk.Scale では bg がつまみの色になる
            fg=C["text"],
            troughcolor=C["input"],
            activebackground=C["accent"],
            highlightthickness=0,
            bd=0,
            sliderrelief="flat",
        ).pack(side="left", padx=px(8))
        _label(row, t("settings.target.louder"), size=9, color="faint").pack(side="left")
        value_label.pack(anchor="w", pady=(px(4), 0))
        on_target()

        # 揃え方
        _label(body, t("settings.style.title"), size=11, bold=True).pack(
            anchor="w", pady=(px(18), 0)
        )
        _label(body, t("settings.style.desc"), size=9, color="muted").pack(
            anchor="w", pady=(px(2), px(6))
        )
        current = float(params.get("percentile", 87.5))
        nearest = min(_PERCENTILE_CHOICES, key=lambda c: abs(c[0] - current))[0]
        pct_var = tk.DoubleVar(value=nearest)
        for value, key in _PERCENTILE_CHOICES:
            _radio(body, t(key), pct_var, value).pack(anchor="w", pady=px(1))

        # 言語
        _label(body, t("settings.language.title"), size=11, bold=True).pack(
            anchor="w", pady=(px(18), px(4))
        )
        lang_pref = self.config.get("ui", {}).get("language", "auto")
        lang_var = tk.StringVar(value=lang_pref)
        for value, key in _LANGUAGE_CHOICES:
            _radio(body, t(key), lang_var, value).pack(anchor="w", pady=px(1))

        # 減衰のヒント
        tip = tk.Frame(body, bg=C["tip_bg"], padx=px(12), pady=px(10))
        tip.pack(fill="x", pady=(px(18), 0))
        _label(tip, t("settings.tip"), size=9, color="muted", wraplength=px(380)).pack(
            anchor="w"
        )

        # ボタン
        buttons = tk.Frame(body, bg=C["panel"])
        buttons.pack(fill="x", pady=(px(18), 0))

        def redo_setup():
            win.destroy()
            self._show_setup()

        def save():
            new_target = float(round(target_var.get()))
            new_pct = float(pct_var.get())
            params_changed = (
                new_target != params.get("target_db", _TARGET_DEFAULT)
                or new_pct != params.get("percentile", 87.5)
            )
            self.config.setdefault("params", {})
            self.config["params"]["target_db"] = new_target
            self.config["params"]["percentile"] = new_pct
            self.config.setdefault("ui", {})["language"] = lang_var.get()
            save_config(self.config_path, self.config)
            win.destroy()
            if lang_var.get() != lang_pref:
                set_language(lang_var.get())
                self._apply_language()
            self._log("info", t("log.settings_saved"))
            if params_changed and self._want_running:
                self._restart_engine()

        FlatButton(buttons, t("settings.save"), save).pack(side="right")
        FlatButton(buttons, t("settings.cancel"), win.destroy, kind="secondary").pack(
            side="right", padx=(0, px(8))
        )
        FlatButton(buttons, t("settings.redo"), redo_setup, kind="secondary", size=9).pack(
            side="left"
        )

        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + px(40)
        win.geometry(f"+{max(0, x)}+{max(0, y)}")

    # ==== エンジン制御 ======================================================

    def _toggle(self) -> None:
        if self._want_running:
            self._stop()
        else:
            self._start()

    def _start(self) -> None:
        self._want_running = True
        self._cancel_retry()
        self._start_engine()

    def _stop(self) -> None:
        self._want_running = False
        self._cancel_retry()
        if self.engine is not None:
            self.engine.request_stop()
        self._set_state("stopped")
        self._refresh_toggle()

    def _start_engine(self) -> None:
        if self.engine is not None:
            return
        try:
            self.config = load_config(self.config_path)
        except OSError as e:
            self._set_error("error.title.config_load", "raw", {"text": str(e)}, action=True)
            self._want_running = False
            self._refresh_toggle()
            return
        self._last_chunks = -1
        self.engine = NormalizerEngine(self.config, self.config_dir)
        self.engine.start()
        self._set_state("connecting")
        self._refresh_toggle()

    def _restart_engine(self) -> None:
        self._cancel_retry()
        if self.engine is not None:
            self._restart_pending = True
            self.engine.request_stop()
        else:
            self._start_engine()

    def _schedule_retry(self) -> None:
        self._cancel_retry()
        self._retry_id = self.root.after(_RETRY_SEC * 1000, self._retry)

    def _cancel_retry(self) -> None:
        if self._retry_id is not None:
            self.root.after_cancel(self._retry_id)
            self._retry_id = None

    def _retry(self) -> None:
        self._retry_id = None
        if not self._want_running:
            return
        if self.engine is not None:  # 停止処理がまだ終わっていない
            self._schedule_retry()
            return
        self._start_engine()

    def _refresh_toggle(self) -> None:
        if self._want_running:
            self.toggle_btn.configure(text=t("button.stop"))
            self.toggle_btn.set_kind("secondary")
        else:
            self.toggle_btn.configure(text=t("button.start"))
            self.toggle_btn.set_kind("primary")

    def _on_close(self) -> None:
        self._cancel_retry()
        if self.engine is not None:
            self.engine.request_stop()
            self.root.after(800, self.root.destroy)
        else:
            self.root.destroy()

    # ==== イベント反映 ======================================================

    def _poll_events(self) -> None:
        engine = self.engine
        if engine is not None:
            for _ in range(200):
                try:
                    ev = engine.events.get_nowait()
                except queue.Empty:
                    break
                self._handle(ev)
        self.root.after(100, self._poll_events)

    def _handle(self, ev: dict) -> None:
        kind = ev["kind"]
        if kind == "status":
            # 停止ボタン後に届いた状態通知で「停止中」を上書きしない
            if self._want_running:
                self._set_state(ev["state"], channel=ev.get("channel"))
            self._log("info", ev["text"])
        elif kind == "account":
            self._account = ev["name"]
            self.account_label.configure(text=t("header.logged_in", name=ev["name"]))
        elif kind == "log":
            self._log(ev["level"], ev["text"])
        elif kind == "notice":
            self._set_notice(ev["key"], ev["level"], ev["msg"], ev["args"])
        elif kind == "users":
            self._last_users = ev["users"]
            self._refresh_cards()
        elif kind == "stats":
            self._last_stats = ev
            self._update_stats(ev)
        elif kind == "error":
            self._on_error(ev["code"], ev["msg"], ev["args"])
        elif kind == "stopped":
            self._on_stopped()

    def _on_error(self, code: str, msg: str, args: dict) -> None:
        text = t(msg, **args)
        if text != self._last_error_text:
            self._log("error", text)
            self._last_error_text = text
        if code in _RECOVERABLE and self._want_running:
            if code == "no_discord":
                self._set_state("no_discord")
            else:
                self._set_error("error.title.disconnected", msg, args, retry=True)
            self._schedule_retry()
        else:
            self._want_running = False
            if code in ("auth", "redirect"):
                self._set_error("error.title.check_setup", msg, args, action=True)
            else:
                self._set_error("error.title.generic", msg, args)
            self._refresh_toggle()

    def _on_stopped(self) -> None:
        self.engine = None
        self._last_users = []
        self._refresh_cards()
        self.chips.pack_forget()
        if self._restart_pending:
            self._restart_pending = False
            if self._want_running:
                self._start_engine()
                return
        if not self._want_running and self._state not in ("error",):
            self._set_state("stopped")
        self._refresh_toggle()

    # ==== 表示の更新 ========================================================

    def _set_state(self, state: str, channel: str | None = None) -> None:
        self._state = state
        self._channel = channel
        self._error_info = None
        color, title_key, sub_key = _STATUS_STYLE[state]
        title = t(title_key)
        sub = t(sub_key) if sub_key else ""
        if state == "monitoring":
            self._last_error_text = ""
            if channel:
                title = t("status.monitoring.title_channel", channel=channel)
        if state == "no_discord":
            sub += t("status.retry_suffix", sec=_RETRY_SEC)
        self.status_dot.set(C[color])
        self.status_title.configure(text=title, fg=C["text"])
        self.status_sub.configure(text=sub)
        self.status_action.pack_forget()
        if state == "monitoring":
            self.chips.pack(fill="x", pady=(px(12), 0))
        else:
            self.chips.pack_forget()
            self.stats_label.configure(text="")
        if state in ("waiting", "stopped", "no_discord"):
            self._last_users = []
            self._refresh_cards()
        self._update_empty()

    def _set_error(
        self, title_key: str, msg: str, args: dict, retry: bool = False, action: bool = False
    ) -> None:
        self._state = "error"
        self._error_info = (title_key, msg, args, retry, action)
        self._render_error()

    def _render_error(self) -> None:
        title_key, msg, args, retry, action = self._error_info
        text = t(msg, **args)
        if retry:
            text = t("error.retrying", text=text.rstrip("。."), sec=_RETRY_SEC)
        self.status_dot.set(C["red"])
        self.status_title.configure(text=t(title_key))
        self.status_sub.configure(text=text)
        self.chips.pack_forget()
        self.status_action.pack_forget()
        if action:
            self.status_action.pack(anchor="w", pady=(px(12), 0))
        self._update_empty()

    def _update_stats(self, ev: dict) -> None:
        now = time.monotonic()
        if ev["chunks"] != self._last_chunks:
            self._last_chunks = ev["chunks"]
            self._last_chunk_t = now
        audio_ok = now - self._last_chunk_t < 3.0

        if audio_ok:
            self.chip_audio.configure(text=t("chip.audio_ok"), fg=C["green"])
        else:
            self.chip_audio.configure(text=t("chip.audio_none"), fg=C["yellow"])
        if ev["speak"] > 0:
            self.chip_voice.configure(text=t("chip.voice_ok"), fg=C["green"])
        else:
            self.chip_voice.configure(text=t("chip.voice_none"), fg=C["faint"])
        if ev["mode"] == "process":
            self.chip_mode.configure(text=t("chip.mode_process"), fg=C["muted"])
        else:
            self.chip_mode.configure(text=t("chip.mode_device"), fg=C["yellow"])
        for chip in (self.chip_audio, self.chip_voice, self.chip_mode):
            if not chip.winfo_ismapped():
                chip.pack(side="left", padx=(0, px(6)))

        if self.show_numbers.get() and self._state == "monitoring":
            self.stats_label.configure(
                text=t("members.stats", adopted=ev["adopted"], discarded=ev["discarded"])
            )
        else:
            self.stats_label.configure(text="")

    def _refresh_cards(self) -> None:
        show = self.show_numbers.get()
        seen = set()
        for u in self._last_users:
            seen.add(u["id"])
            card = self._cards.get(u["id"])
            if card is None:
                card = MemberCard(self.members.inner)
                self._cards[u["id"]] = card
            card.update(u, show)
        for uid in list(self._cards):
            if uid not in seen:
                self._cards.pop(uid).destroy()
        if not show:
            self.stats_label.configure(text="")
        self._update_empty()

    def _update_empty(self) -> None:
        if self._cards:
            self.empty_label.pack_forget()
            return
        if self._state == "monitoring":
            text = t("members.empty_monitoring")
        elif self._state == "waiting":
            text = t("members.empty_waiting")
        else:
            text = ""
        # 中身が空の Frame は Tk が縮めないので、空でもラベルは置いておく
        self.empty_label.configure(text=text)
        self.empty_label.pack(fill="x")

    def _set_notice(self, key: str, level: str, msg: str, args: dict) -> None:
        if not msg:
            self._notice_data.pop(key, None)
        else:
            self._notice_data[key] = (level, msg, args)
        self._render_notice(key)

    def _render_notice(self, key: str) -> None:
        old = self._notices.pop(key, None)
        if old is not None:
            old.destroy()
        data = self._notice_data.get(key)
        if data is None or key in self._dismissed:
            return
        level, msg, args = data
        bg = C["warn_bg"] if level == "warning" else C["tip_bg"]
        edge = C["yellow"] if level == "warning" else C["accent"]
        frame = tk.Frame(self.notice_box, bg=bg)
        frame.pack(fill="x", pady=(px(10), 0))
        tk.Frame(frame, bg=edge, width=px(4)).pack(side="left", fill="y")
        close = _label(frame, "×", size=11, color="muted", cursor="hand2", padx=px(10))
        close.pack(side="right", anchor="n", pady=px(6))
        text = _label(frame, t(msg, **args), size=9, padx=px(10), pady=px(8))
        text.pack(side="left", fill="x", expand=True)
        text.configure(wraplength=max(px(200), self.root.winfo_width() - px(110)))

        def dismiss(_e=None):
            self._dismissed.add(key)
            self._notices.pop(key, None)
            frame.destroy()

        close.bind("<Button-1>", dismiss)
        self._notices[key] = frame

    def _toggle_log(self) -> None:
        self._log_shown = not self._log_shown
        self._render_log_toggle()

    def _render_log_toggle(self) -> None:
        if self._log_shown:
            self.log_text.pack(fill="x", pady=(px(4), 0))
            self.log_toggle.configure(text=t("log.hide"))
        else:
            self.log_text.pack_forget()
            self.log_toggle.configure(text=t("log.show"))

    def _copy_log(self) -> None:
        """不具合報告用に、バージョンと環境を付けてログをコピーする。"""
        header = (
            f"{APP_NAME} {__version__} / {platform.platform()}\n"
            f"{t('log.state_header', state=self.status_title.cget('text'))}\n\n"
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(header + self.log_text.get("1.0", "end-1c"))
        self.log_copy.configure(text=t("log.copied"), fg=C["green"])
        label = self.log_copy
        self.root.after(
            1500,
            lambda: label.winfo_exists() and label.configure(text=t("log.copy"), fg=C["faint"]),
        )

    def _log(self, level: str, text: str) -> None:
        line = f"{time.strftime('%H:%M:%S')}  {text}"
        self._log_lines.append((level, line))
        if len(self._log_lines) > _MAX_LOG_LINES:
            del self._log_lines[: len(self._log_lines) - _MAX_LOG_LINES]
            self._restore_log()
            return
        self._insert_log_line(level, line)
        self.log_text.see("end")

    def _insert_log_line(self, level: str, line: str) -> None:
        self.log_text.configure(state="normal")
        tag = level if level in ("warning", "error") else ()
        self.log_text.insert("end", line + "\n", tag)
        self.log_text.configure(state="disabled")

    def _restore_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        for level, line in self._log_lines:
            self._insert_log_line(level, line)
        self.log_text.see("end")

    def _on_resize(self, e) -> None:
        if e.widget is self.root:
            self._apply_wrap(e.width)

    def _apply_wrap(self, width: int) -> None:
        for label, margin in self._wrap_labels:
            if label.winfo_exists():
                label.configure(wraplength=max(px(200), width - px(margin)))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)  # 高 DPI でぼやけないように
    except (ImportError, AttributeError, OSError):
        pass
    root = tk.Tk()
    # 96 dpi のとき tk scaling は約 1.333(pt→px)。それに対する倍率で寸法を拡大する
    _Scale.factor = max(1.0, float(root.tk.call("tk", "scaling")) / (96 / 72))
    NormalizerGUI(root)
    if "--smoke" in argv:  # exe ビルドの起動確認用
        root.after(1500, root.destroy)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
