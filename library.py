"""Library check-in: check in when you arrive, check out when you leave, see your time and streak."""

import datetime as dt
import sqlite3
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from i18n import t

MAX_SESSION_HOURS = 8   # a session nobody checked out of is closed after this long
HEATMAP_WEEKS = 18

BG = "#1f2430"
PANEL = "#2a3040"
FG = "#f2f4f8"
FG_DIM = "#9aa3b5"
ACCENT = "#7cc4ff"
GOOD = "#46d07e"
# heatmap: no time, < 30 min, < 1 h, < 2 h, 2 h+
HEAT = ["#2a3040", "#1d4a3a", "#23744f", "#2fa364", "#46d07e"]


def fmt_duration(seconds):
    minutes = int(seconds // 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def fmt_long(seconds):
    minutes = int(seconds // 60)
    hours, minutes = divmod(minutes, 60)
    return t("lib_hm", h=hours, m=minutes) if hours else t("lib_m", m=minutes)


class LibraryLog:
    def __init__(self, db):
        """`db` is the word list's sqlite connection; sharing it avoids two writers locking each other."""
        self.db = db
        self.db.row_factory = sqlite3.Row
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS library_sessions (
                id          INTEGER PRIMARY KEY,
                start       REAL NOT NULL,
                end         REAL,
                auto_closed INTEGER DEFAULT 0
            )""")
        self.db.commit()

    def current(self):
        return self.db.execute("SELECT * FROM library_sessions WHERE end IS NULL "
                               "ORDER BY start DESC LIMIT 1").fetchone()

    def check_in(self):
        if not self.current():
            self.db.execute("INSERT INTO library_sessions (start) VALUES (?)", (time.time(),))
            self.db.commit()

    def check_out(self):
        """Close the open session; returns its length in seconds (or None)."""
        row = self.current()
        if not row:
            return None
        end = time.time()
        self.db.execute("UPDATE library_sessions SET end=? WHERE id=?", (end, row["id"]))
        self.db.commit()
        return end - row["start"]

    def close_stale(self):
        """Close a session left open for more than MAX_SESSION_HOURS. Returns True if it did."""
        row = self.current()
        if row and time.time() - row["start"] > MAX_SESSION_HOURS * 3600:
            self.db.execute("UPDATE library_sessions SET end=?, auto_closed=1 WHERE id=?",
                            (row["start"] + MAX_SESSION_HOURS * 3600, row["id"]))
            self.db.commit()
            return True
        return False

    def sessions(self, since=0):
        return self.db.execute("SELECT * FROM library_sessions WHERE COALESCE(end, ?) >= ? "
                               "ORDER BY start DESC", (time.time(), since)).fetchall()

    def daily_totals(self, since):
        """{date: seconds}, splitting sessions that run past midnight."""
        totals = {}
        now = time.time()
        for row in self.sessions(since):
            start, end = row["start"], row["end"] or now
            while start < end:
                day = dt.date.fromtimestamp(start)
                midnight = dt.datetime.combine(day + dt.timedelta(days=1), dt.time()).timestamp()
                piece_end = min(end, midnight)
                totals[day] = totals.get(day, 0) + piece_end - start
                start = piece_end
        return totals

    def streak(self, totals):
        """Consecutive days with library time, counting back from today (or yesterday)."""
        day = dt.date.today()
        if totals.get(day, 0) < 60:
            day -= dt.timedelta(days=1)
        n = 0
        while totals.get(day, 0) >= 60:
            n += 1
            day -= dt.timedelta(days=1)
        return n


def start_of_today():
    return dt.datetime.combine(dt.date.today(), dt.time()).timestamp()


class TodoList:
    """Today's to-dos: everything not done yet (unfinished ones carry over) plus what was done today."""

    def __init__(self, db):
        self.db = db
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS todos (
                id      INTEGER PRIMARY KEY,
                text    TEXT NOT NULL,
                done    INTEGER DEFAULT 0,
                created REAL,
                done_at REAL
            )""")
        self.db.commit()

    def today(self):
        return self.db.execute("SELECT * FROM todos WHERE done=0 OR done_at >= ? ORDER BY done, created",
                               (start_of_today(),)).fetchall()

    def progress(self):
        rows = self.today()
        return sum(r["done"] for r in rows), len(rows)

    def add(self, text):
        self.db.execute("INSERT INTO todos (text, created) VALUES (?, ?)", (text, time.time()))
        self.db.commit()

    def toggle(self, todo_id):
        self.db.execute("UPDATE todos SET done = 1 - done, done_at = CASE WHEN done = 0 THEN ? END WHERE id=?",
                        (time.time(), todo_id))
        self.db.commit()

    def delete(self, todo_id):
        self.db.execute("DELETE FROM todos WHERE id=?", (todo_id,))
        self.db.commit()

    def done_by_day(self, since):
        counts = {}
        for (done_at,) in self.db.execute("SELECT done_at FROM todos WHERE done=1 AND done_at >= ?", (since,)):
            day = dt.date.fromtimestamp(done_at)
            counts[day] = counts.get(day, 0) + 1
        return counts


class TodoWindow:
    """Today's to-do list, opened when you check in at the library."""

    def __init__(self, app):
        self.app = app
        top = self.top = tk.Toplevel(app.root)
        top.title(t("todo_title"))
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        s = app.scale
        self.wrap = int(330 * s)

        head = tk.Frame(top, bg=BG)
        head.pack(fill="x", padx=18, pady=(14, 4))
        tk.Label(head, text=t("todo_title"), bg=BG, fg=FG, font=app.font("Microsoft YaHei UI", 15)).pack(side="left")
        self.progress = tk.Label(head, bg=BG, fg=FG_DIM, font=app.font("Microsoft YaHei UI", 10))
        self.progress.pack(side="right")
        self.session = tk.Label(top, bg=BG, fg=ACCENT, font=app.font("Microsoft YaHei UI", 10), anchor="w")
        self.session.pack(fill="x", padx=18)

        self.entry = tk.Entry(top, bg=PANEL, fg=FG_DIM, insertbackground=FG, relief="flat",
                              font=app.font("Microsoft YaHei UI", 11))
        self.entry.pack(fill="x", padx=18, pady=(10, 8), ipady=int(6 * s))
        self.entry.insert(0, t("todo_hint"))
        self.entry.bind("<FocusIn>", self.clear_hint)
        self.entry.bind("<Return>", self.add)

        self.rows = tk.Frame(top, bg=BG)
        self.rows.pack(fill="both", expand=True, padx=12, pady=(0, 16))
        top.bind("<Escape>", lambda e: top.destroy())
        top.minsize(int(400 * s), int(260 * s))
        self.refresh()
        self.tick()
        top.lift()
        top.focus_force()
        self.entry.focus_set()

    def clear_hint(self, _=None):
        if self.entry.get() == t("todo_hint"):
            self.entry.delete(0, "end")
            self.entry.configure(fg=FG)

    def add(self, _=None):
        self.clear_hint()
        text = self.entry.get().strip()
        if text:
            self.app.todos.add(text)
            self.entry.delete(0, "end")
            self.refresh()

    def toggle(self, todo_id):
        self.app.todos.toggle(todo_id)
        self.refresh()

    def delete(self, todo_id):
        self.app.todos.delete(todo_id)
        self.refresh()

    def tick(self):
        if not self.top.winfo_exists():
            return
        row = self.app.library.current()
        self.session.configure(text=t("lib_in", time=fmt_duration(time.time() - row["start"])) if row else "")
        self.top.after(15000, self.tick)

    def refresh(self):
        for w in self.rows.winfo_children():
            w.destroy()
        rows = self.app.todos.today()
        done, total = self.app.todos.progress()
        self.progress.configure(text=t("todo_progress", done=done, total=total) if total else "")
        if not rows:
            tk.Label(self.rows, text=t("todo_empty"), bg=BG, fg=FG_DIM,
                     font=self.app.font("Microsoft YaHei UI", 10)).pack(anchor="w", padx=6, pady=8)
        for r in rows:
            line = tk.Frame(self.rows, bg=BG)
            line.pack(fill="x", pady=2)
            box = tk.Label(line, text="☑" if r["done"] else "☐", bg=BG, cursor="hand2",
                           fg=GOOD if r["done"] else FG_DIM, font=self.app.font("Segoe UI Symbol", 14))
            box.pack(side="left", padx=(6, 8))
            text_font = tkfont.Font(family="Microsoft YaHei UI", size=round(11 * self.app.zoom),
                                    overstrike=bool(r["done"]))
            text = tk.Label(line, text=r["text"], bg=BG, fg=FG_DIM if r["done"] else FG, cursor="hand2",
                            font=text_font, anchor="w", justify="left", wraplength=self.wrap)
            text.pack(side="left", fill="x", expand=True)
            text.font = text_font  # keep a reference so Tk doesn't drop it
            close = tk.Label(line, text="×", bg=BG, fg=FG_DIM, cursor="hand2", font=self.app.font("Segoe UI", 13))
            close.pack(side="right", padx=6)
            for w in (box, text):
                w.bind("<Button-1>", lambda e, i=r["id"]: self.toggle(i))
            close.bind("<Button-1>", lambda e, i=r["id"]: self.delete(i))


def new_words_by_day(vocab_db, since):
    rows = vocab_db.execute("SELECT added FROM words WHERE added >= ?", (since,))
    counts = {}
    for (added,) in rows:
        day = dt.date.fromtimestamp(added)
        counts[day] = counts.get(day, 0) + 1
    return counts


class LibraryWindow:
    """Check in/out, today / week / streak / total, a heatmap and the recent sessions."""

    def __init__(self, app):
        self.app = app
        top = self.top = tk.Toplevel(app.root)
        top.title(t("lib_title"))
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        s = app.scale
        self.s = s

        head = tk.Frame(top, bg=BG)
        head.pack(fill="x", padx=20, pady=(16, 6))
        self.state_lbl = tk.Label(head, bg=BG, fg=FG, font=app.font("Microsoft YaHei UI", 16), anchor="w")
        self.state_lbl.pack(side="left")
        self.toggle_btn = tk.Button(head, command=self.toggle, relief="flat", bd=0, padx=18, pady=6,
                                    fg=FG, activeforeground=FG, cursor="hand2",
                                    font=app.font("Microsoft YaHei UI", 11))
        self.toggle_btn.pack(side="right")

        tiles = tk.Frame(top, bg=BG)
        tiles.pack(fill="x", padx=14, pady=6)
        self.tiles = {}
        for key in ("lib_today", "lib_week", "lib_streak", "lib_total"):
            box = tk.Frame(tiles, bg=PANEL, padx=14, pady=10)
            box.pack(side="left", expand=True, fill="both", padx=6)
            value = tk.Label(box, bg=PANEL, fg=FG, font=app.font("Segoe UI Semibold", 16))
            value.pack(anchor="w")
            tk.Label(box, text=t(key), bg=PANEL, fg=FG_DIM, font=app.font("Microsoft YaHei UI", 9)).pack(anchor="w")
            self.tiles[key] = value

        self.cell = int(15 * s)
        gap = max(2, int(3 * s))
        self.pitch = self.cell + gap
        width = HEATMAP_WEEKS * self.pitch + int(40 * s)
        self.canvas = tk.Canvas(top, bg=BG, highlightthickness=0, width=width, height=7 * self.pitch + int(24 * s))
        self.canvas.pack(padx=20, pady=(10, 0))
        self.hover = tk.Label(top, bg=BG, fg=FG_DIM, font=app.font("Microsoft YaHei UI", 9))
        self.hover.pack(anchor="w", padx=20)

        cols = ("date", "in", "out", "length", "words", "tasks")
        self.tree = ttk.Treeview(top, columns=cols, show="headings", height=7)
        for col, key, w in [("date", "lib_col_date", 110), ("in", "lib_col_in", 60), ("out", "lib_col_out", 80),
                            ("length", "lib_col_length", 60), ("words", "lib_col_words", 70),
                            ("tasks", "lib_col_tasks", 70)]:
            self.tree.heading(col, text=t(key))
            self.tree.column(col, width=int(w * s), anchor="w")
        self.tree.pack(fill="both", expand=True, padx=20, pady=(8, 18))

        top.bind("<Escape>", lambda e: top.destroy())
        self.refresh()
        self.tick()
        top.lift()
        top.focus_force()

    def toggle(self):
        self.app.toggle_library()

    def tick(self):
        if not self.top.winfo_exists():
            return
        self.refresh_state()
        self.top.after(15000, self.tick)

    def refresh_state(self):
        row = self.app.library.current()
        if row:
            self.state_lbl.configure(text=t("lib_in", time=fmt_duration(time.time() - row["start"])))
            self.toggle_btn.configure(text=t("lib_check_out"), bg="#c4544f", activebackground="#c4544f")
        else:
            self.state_lbl.configure(text=t("lib_not_in"))
            self.toggle_btn.configure(text=t("lib_check_in"), bg="#3f9f6a", activebackground="#3f9f6a")

    def refresh(self):
        lib = self.app.library
        today = dt.date.today()
        first = today - dt.timedelta(days=today.weekday() + 7 * (HEATMAP_WEEKS - 1))
        since = dt.datetime.combine(first, dt.time()).timestamp()
        totals = lib.daily_totals(0)
        week_start = today - dt.timedelta(days=today.weekday())
        self.tiles["lib_today"].configure(text=fmt_duration(totals.get(today, 0)))
        self.tiles["lib_week"].configure(text=fmt_duration(sum(v for d, v in totals.items() if d >= week_start)))
        self.tiles["lib_streak"].configure(text=t("lib_days", n=lib.streak(totals)))
        self.tiles["lib_total"].configure(text=fmt_duration(sum(totals.values())))
        self.refresh_state()

        words = new_words_by_day(self.app.vocab.db, since)
        c, p, s = self.canvas, self.pitch, self.s
        c.delete("all")
        left, topy = int(30 * s), int(20 * s)
        for i, name in enumerate(t("lib_weekdays")):
            if i % 2 == 0:
                c.create_text(left - 6, topy + i * p + self.cell / 2, text=name, fill=FG_DIM, anchor="e",
                              font=self.app.font("Segoe UI", 8))
        last_month, last_label_week = None, -9
        for w in range(HEATMAP_WEEKS):
            for d in range(7):
                day = first + dt.timedelta(days=7 * w + d)
                if day > today:
                    continue
                if d == 0 and day.month != last_month:
                    last_month = day.month
                    if w - last_label_week >= 3:  # skip a label that would collide with the previous one
                        c.create_text(left + w * p, 4, text=t("lib_month", name=day.strftime("%b"), n=day.month),
                                      fill=FG_DIM, anchor="nw", font=self.app.font("Microsoft YaHei UI", 8))
                        last_label_week = w
                secs = totals.get(day, 0)
                level = 0 if secs < 60 else 1 if secs < 1800 else 2 if secs < 3600 else 3 if secs < 7200 else 4
                x, y = left + w * p, topy + d * p
                rect = c.create_rectangle(x, y, x + self.cell, y + self.cell, fill=HEAT[level], width=0)
                info = t("lib_hover", date=day.isoformat(), time=fmt_long(secs), words=words.get(day, 0))
                c.tag_bind(rect, "<Enter>", lambda e, s=info: self.hover.configure(text=s))

        tasks = self.app.todos.done_by_day(since)
        self.tree.delete(*self.tree.get_children())
        for row in lib.sessions()[:60]:
            start = dt.datetime.fromtimestamp(row["start"])
            if row["end"]:
                out = dt.datetime.fromtimestamp(row["end"]).strftime("%H:%M")
                if row["auto_closed"]:
                    out += " *"
                length = fmt_duration(row["end"] - row["start"])
            else:
                out, length = t("lib_ongoing"), fmt_duration(time.time() - row["start"])
            date = t("lib_date", wd=t("lib_weekdays")[start.weekday()], m=start.month, d=start.day)
            self.tree.insert("", "end", values=(date, start.strftime("%H:%M"), out, length,
                                                words.get(start.date(), ""), tasks.get(start.date(), "")))
