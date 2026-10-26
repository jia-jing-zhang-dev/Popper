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
LATE = "#e57373"
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


def fmt_clock(seconds):
    """25:13, or 1:02:03 once past an hour."""
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def day_label(day):
    today = dt.date.today()
    if day == today:
        return t("date_today")
    if day == today + dt.timedelta(days=1):
        return t("date_tomorrow")
    return t("date_short", m=day.month, d=day.day, wd=t("lib_weekdays")[day.weekday()])


def countdown(deadline):
    days = (dt.date.fromisoformat(deadline) - dt.date.today()).days
    if days > 0:
        return t("goal_days_left", n=days)
    return t("goal_due_today") if days == 0 else t("goal_overdue", n=-days)


class TodoList:
    """Long-term goals, dated tasks with timers, and the archive of finished tasks.

    A task is planned for a day (today by default). Today's list holds unfinished tasks planned for
    today or earlier; later ones wait under "Coming up". Each task has a stopwatch (one runs at a
    time); ticking a task off stops it, and the task moves to the archive with the time it took.
    """

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
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id       INTEGER PRIMARY KEY,
                title    TEXT NOT NULL,
                deadline TEXT,
                done     INTEGER DEFAULT 0,
                created  REAL,
                done_at  REAL
            )""")
        columns = {r["name"] for r in self.db.execute("PRAGMA table_info(todos)")}
        for name, kind in (("goal_id", "INTEGER"), ("due", "TEXT"), ("spent", "REAL DEFAULT 0"),
                           ("started", "REAL")):
            if name not in columns:  # added after the first version of the to-do list
                self.db.execute(f"ALTER TABLE todos ADD COLUMN {name} {kind}")
        self.db.commit()

    _SELECT = ("SELECT todos.*, goals.title AS goal FROM todos "
               "LEFT JOIN goals ON goals.id = todos.goal_id ")

    # ---------- tasks

    def today(self):
        """Unfinished tasks planned for today or earlier (or never dated), oldest plan first."""
        return self.db.execute(self._SELECT + "WHERE todos.done=0 AND COALESCE(todos.due, '') <= ? "
                               "ORDER BY COALESCE(todos.due, ''), todos.created",
                               (dt.date.today().isoformat(),)).fetchall()

    def upcoming(self):
        return self.db.execute(self._SELECT + "WHERE todos.done=0 AND todos.due > ? ORDER BY todos.due, todos.created",
                               (dt.date.today().isoformat(),)).fetchall()

    def done_today(self):
        return self.db.execute("SELECT COUNT(*) FROM todos WHERE done=1 AND done_at >= ?",
                               (start_of_today(),)).fetchone()[0]

    def progress(self):
        """(finished today, today's total) — today's total counts what's left plus what's done."""
        done = self.done_today()
        return done, done + len(self.today())

    def add(self, text, goal_id=None, due=None):
        due = (due or dt.date.today()).isoformat()
        self.db.execute("INSERT INTO todos (text, created, goal_id, due, spent) VALUES (?, ?, ?, ?, 0)",
                        (text, time.time(), goal_id, due))
        self.db.commit()

    @staticmethod
    def elapsed(row):
        return (row["spent"] or 0) + (time.time() - row["started"] if row["started"] else 0)

    def running(self):
        return self.db.execute("SELECT * FROM todos WHERE started IS NOT NULL").fetchone()

    def start(self, todo_id):
        """Start this task's stopwatch, pausing whichever one was running."""
        for row in self.db.execute("SELECT id FROM todos WHERE started IS NOT NULL AND id != ?", (todo_id,)):
            self.pause(row["id"])
        self.db.execute("UPDATE todos SET started=? WHERE id=? AND started IS NULL", (time.time(), todo_id))
        self.db.commit()

    def pause(self, todo_id):
        self.db.execute("UPDATE todos SET spent = COALESCE(spent, 0) + (? - started), started = NULL "
                        "WHERE id=? AND started IS NOT NULL", (time.time(), todo_id))
        self.db.commit()

    def complete(self, todo_id):
        self.pause(todo_id)
        self.db.execute("UPDATE todos SET done=1, done_at=? WHERE id=?", (time.time(), todo_id))
        self.db.commit()

    def reopen(self, todo_id):
        """Undo a completion: back to today's list (the time already spent is kept)."""
        self.db.execute("UPDATE todos SET done=0, done_at=NULL, due=MIN(COALESCE(due, ?), ?) WHERE id=?",
                        (dt.date.today().isoformat(), dt.date.today().isoformat(), todo_id))
        self.db.commit()

    def delete(self, todo_id):
        self.db.execute("DELETE FROM todos WHERE id=?", (todo_id,))
        self.db.commit()

    def archive(self, days=60):
        """Finished tasks of the last `days` days: [(date, total seconds, [rows])], newest first."""
        since = start_of_today() - (days - 1) * 86400
        groups = {}
        for row in self.db.execute(self._SELECT + "WHERE todos.done=1 AND todos.done_at >= ? "
                                   "ORDER BY todos.done_at DESC", (since,)):
            groups.setdefault(dt.date.fromtimestamp(row["done_at"]), []).append(row)
        return [(day, sum(r["spent"] or 0 for r in rows), rows) for day, rows in groups.items()]

    def done_by_day(self, since):
        counts = {}
        for (done_at,) in self.db.execute("SELECT done_at FROM todos WHERE done=1 AND done_at >= ?", (since,)):
            day = dt.date.fromtimestamp(done_at)
            counts[day] = counts.get(day, 0) + 1
        return counts

    # ---------- goals

    def goals(self):
        """Open goals (nearest deadline first, then those without one) plus goals finished today."""
        return self.db.execute("""
            SELECT goals.*,
                   (SELECT COUNT(*) FROM todos WHERE todos.goal_id = goals.id AND todos.done = 1) AS tasks_done,
                   (SELECT COALESCE(SUM(spent), 0) FROM todos WHERE todos.goal_id = goals.id) AS time_spent
            FROM goals WHERE done=0 OR done_at >= ?
            ORDER BY done, deadline IS NULL, deadline, created""", (start_of_today(),)).fetchall()

    def open_goals(self):
        return [g for g in self.goals() if not g["done"]]

    def add_goal(self, title, deadline=None):
        self.db.execute("INSERT INTO goals (title, deadline, created) VALUES (?, ?, ?)",
                        (title, deadline.isoformat() if deadline else None, time.time()))
        self.db.commit()

    def toggle_goal(self, goal_id):
        self.db.execute("UPDATE goals SET done = 1 - done, done_at = CASE WHEN done = 0 THEN ? END WHERE id=?",
                        (time.time(), goal_id))
        self.db.commit()

    def delete_goal(self, goal_id):
        """Delete a goal; its tasks stay, just without a goal."""
        self.db.execute("UPDATE todos SET goal_id = NULL WHERE goal_id=?", (goal_id,))
        self.db.execute("DELETE FROM goals WHERE id=?", (goal_id,))
        self.db.commit()


class DatePicker:
    """A small month calendar under `anchor`; calls on_pick(date) or on_pick(None) for "no date"."""

    def __init__(self, app, anchor, on_pick, selected=None, allow_clear=True):
        self.app, self.on_pick = app, on_pick
        self.selected = selected
        self.month = (selected or dt.date.today()).replace(day=1)
        top = self.top = tk.Toplevel(anchor)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=PANEL, padx=10, pady=8)
        top.geometry(f"+{anchor.winfo_rootx()}+{anchor.winfo_rooty() + anchor.winfo_height() + 2}")

        bar = tk.Frame(top, bg=PANEL)
        bar.pack(fill="x")
        nav = dict(bg=PANEL, fg=FG, cursor="hand2", font=app.font("Segoe UI", 11))
        prev = tk.Label(bar, text="‹", **nav)
        prev.pack(side="left", padx=4)
        prev.bind("<Button-1>", lambda e: self.shift(-1))
        self.title = tk.Label(bar, bg=PANEL, fg=FG, font=app.font("Microsoft YaHei UI", 10))
        self.title.pack(side="left", expand=True)
        nxt = tk.Label(bar, text="›", **nav)
        nxt.pack(side="left", padx=4)
        nxt.bind("<Button-1>", lambda e: self.shift(1))
        self.grid = tk.Frame(top, bg=PANEL)
        self.grid.pack(pady=(6, 4))

        foot = tk.Frame(top, bg=PANEL)
        foot.pack(fill="x")
        for key, value in (("date_today", dt.date.today()), ("date_tomorrow", dt.date.today() + dt.timedelta(1))):
            link = tk.Label(foot, text=t(key), bg=PANEL, fg=ACCENT, cursor="hand2",
                            font=app.font("Microsoft YaHei UI", 9))
            link.pack(side="left", padx=(0, 10))
            link.bind("<Button-1>", lambda e, v=value: self.pick(v))
        if allow_clear:
            clear = tk.Label(foot, text=t("date_none"), bg=PANEL, fg=FG_DIM, cursor="hand2",
                             font=app.font("Microsoft YaHei UI", 9))
            clear.pack(side="right")
            clear.bind("<Button-1>", lambda e: self.pick(None))

        top.bind("<Escape>", lambda e: top.destroy())
        top.bind("<FocusOut>", lambda e: top.after(150, self.close_if_unfocused))
        self.draw()
        top.focus_force()

    def close_if_unfocused(self):
        """Close when focus went anywhere outside the calendar (another window or another app)."""
        if not self.top.winfo_exists():
            return
        focus = self.top.focus_get()
        if focus is None or not str(focus).startswith(str(self.top)):
            self.top.destroy()

    def shift(self, months):
        y, m = divmod(self.month.month - 1 + months, 12)
        self.month = dt.date(self.month.year + y, m + 1, 1)
        self.draw()

    def pick(self, day):
        self.top.destroy()
        self.on_pick(day)

    def draw(self):
        for w in self.grid.winfo_children():
            w.destroy()
        self.title.configure(text=t("date_month", y=self.month.year, m=self.month.month))
        for col, name in enumerate(t("lib_weekdays")):
            tk.Label(self.grid, text=name, bg=PANEL, fg=FG_DIM, width=3,
                     font=self.app.font("Microsoft YaHei UI", 8)).grid(row=0, column=col)
        today = dt.date.today()
        day = self.month - dt.timedelta(days=self.month.weekday())
        for row in range(1, 7):
            for col in range(7):
                in_month = day.month == self.month.month
                bg = ACCENT if day == self.selected else PANEL
                fg = BG if day == self.selected else (FG if in_month else "#5b6377")
                cell = tk.Label(self.grid, text=str(day.day), bg=bg, fg=fg, width=3, cursor="hand2",
                                font=self.app.font("Segoe UI Semibold" if day == today else "Segoe UI", 9))
                cell.grid(row=row, column=col, padx=1, pady=1)
                cell.bind("<Button-1>", lambda e, d=day: self.pick(d))
                day += dt.timedelta(days=1)


