"""Study time: notices which window you're working in and whether you're actually at the computer.

Every few seconds it looks at the foreground window (program and title) and how long it's been since
the last key press or mouse move. Active seconds are added to a per-minute bucket under a *key*
naming what you were in: a program ("app:code.exe") or, in a browser, a site worked out from the tab
title ("web:YouTube", "web:YouTube · lectures"). Nothing leaves the computer, and titles themselves
aren't stored, only the key.

Whether a key counts as study is decided when you look, not when it's recorded: default rules below,
then your own choices (focus_rules table). Changing a choice re-counts the past too.
"""

import ctypes
import datetime as dt
import os
import re
import time
import tkinter as tk
from ctypes import wintypes

from i18n import t
from library import ACCENT, BG, FG, FG_DIM, GOOD, PANEL, fmt_duration

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

SAMPLE_MS = 5000
IDLE_LIMIT = 180          # seconds without keyboard/mouse before time stops counting
WATCH_IDLE_LIMIT = 20 * 60  # ...but watching a lecture is fine for longer
CATEGORIES = ("study", "other", "ignore")

BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "arc.exe", "vivaldi.exe"}
POPPER = {"python.exe", "pythonw.exe", "popper.exe"}

# Sites recognised from a tab title (lower-case keyword -> name)
KNOWN_SITES = {
    "brightspace": "Brightspace", "mycourses": "Brightspace", "d2l": "Brightspace", "canvas": "Canvas",
    "blackboard": "Blackboard", "gradescope": "Gradescope", "piazza": "Piazza", "google docs": "Google Docs",
    "google sheets": "Google Sheets", "google slides": "Google Slides", "google drive": "Google Drive",
    "overleaf": "Overleaf", "arxiv": "arXiv", "google scholar": "Google Scholar", "wikipedia": "Wikipedia",
    "stack overflow": "Stack Overflow", "leetcode": "LeetCode", "github": "GitHub", "chatgpt": "ChatGPT",
    "claude": "Claude", "coursera": "Coursera", "khan academy": "Khan Academy", "quizlet": "Quizlet",
    "notion": "Notion", "zoom": "Zoom", "youtube": "YouTube", "bilibili": "Bilibili", "哔哩哔哩": "Bilibili",
    "小红书": "小红书", "知乎": "知乎", "微博": "微博", "抖音": "抖音", "tiktok": "TikTok", "netflix": "Netflix",
    "twitch": "Twitch", "instagram": "Instagram", "reddit": "Reddit", "facebook": "Facebook",
    "x.com": "X", "/ x": "X", "amazon": "Amazon", "outlook": "Outlook", "gmail": "Gmail",
}
LECTURE_WORDS = re.compile(r"lecture|lec\b|tutorial|course|lesson|recitation|课|讲|教程|网课", re.I)

DEFAULT_RULES = {
    # programs
    **{f"app:{exe}": "study" for exe in (
        "code.exe", "acrord32.exe", "acrobat.exe", "sumatrapdf.exe", "foxitpdfreader.exe", "winword.exe",
        "excel.exe", "powerpnt.exe", "onenote.exe", "notion.exe", "obsidian.exe", "pycharm64.exe",
        "idea64.exe", "clion64.exe", "devenv.exe", "rstudio.exe", "matlab.exe", "windowsterminal.exe",
        "zotero.exe", "anki.exe", "mathematica.exe", "claude.exe", "cursor.exe", "unity.exe", "blender.exe",
        "chatgpt.exe", "chatgpt classic.exe")},
    **{f"app:{exe}": "other" for exe in (
        "wechat.exe", "weixin.exe", "qq.exe", "discord.exe", "steam.exe", "spotify.exe", "telegram.exe",
        "whatsapp.exe", "epicgameslauncher.exe", "neteasecloudmusic.exe", "cloudmusic.exe")},
    **{f"app:{exe}": "ignore" for exe in (
        "explorer.exe", "lockapp.exe", "searchhost.exe", "searchapp.exe", "startmenuexperiencehost.exe",
        "shellexperiencehost.exe", "taskmgr.exe", "systemsettings.exe", "textinputhost.exe",
        "snippingtool.exe", "screenclippinghost.exe")},
    "app:popper": "study",
    # sites
    **{f"web:{s}": "study" for s in (
        "Brightspace", "Canvas", "Blackboard", "Gradescope", "Piazza", "Google Docs", "Google Sheets",
        "Google Slides", "Google Drive", "Overleaf", "arXiv", "Google Scholar", "Wikipedia", "Stack Overflow",
        "LeetCode", "GitHub", "ChatGPT", "Claude", "Coursera", "Khan Academy", "Quizlet", "Notion", "Zoom",
        "YouTube · lectures", "Bilibili · lectures", "PDF")},
    **{f"web:{s}": "other" for s in (
        "YouTube", "Bilibili", "小红书", "知乎", "微博", "抖音", "TikTok", "Netflix", "Twitch", "Instagram",
        "Reddit", "Facebook", "X", "Amazon")},
}


