"""Study buddy: Claude, through the owner's own Claude Code login, as a friend to chat with.

Popper runs `claude -p` (Claude Code's one-shot mode) in the background, so it uses the Claude
subscription the owner is already signed in to; no API key. Claude Code reads nothing beyond its own
working folder. Each day is one Claude Code session, resumed for every message, so the chat remembers
the day.

A reply may end with [[interest: ...]] when the student shows curiosity about something; Popper strips the
tag and keeps the topic for the daily "something new".
"""

import ctypes
import datetime as dt
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk

import customtkinter as ctk  # rounded cards and buttons in the chat (TomSchimansky/CustomTkinter, MIT)

from i18n import t
from library import ACCENT, BG, FG, FG_DIM, GOOD, PANEL

CLAUDE_TIMEOUT = 180  # seconds
TAG_RE = re.compile(r"\[\[\s*(\w+)\s*:\s*(.*?)\s*\]\]")
# Markdown markers and emoji, which the plain Tk chat would show as-is or as broken glyphs
CLEAN_RE = re.compile("\\*\\*|__|`|[\U0001F000-\U0001FAFF☀-➿️]")
PERSONA = """You are Popper (泡泡), a warm, slightly fussy study buddy who lives in the corner of a university student's screen. Think of a caring friend who keeps them company while they study, cheers them on, notices how their day is going, and is genuinely curious with them. You don't quiz them or set exercises; they come to you to chat, to think out loud or to ask for help.

Style: short and friendly, plain text only: no Markdown (no **, #, bullets or backticks) and no emoji. The chat keeps your line breaks, so use short lines, never one long paragraph. Code, if any, goes on its own lines, each indented by four spaces. Encourage without flattering.

Language: anything about course content (explanations, answers to their study questions) is in English, the language of their courses, even when the student writes in another language. Casual chat (greetings, mood, plans) is in {language}.

When the student shows curiosity about something new, end your reply with [[interest: <topic, in English>]] on its own line (Popper reads and hides it)."""


# chat card colours, on the dark palette of library.py
CARD = "#2b3242"
ME_BUBBLE = "#2d4a70"
CODE_BG = "#1b2029"



def dark_title_bar(top):
    """Windows 10/11: a dark title bar to match the dark window (as py-window-styles does, CC0)."""
    try:
        top.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(top.winfo_id())
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
    except (AttributeError, OSError):
        pass


def find_claude():
    path = shutil.which("claude")
    if path:
        return path
    guess = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
    return guess if os.path.exists(guess) else None


def split_tags(text):
    """(visible text, {tag: value}) — tags are removed from what the student sees."""
    tags = {}
    for name, value in TAG_RE.findall(text or ""):
        tags[name.lower()] = value
    return CLEAN_RE.sub("", TAG_RE.sub("", text or "")).strip(), tags