class TodoWindow:
    """Three columns: long-term goals | today (plus what's coming up) | archive of finished tasks.

    Each column has its input at the top and its list below, so nothing that changes ever moves an
    input box (on some machines a moved Entry was left drawn at its old position).
    """

    def __init__(self, app):
        self.app = app
        top = self.top = tk.Toplevel(app.root)
        top.title(t("todo_title"))
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        s = app.scale
        self.wrap = int(210 * s)
        self.deadline = None             # chosen deadline for the next goal
        self.task_day = dt.date.today()  # chosen day for the next task
        self.clock_labels = {}           # running task id -> its time label, ticked every second

        head = tk.Frame(top, bg=BG)
        head.pack(fill="x", padx=18, pady=(14, 0))
        tk.Label(head, text=t("todo_title"), bg=BG, fg=FG, font=app.font("Microsoft YaHei UI", 15)).pack(side="left")
        self.session = tk.Label(head, bg=BG, fg=ACCENT, font=app.font("Microsoft YaHei UI", 10))
        self.session.pack(side="right")

        columns = tk.Frame(top, bg=BG)
        columns.pack(fill="both", expand=True, padx=12, pady=(0, 16))
        columns.columnconfigure((0, 1, 2), weight=1, uniform="col")
        columns.rowconfigure(0, weight=1)
        cols = [tk.Frame(columns, bg=BG) for _ in range(3)]
        for i, col in enumerate(cols):
            col.grid(row=0, column=i, sticky="nsew", padx=8)
        left, middle, right = cols

        # long-term goals
        self.section(left, t("goal_section"))
        goal_bar = tk.Frame(left, bg=BG)
        goal_bar.pack(fill="x", pady=(4, 6))
        self.goal_entry = self.entry(goal_bar, t("goal_hint"), self.add_goal)
        self.goal_entry.pack(side="left", fill="x", expand=True, ipady=int(5 * s))
        self.deadline_btn = self.button(goal_bar, self.pick_deadline)
        self.deadline_btn.pack(side="left", padx=(6, 0), fill="y")
        self.goal_rows = tk.Frame(left, bg=BG)
        self.goal_rows.pack(fill="both", expand=True)

        # today
        self.progress = self.section(middle, t("todo_section"))
        task_bar = tk.Frame(middle, bg=BG)
        task_bar.pack(fill="x", pady=(4, 2))
        self.task_entry = self.entry(task_bar, t("todo_hint"), self.add_task)
        self.task_entry.pack(side="left", fill="x", expand=True, ipady=int(5 * s))
        self.day_btn = self.button(task_bar, self.pick_task_day)
        self.day_btn.pack(side="left", padx=(6, 0), fill="y")
        self.task_goal = None  # goal id for the next task
        self.goal_btn = self.button(middle, self.pick_goal)
        self.goal_btn.configure(anchor="w", pady=int(3 * s))
        self.goal_btn.pack(fill="x", pady=(0, 6))
        self.task_rows = tk.Frame(middle, bg=BG)
        self.task_rows.pack(fill="both", expand=True)

        # archive
        self.archive_total = self.section(right, t("archive_section"))
        box = tk.Frame(right, bg=PANEL)
        box.pack(fill="both", expand=True, pady=(4, 0))
        self.archive = tk.Text(box, bg=PANEL, fg=FG, relief="flat", wrap="none", cursor="arrow",
                               padx=int(10 * s), pady=int(8 * s), spacing1=int(3 * s), spacing3=int(3 * s),
                               font=app.font("Microsoft YaHei UI", 10), width=1, height=1,
                               highlightthickness=0, selectbackground=PANEL, inactiveselectbackground=PANEL)
        scroll = tk.Scrollbar(box, command=self.archive.yview)
        self.archive.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.archive.pack(side="left", fill="both", expand=True)
        self.archive.tag_configure("day", foreground=ACCENT, font=app.font("Microsoft YaHei UI Semibold", 10),
                                   spacing1=int(10 * s))
        self.archive.tag_configure("goal", foreground=FG_DIM, font=app.font("Microsoft YaHei UI", 9),
                                   spacing1=0)
        self.archive.tag_configure("time", foreground=FG_DIM)
        self.archive.tag_configure("empty", foreground=FG_DIM)
        self.archive.bind("<Configure>", lambda e: self.archive.configure(
            tabs=(max(e.width - int(24 * s), 100), "right")))
        tk.Label(right, text=t("archive_hint"), bg=BG, fg=FG_DIM,
                 font=app.font("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(4, 0))

        top.bind("<Escape>", lambda e: top.destroy())
        top.minsize(int(1050 * s), int(480 * s))
        self.refresh()
        self.tick()
        top.lift()
        top.focus_force()
        self.task_entry.focus_set()

    # ---------- building blocks

    def section(self, parent, title):
        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill="x", padx=6, pady=(14, 0))
        tk.Label(bar, text=title, bg=BG, fg=FG_DIM, font=self.app.font("Microsoft YaHei UI", 10)).pack(side="left")
        right = tk.Label(bar, bg=BG, fg=FG_DIM, font=self.app.font("Microsoft YaHei UI", 10))
        right.pack(side="right")
        return right

    def entry(self, parent, hint, on_enter):
        e = tk.Entry(parent, bg=PANEL, fg=FG_DIM, insertbackground=FG, relief="flat",
                     font=self.app.font("Microsoft YaHei UI", 11))
        e.hint = hint
        e.insert(0, hint)
        e.bind("<FocusIn>", lambda ev: self.clear_hint(e))
        e.bind("<FocusOut>", lambda ev: self.restore_hint(e))
        e.bind("<Return>", on_enter)
        return e

    def button(self, parent, command):
        b = tk.Label(parent, bg=PANEL, fg=ACCENT, cursor="hand2", padx=10,
                     font=self.app.font("Microsoft YaHei UI", 10))
        b.bind("<Button-1>", lambda e: command())
        return b

    @staticmethod
    def clear_hint(e):
        if e.get() == e.hint and e.cget("fg") == FG_DIM:
            e.delete(0, "end")
            e.configure(fg=FG)

    @staticmethod
    def restore_hint(e):
        if not e.get():
            e.configure(fg=FG_DIM)
            e.insert(0, e.hint)

    @staticmethod
    def value(e):
        return "" if e.cget("fg") == FG_DIM else e.get().strip()

    def small(self, parent, text, fg=FG_DIM, cursor="hand2", size=11):
        return tk.Label(parent, text=text, bg=BG, fg=fg, cursor=cursor, font=self.app.font("Segoe UI Symbol", size))

    def row(self, parent, done, text, note, on_toggle, on_delete, note_fg=ACCENT, timer=None):
        """One goal or task line. `timer` = (row, on_start, on_pause) adds a stopwatch."""
        line = tk.Frame(parent, bg=BG)
        line.pack(fill="x", pady=2)
        box = self.small(line, "☑" if done else "☐", fg=GOOD if done else FG_DIM, size=14)
        box.pack(side="left", padx=(4, 8))
        close = self.small(line, "×", size=12)
        close.pack(side="right", padx=4)
        body = tk.Frame(line, bg=BG)
        body.pack(side="left", fill="x", expand=True)
        text_font = tkfont.Font(family="Microsoft YaHei UI", size=round(11 * self.app.zoom), overstrike=bool(done))
        label = tk.Label(body, text=text, bg=BG, fg=FG_DIM if done else FG, cursor="hand2", font=text_font,
                         anchor="w", justify="left", wraplength=self.wrap)
        label.font = text_font  # keep a reference so Tk doesn't drop it
        label.pack(fill="x")
        meta = tk.Frame(body, bg=BG)
        meta.pack(fill="x")
        if note:
            tk.Label(meta, text=note, bg=BG, fg=note_fg, font=self.app.font("Microsoft YaHei UI", 9)).pack(side="left")
        if timer:
            task, on_start, on_pause = timer
            running = bool(task["started"])
            spent = TodoList.elapsed(task)
            clock = tk.Label(meta, text=fmt_clock(spent) if spent or running else "", bg=BG,
                             fg=GOOD if running else FG_DIM, font=self.app.font("Segoe UI", 9))
            clock.pack(side="left", padx=(8 if note else 0, 0))
            if running:
                self.clock_labels[task["id"]] = (clock, task)
            play = self.small(line, "⏸" if running else "▶", fg=GOOD if running else ACCENT, size=12)
            play.pack(side="right", padx=4)
            play.bind("<Button-1>", lambda e: on_pause() if running else on_start())
        for w in (box, label):
            w.bind("<Button-1>", lambda e: on_toggle())
        close.bind("<Button-1>", lambda e: on_delete())

    # ---------- actions

    def act(self, fn, *args):
        fn(*args)
        self.refresh()

    def pick_deadline(self):
        DatePicker(self.app, self.deadline_btn, self.set_deadline, self.deadline)

    def set_deadline(self, day):
        self.deadline = day
        self.refresh_buttons()
        self.goal_entry.focus_set()

    def pick_task_day(self):
        DatePicker(self.app, self.day_btn, self.set_task_day, self.task_day, allow_clear=False)

    def set_task_day(self, day):
        self.task_day = day or dt.date.today()
        self.refresh_buttons()
        self.task_entry.focus_set()

    def refresh_buttons(self):
        self.deadline_btn.configure(text=f"{day_label(self.deadline) if self.deadline else t('goal_deadline_hint')} ▾")
        self.day_btn.configure(text=f"{day_label(self.task_day)} ▾")
        titles = {g["id"]: g["title"] for g in self.app.todos.open_goals()}
        self.goal_btn.configure(text=f"{t('task_goal', goal=titles[self.task_goal]) if self.task_goal in titles else t('goal_none')} ▾")

    def add_goal(self, _=None):
        title = self.value(self.goal_entry)
        if not title:
            return
        self.app.todos.add_goal(title, self.deadline)
        self.goal_entry.delete(0, "end")
        self.deadline = None
        self.refresh()

    def add_task(self, _=None):
        text = self.value(self.task_entry)
        if not text:
            return
        self.app.todos.add(text, self.task_goal, self.task_day)
        self.task_entry.delete(0, "end")
        self.task_day = dt.date.today()
        self.refresh()

    def pick_goal(self):
        menu = tk.Menu(self.top, tearoff=0)
        for goal_id, title in [(None, t("goal_none"))] + [(g["id"], g["title"]) for g in self.app.todos.open_goals()]:
            menu.add_command(label=title, command=lambda i=goal_id: self.set_task_goal(i))
        menu.tk_popup(self.goal_btn.winfo_rootx(), self.goal_btn.winfo_rooty() + self.goal_btn.winfo_height())

    def set_task_goal(self, goal_id):
        self.task_goal = goal_id
        self.refresh_buttons()
        self.task_entry.focus_set()

    def tick(self):
        """Every second: advance the running stopwatch; every so often, the time in the library."""
        if not self.top.winfo_exists():
            return
        for clock, task in self.clock_labels.values():
            if clock.winfo_exists():
                clock.configure(text=fmt_clock(TodoList.elapsed(task)))
        row = self.app.library.current()
        self.session.configure(text=t("lib_in", time=fmt_duration(time.time() - row["start"])) if row else "")
        self.top.after(1000, self.tick)

    def refresh(self):
        todos = self.app.todos
        self.clock_labels = {}
        for frame in (self.goal_rows, self.task_rows):
            for w in frame.winfo_children():
                w.destroy()
        self.refresh_buttons()

        # goals
        goals = todos.goals()
        if not goals:
            tk.Label(self.goal_rows, text=t("goal_empty"), bg=BG, fg=FG_DIM,
                     font=self.app.font("Microsoft YaHei UI", 10)).pack(anchor="w", padx=6, pady=4)
        for g in goals:
            note = " · ".join(filter(None, [
                countdown(g["deadline"]) if g["deadline"] else "",
                t("goal_tasks_done", n=g["tasks_done"]) if g["tasks_done"] else "",
                t("goal_time", time=fmt_long(g["time_spent"])) if g["time_spent"] >= 60 else ""]))
            self.row(self.goal_rows, g["done"], g["title"], note,
                     lambda i=g["id"]: self.act(todos.toggle_goal, i), lambda i=g["id"]: self.act(todos.delete_goal, i))

        if self.task_goal not in {g["id"] for g in todos.open_goals()}:
            self.task_goal = None
            self.refresh_buttons()

        # today + coming up
        done, total = todos.progress()
        self.progress.configure(text=t("todo_progress", done=done, total=total) if total else "")
        today_rows = todos.today()
        if not today_rows:
            tk.Label(self.task_rows, text=t("todo_empty"), bg=BG, fg=FG_DIM,
                     font=self.app.font("Microsoft YaHei UI", 10)).pack(anchor="w", padx=6, pady=4)
        today = dt.date.today()
        for r in today_rows:
            late = (today - dt.date.fromisoformat(r["due"])).days if r["due"] else 0
            note = " · ".join(filter(None, [t("task_late", n=late) if late > 0 else "", r["goal"] or ""]))
            self.row(self.task_rows, False, r["text"], note,
                     lambda i=r["id"]: self.act(todos.complete, i), lambda i=r["id"]: self.act(todos.delete, i),
                     note_fg=LATE if late > 0 else ACCENT,
                     timer=(r, lambda i=r["id"]: self.act(todos.start, i), lambda i=r["id"]: self.act(todos.pause, i)))
        later = todos.upcoming()
        if later:
            tk.Label(self.task_rows, text=t("upcoming_section"), bg=BG, fg=FG_DIM,
                     font=self.app.font("Microsoft YaHei UI", 10)).pack(anchor="w", padx=6, pady=(12, 2))
            for r in later:
                note = " · ".join(filter(None, [day_label(dt.date.fromisoformat(r["due"])), r["goal"] or ""]))
                self.row(self.task_rows, False, r["text"], note,
                         lambda i=r["id"]: self.act(todos.complete, i), lambda i=r["id"]: self.act(todos.delete, i),
                         note_fg=FG_DIM,
                         timer=(r, lambda i=r["id"]: self.act(todos.start, i), lambda i=r["id"]: self.act(todos.pause, i)))

        # archive
        arc = self.archive
        arc.configure(state="normal")
        arc.delete("1.0", "end")
        groups = todos.archive()
        self.archive_total.configure(text=t("archive_total", n=sum(len(rows) for _, _, rows in groups)) if groups else "")
        if not groups:
            arc.insert("end", t("archive_empty"), "empty")
        for day, seconds, rows in groups:
            arc.insert("end", f"{day_label(day)} · {t('archive_count', n=len(rows))}", "day")
            arc.insert("end", f"\t{fmt_duration(seconds)}\n" if seconds else "\n", ("day", "time"))
            for r in rows:
                tag = f"task-{r['id']}"
                text = r["text"] if len(r["text"]) <= 22 else r["text"][:21] + "…"
                arc.insert("end", f"✓ {text}", tag)
                arc.insert("end", f"\t{fmt_clock(r['spent']) if r['spent'] else '—'}\n", (tag, "time"))
                if r["goal"]:  # on its own line so a long goal never pushes the time out of view
                    arc.insert("end", f"    {r['goal']}\n", (tag, "goal"))
                arc.tag_bind(tag, "<Double-1>", lambda e, i=r["id"]: self.act(todos.reopen, i))
                arc.tag_bind(tag, "<Enter>", lambda e: arc.configure(cursor="hand2"))
                arc.tag_bind(tag, "<Leave>", lambda e: arc.configure(cursor="arrow"))
        arc.configure(state="disabled")

        self.top.geometry("")  # grow or shrink with the lists


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