# ---------------------------------------------------------------- what's on screen

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds():
    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    user32.GetLastInputInfo(ctypes.byref(info))
    return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000


def foreground():
    """(exe name, window title) of the window in front, or (None, '')."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None, ""
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    exe = None
    if handle:
        path = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            exe = os.path.basename(path.value).lower()
        kernel32.CloseHandle(handle)
    return exe, buf.value


def site_of(title):
    """Name of the site a browser tab title belongs to, e.g. 'Lecture 9 - YouTube - Google Chrome' -> 'YouTube'."""
    title = re.sub(r"[​-‏]", "", title)
    title = re.sub(r"\s+and \d+ more pages?", "", title)
    parts = [p.strip() for p in re.split(r"\s[-—–|]\s", title) if p.strip()]
    browser = re.compile(r"(google chrome|microsoft edge|mozilla firefox|brave|opera|arc|vivaldi)$", re.I)
    while parts and (browser.search(parts[-1]) or re.fullmatch(r"(personal|work|profile \d+|个人|工作)", parts[-1], re.I)):
        parts.pop()
    rest = " - ".join(parts)
    low = rest.lower()
    if low.endswith(".pdf") or " pdf" in low[-12:]:
        return "PDF"
    for word, name in KNOWN_SITES.items():
        if word in low:
            return name
    if len(parts) >= 2 and len(parts[-1]) <= 40:
        return parts[-1]
    return rest[:40] or "?"


def key_for(exe, title):
    """What to file the current moment under, or None to skip it entirely."""
    if not exe:
        return None
    if exe in POPPER:
        return "app:popper"
    if exe in BROWSERS:
        site = site_of(title)
        if site in ("YouTube", "Bilibili") and LECTURE_WORDS.search(title):
            site += " · lectures"
        return f"web:{site}"
    return f"app:{exe}"


APP_NAMES = {
    "code.exe": "VS Code", "acrord32.exe": "Adobe Acrobat", "acrobat.exe": "Adobe Acrobat",
    "sumatrapdf.exe": "SumatraPDF", "foxitpdfreader.exe": "Foxit PDF", "winword.exe": "Word", "excel.exe": "Excel",
    "powerpnt.exe": "PowerPoint", "onenote.exe": "OneNote", "notion.exe": "Notion", "obsidian.exe": "Obsidian",
    "pycharm64.exe": "PyCharm", "idea64.exe": "IntelliJ IDEA", "clion64.exe": "CLion", "devenv.exe": "Visual Studio",
    "rstudio.exe": "RStudio", "matlab.exe": "MATLAB", "windowsterminal.exe": "Terminal", "zotero.exe": "Zotero",
    "anki.exe": "Anki", "claude.exe": "Claude", "chatgpt.exe": "ChatGPT", "chatgpt classic.exe": "ChatGPT",
    "cursor.exe": "Cursor", "unity.exe": "Unity", "blender.exe": "Blender", "wechat.exe": "WeChat 微信",
    "weixin.exe": "WeChat 微信", "qq.exe": "QQ", "discord.exe": "Discord", "steam.exe": "Steam",
    "spotify.exe": "Spotify", "explorer.exe": "File Explorer", "neteasecloudmusic.exe": "网易云音乐",
    "cloudmusic.exe": "网易云音乐",
}


def label_of(key):
    kind, name = key.split(":", 1)
    if key == "app:popper":
        return "Popper"
    if kind == "app":
        return APP_NAMES.get(name) or (name[:-4] if name.endswith(".exe") else name)
    return name


# ---------------------------------------------------------------- storage

class FocusLog:
    def __init__(self, db):
        self.db = db
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS focus_activity (
                minute  INTEGER NOT NULL,   -- unix time // 60
                key     TEXT NOT NULL,
                seconds REAL NOT NULL,
                PRIMARY KEY (minute, key)
            )""")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS focus_rules (
                key      TEXT PRIMARY KEY,
                category TEXT NOT NULL
            )""")
        self.db.commit()
        self.pending = {}
        self.last_sample = None

    def sample(self):
        """Count the seconds since the last sample toward whatever is in front, if you're there."""
        now = time.time()
        elapsed = min(now - self.last_sample, SAMPLE_MS / 1000 * 2) if self.last_sample else 0
        self.last_sample = now
        exe, title = foreground()
        key = key_for(exe, title)
        if not key or not elapsed:
            return
        limit = WATCH_IDLE_LIMIT if key.endswith("· lectures") else IDLE_LIMIT
        if idle_seconds() > limit:
            return
        slot = (int(now // 60), key)
        self.pending[slot] = self.pending.get(slot, 0) + elapsed

    def flush(self):
        for (minute, key), seconds in self.pending.items():
            self.db.execute("INSERT INTO focus_activity (minute, key, seconds) VALUES (?, ?, ?) "
                            "ON CONFLICT(minute, key) DO UPDATE SET seconds = seconds + excluded.seconds",
                            (minute, key, seconds))
        self.pending = {}
        self.db.commit()

    # ---------- rules

    def rules(self):
        return dict(self.db.execute("SELECT key, category FROM focus_rules").fetchall())

    def category(self, key, rules=None):
        rules = self.rules() if rules is None else rules
        return rules.get(key) or DEFAULT_RULES.get(key) or "unsorted"

    def set_category(self, key, category):
        self.db.execute("INSERT INTO focus_rules (key, category) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET category=excluded.category", (key, category))
        self.db.commit()

    # ---------- totals

    def by_key(self, start, end):
        """{key: seconds} between two timestamps (unsaved seconds included)."""
        totals = {}
        for key, seconds in self.db.execute("SELECT key, SUM(seconds) FROM focus_activity "
                                            "WHERE minute >= ? AND minute < ? GROUP BY key",
                                            (int(start // 60), int(end // 60))):
            totals[key] = seconds
        for (minute, key), seconds in self.pending.items():
            if start // 60 <= minute < end // 60:
                totals[key] = totals.get(key, 0) + seconds
        return totals

    def split(self, totals):
        """(study seconds, other seconds) — 'other' includes things you haven't sorted yet."""
        rules = self.rules()
        study = other = 0
        for key, seconds in totals.items():
            cat = self.category(key, rules)
            if cat == "study":
                study += seconds
            elif cat != "ignore":
                other += seconds
        return study, other


def day_range(day):
    start = dt.datetime.combine(day, dt.time()).timestamp()
    return start, start + 86400


# ---------------------------------------------------------------- window

CHIP = {"study": ("#1f5a3f", GOOD), "other": ("#5a2d2b", "#e57373"), "ignore": (PANEL, FG_DIM),
        "unsorted": ("#4a4227", "#e0c46c")}


class FocusWindow:
    """Today / this week, the last seven days as bars, and everything you used, which you can re-sort."""

    def __init__(self, app, log):
        self.app, self.log = app, log
        top = self.top = tk.Toplevel(app.root)
        top.title(t("focus_title"))
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        s, f = app.scale, app.font

        tk.Label(top, text=t("focus_title"), bg=BG, fg=FG, font=f("Microsoft YaHei UI", 15)).pack(
            anchor="w", padx=18, pady=(14, 2))
        tk.Label(top, text=t("focus_how"), bg=BG, fg=FG_DIM, font=f("Microsoft YaHei UI", 9),
                 justify="left", wraplength=int(560 * s)).pack(anchor="w", padx=18)

        tiles = tk.Frame(top, bg=BG)
        tiles.pack(fill="x", padx=12, pady=(10, 4))
        self.tiles = {}
        for key in ("focus_today", "focus_today_other", "focus_week"):
            box = tk.Frame(tiles, bg=PANEL, padx=14, pady=10)
            box.pack(side="left", expand=True, fill="both", padx=6)
            value = tk.Label(box, bg=PANEL, fg=FG, font=f("Segoe UI Semibold", 16))
            value.pack(anchor="w")
            tk.Label(box, text=t(key), bg=PANEL, fg=FG_DIM, font=f("Microsoft YaHei UI", 9)).pack(anchor="w")
            self.tiles[key] = value

        self.chart = tk.Canvas(top, bg=BG, highlightthickness=0, height=int(120 * s), width=int(560 * s))
        self.chart.pack(fill="x", padx=18, pady=(8, 0))
        self.chart.bind("<Configure>", lambda e: self.draw_chart())

        head = tk.Frame(top, bg=BG)
        head.pack(fill="x", padx=18, pady=(12, 2))
        tk.Label(head, text=t("focus_list"), bg=BG, fg=FG_DIM, font=f("Microsoft YaHei UI", 10)).pack(side="left")
        tk.Label(head, text=t("focus_list_hint"), bg=BG, fg=FG_DIM, font=f("Microsoft YaHei UI", 8)).pack(side="right")
        self.rows = tk.Frame(top, bg=BG)
        self.rows.pack(fill="both", expand=True, padx=12, pady=(0, 16))

        top.bind("<Escape>", lambda e: top.destroy())
        self.refresh()
        top.lift()
        top.focus_force()

    def cycle(self, key, current):
        order = ["study", "other", "ignore"]
        nxt = order[(order.index(current) + 1) % 3] if current in order else "study"
        self.log.set_category(key, nxt)
        self.refresh()

    def refresh(self):
        log, s = self.log, self.app.scale
        today = dt.date.today()
        study, other = log.split(log.by_key(*day_range(today)))
        week_start = dt.datetime.combine(today - dt.timedelta(days=today.weekday()), dt.time()).timestamp()
        week_study, _ = log.split(log.by_key(week_start, day_range(today)[1]))
        self.tiles["focus_today"].configure(text=fmt_duration(study))
        self.tiles["focus_today_other"].configure(text=fmt_duration(other))
        self.tiles["focus_week"].configure(text=fmt_duration(week_study))

        self.draw_chart()

        # everything used in the last seven days, most time first
        for w in self.rows.winfo_children():
            w.destroy()
        start = day_range(today - dt.timedelta(days=6))[0]
        totals = sorted(log.by_key(start, day_range(today)[1]).items(), key=lambda kv: -kv[1])
        rules = log.rules()
        if not totals:
            tk.Label(self.rows, text=t("focus_empty"), bg=BG, fg=FG_DIM,
                     font=self.app.font("Microsoft YaHei UI", 10)).pack(anchor="w", padx=6, pady=6)
        for key, seconds in totals[:24]:
            if seconds < 30:
                continue
            cat = log.category(key, rules)
            line = tk.Frame(self.rows, bg=BG)
            line.pack(fill="x", pady=1)
            bg, fg = CHIP[cat]
            chip = tk.Label(line, text=t(f"focus_cat_{cat}"), bg=bg, fg=fg, width=9, cursor="hand2",
                            font=self.app.font("Microsoft YaHei UI", 9))
            chip.pack(side="left", padx=(6, 10), pady=2)
            chip.bind("<Button-1>", lambda e, k=key, c=cat: self.cycle(k, c))
            tk.Label(line, text=label_of(key), bg=BG, fg=FG if cat == "study" else FG_DIM, anchor="w",
                     font=self.app.font("Microsoft YaHei UI", 10)).pack(side="left", fill="x", expand=True)
            tk.Label(line, text=fmt_duration(seconds), bg=BG, fg=FG_DIM,
                     font=self.app.font("Segoe UI", 10)).pack(side="right", padx=6)
        self.top.geometry("")

    def draw_chart(self):
        """Last seven days of study time as bars, sized to the window."""
        log, s = self.log, self.app.scale
        today = dt.date.today()
        c = self.chart
        c.delete("all")
        width, height = max(c.winfo_width(), int(400 * s)), int(120 * s)
        days = [today - dt.timedelta(days=i) for i in range(6, -1, -1)]
        values = [log.split(log.by_key(*day_range(d)))[0] for d in days]
        top_value = max(values + [3600])
        slot = width / 7
        for i, (day, v) in enumerate(zip(days, values)):
            x = slot * i + slot * 0.25
            bar_h = (height - int(36 * s)) * v / top_value
            y = height - int(20 * s)
            c.create_rectangle(x, y - bar_h, x + slot * 0.5, y, fill=GOOD if day == today else "#2f7f57", width=0)
            if v >= 60:
                c.create_text(x + slot * 0.25, y - bar_h - 4, text=fmt_duration(v), fill=FG_DIM, anchor="s",
                              font=self.app.font("Segoe UI", 8))
            c.create_text(x + slot * 0.25, y + 4, text=t("lib_weekdays")[day.weekday()], fill=FG_DIM, anchor="n",
                          font=self.app.font("Microsoft YaHei UI", 8))