class ClaudeBridge:
    """Runs one `claude -p` at a time in the background and hands results back on the Tk thread."""

    def __init__(self, app, workdir):
        self.app = app
        self.workdir = workdir
        os.makedirs(workdir, exist_ok=True)
        self.jobs = queue.Queue()
        self.busy = False
        threading.Thread(target=self._worker, daemon=True).start()

    def ask(self, prompt, session_id, on_done, system=None, timeout=CLAUDE_TIMEOUT):
        """on_done({"ok", "text", "session_id", "error"}) is called on the Tk thread. `system` replaces the persona."""
        self.jobs.put((prompt, session_id, on_done, system, timeout))

    def _worker(self):
        while True:
            prompt, session_id, on_done, system, timeout = self.jobs.get()
            self.busy = True
            result = self._run(prompt, session_id, system, timeout)
            self.busy = False
            self.app.ui_q.put(("call", lambda r=result, f=on_done: f(r)))

    def _run(self, prompt, session_id, system=None, timeout=CLAUDE_TIMEOUT):
        exe = find_claude()
        if not exe:
            return {"ok": False, "error": t("buddy_no_claude")}
        language = "Simplified Chinese" if self.app.settings["ui_lang"] == "zh" else "English"
        cmd = [exe, "-p", prompt, "--output-format", "json",
               "--tools", "Read,Glob,Grep", "--allowedTools", "Read", "Glob", "Grep",
               "--strict-mcp-config", "--permission-prompts", "none",
               "--system-prompt", system or PERSONA.format(language=language)]
        if session_id:
            cmd += ["--resume", session_id]
        try:
            proc = subprocess.run(cmd, cwd=self.workdir, capture_output=True, text=True, encoding="utf-8",
                                  timeout=timeout, stdin=subprocess.DEVNULL,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
            data = json.loads(proc.stdout or "{}")
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": t("buddy_timeout")}
        except (OSError, ValueError) as e:
            return {"ok": False, "error": f"{t('buddy_failed')} ({e.__class__.__name__})"}
        if data.get("is_error") or not data.get("result"):
            message = data.get("result") or proc.stderr.strip()[:200] or t("buddy_failed")
            if "authenticate" in message.lower() or "log in" in message.lower():
                message = t("buddy_login")
            return {"ok": False, "error": message, "session_id": data.get("session_id")}
        return {"ok": True, "text": data["result"], "session_id": data.get("session_id")}


class BuddyStore:
    """Everything said, one Claude session per day, and the topics the student likes."""

    def __init__(self, db):
        self.db = db
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS buddy_messages (
                id      INTEGER PRIMARY KEY,
                ts      REAL NOT NULL,
                day     TEXT NOT NULL,
                role    TEXT NOT NULL,      -- 'buddy' or 'me'
                kind    TEXT,               -- 'chat', 'morning', 'evening', 'discovery'
                text    TEXT NOT NULL
            )""")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS buddy_interests (
                topic TEXT PRIMARY KEY,
                score REAL NOT NULL,
                last  REAL NOT NULL
            )""")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS buddy_sessions (
                day        TEXT PRIMARY KEY,
                session_id TEXT NOT NULL
            )""")
        self.db.commit()

    def session(self, day):
        row = self.db.execute("SELECT session_id FROM buddy_sessions WHERE day=?", (day.isoformat(),)).fetchone()
        return row[0] if row else None

    def set_session(self, day, session_id):
        self.db.execute("INSERT INTO buddy_sessions (day, session_id) VALUES (?, ?) "
                        "ON CONFLICT(day) DO UPDATE SET session_id=excluded.session_id", (day.isoformat(), session_id))
        self.db.commit()

    def say(self, role, text, kind="chat"):
        self.db.execute("INSERT INTO buddy_messages (ts, day, role, kind, text) VALUES (?, ?, ?, ?, ?)",
                        (time.time(), dt.date.today().isoformat(), role, kind, text))
        self.db.commit()

    def messages(self, day):
        return self.db.execute("SELECT * FROM buddy_messages WHERE day=? ORDER BY ts", (day.isoformat(),)).fetchall()

    def interests(self, limit=6):
        return [r[0] for r in self.db.execute("SELECT topic FROM buddy_interests ORDER BY score DESC, last DESC "
                                              "LIMIT ?", (limit,))]

    def like(self, topic, amount=1.0):
        self.db.execute("INSERT INTO buddy_interests (topic, score, last) VALUES (?, ?, ?) "
                        "ON CONFLICT(topic) DO UPDATE SET score = score + excluded.score, last = excluded.last",
                        (topic.strip()[:80], amount, time.time()))
        self.db.commit()


# ---------------------------------------------------------------- windows

class ChatWindow:
    """A chat with the buddy, drawn as cards: Popper's replies in rounded cards (a line ending in "?" in bold,
    code in an inset block), the student's messages as bubbles on the right. The input sits below the
    transcript and never moves."""

    def __init__(self, app, feature):
        self.app, self.feature = app, feature
        top = self.top = tk.Toplevel(app.root)
        top.title(t("buddy_title"))
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        dark_title_bar(top)
        s, f = app.scale, app.font

        head = tk.Frame(top, bg=BG)
        head.pack(fill="x", padx=14, pady=(10, 6))
        tk.Label(head, text=t("buddy_title"), bg=BG, fg=FG, font=f("Microsoft YaHei UI", 14)).pack(side="left")
        self.status = tk.Label(head, bg=BG, fg=ACCENT, font=f("Microsoft YaHei UI", 9))
        self.status.pack(side="left", padx=10)
        for key, cmd in (("buddy_snooze", feature.snooze_today),):
            b = tk.Label(head, text=t(key), bg=PANEL, fg=ACCENT, padx=10, pady=2, cursor="hand2",
                         font=f("Microsoft YaHei UI", 9))
            b.pack(side="right", padx=(6, 0))
            b.bind("<Button-1>", lambda e, c=cmd: c())

        # input first, packed at the bottom, so the growing transcript never pushes it
        bottom = tk.Frame(top, bg=BG)
        bottom.pack(side="bottom", fill="x", padx=14, pady=(4, 12))
        self.input = tk.Text(bottom, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", height=3, width=1, wrap="word",
                             padx=int(8 * s), pady=int(6 * s), font=f("Microsoft YaHei UI", 11), highlightthickness=0)
        self.input.pack(side="left", fill="x", expand=True)
        self.input.bind("<Return>", self.send)
        self.input.bind("<Shift-Return>", lambda e: None)  # newline
        send = tk.Label(bottom, text=t("buddy_send"), bg=GOOD, fg=BG, padx=14, cursor="hand2",
                        font=f("Microsoft YaHei UI", 11))
        send.pack(side="left", fill="y", padx=(8, 0))
        send.bind("<Button-1>", self.send)

        body = tk.Frame(top, bg=BG)
        body.pack(fill="both", expand=True, padx=14)
        # the transcript is a read-only Text holding the cards as embedded windows, so it scrolls like a page
        self.view = tk.Text(body, bg=BG, relief="flat", wrap="word", cursor="arrow", width=1, height=1,
                            padx=int(4 * s), pady=int(6 * s), highlightthickness=0, state="disabled")
        scroll = ctk.CTkScrollbar(body, command=self.view.yview, fg_color=BG, button_color="#3a4358",
                                  button_hover_color="#4a5570")
        self.view.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.view.pack(side="left", fill="both", expand=True)
        self.view.tag_configure("right", justify="right")
        self.view.tag_configure("gap", font=f("Microsoft YaHei UI", 4))
        self.cards = []         # every card widget, so they can be resized and destroyed
        self.wraps = []         # (label, share of the card width) to re-wrap on resize
        self.thinking = None
        self.width_job = None
        self.view.bind("<Configure>", self.on_resize)

        top.bind("<Escape>", lambda e: top.destroy())
        top.geometry(f"{int(720 * s)}x{int(680 * s)}")
        top.update_idletasks()
        self.reload()
        self.set_busy(feature.bridge.busy or feature.waiting)
        top.lift()
        top.focus_force()
        self.input.focus_set()

    # ---------- layout helpers

    def cfont(self, size, weight="normal", family="Microsoft YaHei UI"):
        """A CustomTkinter font matching app.font(family, size): CTk sizes are pixels at 96 dpi, Tk's are points."""
        return ctk.CTkFont(family=family, size=round(self.app.font(family, size)[1] * 4 / 3), weight=weight)

    def card_width(self):
        """Usable width for a card, in CustomTkinter's unscaled pixels."""
        scaling = ctk.ScalingTracker.get_window_dpi_scaling(self.top) or 1
        return max(300, int((self.view.winfo_width() - 40 * self.app.scale) / scaling))

    def label(self, parent, text, size=11, weight="normal", color=FG, share=1.0, family="Microsoft YaHei UI",
              **pack):
        w = ctk.CTkLabel(parent, text=text, font=self.cfont(size, weight, family), text_color=color,
                         justify="left", anchor="w", wraplength=int(self.card_width() * share) - 40)
        w.pack(fill="x", **pack)
        self.wraps.append((w, share))
        return w

    def wheel(self, widget):
        """Let the mouse wheel scroll the chat while the pointer is over a card."""
        widget.bind("<MouseWheel>", lambda e: self.view.yview_scroll(-1 if e.delta > 0 else 1, "units") or "break",
                    add="+")
        for child in widget.winfo_children():
            self.wheel(child)

    def place(self, widget, right=False):
        v = self.view
        v.configure(state="normal")
        start = v.index("end-1c")
        v.window_create("end", window=widget, padx=int(4 * self.app.scale), pady=int(5 * self.app.scale))
        v.insert("end", "\n")
        if right:  # justify is a line property: tag the whole line, the embedded card included
            v.tag_add("right", start, "end-1c")
        v.configure(state="disabled")
        self.cards.append(widget)
        self.wheel(widget)

    def on_resize(self, _=None):
        if self.width_job:
            self.top.after_cancel(self.width_job)
        self.width_job = self.top.after(120, self.rewrap)

    def rewrap(self):
        self.width_job = None
        width = self.card_width()
        for w, share in self.wraps:
            if w.winfo_exists():
                w.configure(wraplength=int(width * share) - 40)
        for card in self.cards:
            if card.winfo_exists() and getattr(card, "full", False):
                card.configure(width=width)

    # ---------- messages

    def reload(self):
        for card in self.cards:
            card.destroy()
        self.cards, self.wraps, self.thinking = [], [], None
        v = self.view
        v.configure(state="normal")
        v.delete("1.0", "end")
        v.configure(state="disabled")
        rows = self.feature.store.messages(dt.date.today())
        if not rows:
            note = ctk.CTkFrame(self.view, fg_color="transparent")
            self.label(note, t("buddy_empty"), size=10, color=FG_DIM)
            self.place(note)
        for r in rows:
            self.add_line(r["role"], r["text"], scroll=False)
        self.view.see("end")
        self.view.xview_moveto(0)

    def add_line(self, role, text, scroll=True):
        if role == "buddy":
            card = self.buddy_card(text)
        else:
            card = self.my_bubble(text)
        if scroll:
            self.view.update_idletasks()
            self.view.see("end")
            self.view.see(self.view.index(card))  # a long reply is read from its start, not its end
            self.view.xview_moveto(0)  # see() may scroll sideways to a wide card; the chat never does

    def my_bubble(self, text):
        bubble = ctk.CTkFrame(self.view, fg_color=ME_BUBBLE, corner_radius=14)
        inner = ctk.CTkFrame(bubble, fg_color="transparent")
        inner.pack(padx=14, pady=8)
        self.label(inner, text.strip(), color="#e8f2ff", share=0.7)
        self.place(bubble, right=True)
        return bubble

    def buddy_card(self, text):
        """Lay out a reply as a card: text, code blocks, and a question in bold."""
        lines = [line for line in text.strip().splitlines()]
        card = ctk.CTkFrame(self.view, fg_color=CARD, corner_radius=16, width=self.card_width())
        card.full = True
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=14)
        code = []

        def flush_code():
            if code:
                block = ctk.CTkFrame(inner, fg_color=CODE_BG, corner_radius=10)
                block.pack(fill="x", pady=6)
                lab = ctk.CTkLabel(block, text="\n".join(code), font=self.cfont(10, family="Consolas"),
                                   text_color="#d8dee9", justify="left", anchor="w",
                                   wraplength=int(self.card_width() * 0.95) - 80)
                lab.pack(fill="x", padx=14, pady=10)
                self.wraps.append((lab, 0.95))
                code.clear()

        for line in lines:
            if line.startswith(("    ", "\t")):
                code.append(line[4:] if line.startswith("    ") else line.lstrip("\t"))
                continue
            flush_code()
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.endswith(("?", "？")):
                self.label(inner, stripped, size=12, weight="bold", pady=(6, 6))
            else:
                self.label(inner, stripped, size=11, color="#dfe5ef", pady=(2, 2))
        flush_code()
        self.place(card)
        return card

    # ---------- state

    def set_busy(self, busy):
        """While Claude works: a "thinking" card at the end of the chat."""
        if not self.top.winfo_exists():
            return
        self.status.configure(text=t("buddy_thinking") if busy else "")
        if self.thinking is not None:
            v = self.view
            v.configure(state="normal")
            try:
                v.delete(self.thinking, f"{self.thinking}+2c")
            except tk.TclError:
                pass
            v.configure(state="disabled")
            self.thinking_card.destroy()
            self.thinking = None
        if busy:
            card = self.thinking_card = ctk.CTkFrame(self.view, fg_color=CARD, corner_radius=16)
            label = ctk.CTkLabel(card, text=t("buddy_thinking_line"), font=self.cfont(10, "normal"),
                                 text_color=FG_DIM)
            label.pack(padx=18, pady=10)
            self.place(card)
            self.cards.remove(card)
            self.thinking = self.view.index(card)
            self.view.see("end")
            self.view.xview_moveto(0)
            self.animate(label, 0)

    def animate(self, label, n):
        """Three dots that come and go while Popper thinks."""
        if self.thinking is None or not label.winfo_exists():
            return
        label.configure(text=t("buddy_thinking_line").rstrip("….") + "." * (n % 3 + 1))
        self.top.after(450, lambda: self.animate(label, n + 1))

    def send(self, _=None):
        text = self.input.get("1.0", "end").strip()
        if text:
            self.input.delete("1.0", "end")
            self.feature.chat(text)
        return "break"  # keep Enter from adding a newline
