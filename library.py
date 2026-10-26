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


def parse_deadline(text, today=None):
    """'2026-12-20', '12-20' or '12/20' (the next one coming) -> date; '' -> None; ValueError if unreadable."""
    text = text.strip().replace("/", "-").replace(".", "-")
    if not text:
        return None
    today = today or dt.date.today()
    parts = [int(p) for p in text.split("-")]
    if len(parts) == 3:
        return dt.date(*parts)
    if len(parts) == 2:
        day = dt.date(today.year, *parts)
        return day if day >= today else dt.date(today.year + 1, *parts)
    raise ValueError(text)


def countdown(deadline):
    days = (dt.date.fromisoformat(deadline) - dt.date.today()).days
    if days > 0:
        return t("goal_days_left", n=days)
    return t("goal_due_today") if days == 0 else t("goal_overdue", n=-days)


class TodoList:
    """Long-term goals and today's to-dos.

    Today's list is everything not done yet (unfinished tasks carry over) plus what was done today.
    A task can belong to a goal; a goal's progress is the number of its tasks done.
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
        if "goal_id" not in {r["name"] for r in self.db.execute("PRAGMA table_info(todos)")}:
            self.db.execute("ALTER TABLE todos ADD COLUMN goal_id INTEGER")
        self.db.commit()

    # ---------- to-dos

    def today(self):
        return self.db.execute("""
            SELECT todos.*, goals.title AS goal FROM todos LEFT JOIN goals ON goals.id = todos.goal_id
            WHERE todos.done=0 OR todos.done_at >= ? ORDER BY todos.done, todos.created""",
                               (start_of_today(),)).fetchall()

    def progress(self):
        rows = self.today()
        return sum(r["done"] for r in rows), len(rows)

    def add(self, text, goal_id=None):
        self.db.execute("INSERT INTO todos (text, created, goal_id) VALUES (?, ?, ?)", (text, time.time(), goal_id))
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

    # ---------- goals

    def goals(self):
        """Open goals (nearest deadline first, then those without one) plus goals finished today."""
        return self.db.execute("""
            SELECT goals.*, (SELECT COUNT(*) FROM todos WHERE todos.goal_id = goals.id AND todos.done = 1)
                   AS tasks_done
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


class TodoWindow:
    """Long-term goals on top, today's to-dos below. Opens when you check in at the library."""

    def __init__(self, app):
        self.app = app
        top = self.top = tk.Toplevel(app.root)
        top.title(t("todo_title"))
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        s = app.scale
        self.wrap = int(300 * s)

        head = tk.Frame(top, bg=BG)
        head.pack(fill="x", padx=18, pady=(14, 0))
        tk.Label(head, text=t("todo_title"), bg=BG, fg=FG, font=app.font("Microsoft YaHei UI", 15)).pack(side="left")
        self.session = tk.Label(head, bg=BG, fg=ACCENT, font=app.font("Microsoft YaHei UI", 10))
        self.session.pack(side="right")

        # long-term goals
        self.section(top, t("goal_section"))
        goal_bar = tk.Frame(top, bg=BG)
        goal_bar.pack(fill="x", padx=18, pady=(4, 4))
        self.goal_entry = self.entry(goal_bar, t("goal_hint"), self.add_goal)
        self.goal_entry.pack(side="left", fill="x", expand=True, ipady=int(5 * s))
        self.deadline_entry = self.entry(goal_bar, t("goal_deadline_hint"), self.add_goal, width=12)
        self.deadline_entry.pack(side="left", padx=(6, 0), ipady=int(5 * s))
        self.goal_rows = tk.Frame(top, bg=BG)
        self.goal_rows.pack(fill="x", padx=12)

        # today's to-dos
        self.progress = self.section(top, t("todo_section"))
        task_bar = tk.Frame(top, bg=BG)
        task_bar.pack(fill="x", padx=18, pady=(4, 4))
        self.task_entry = self.entry(task_bar, t("todo_hint"), self.add_task)
        self.task_entry.pack(side="left", fill="x", expand=True, ipady=int(5 * s))
        self.goal_var = tk.StringVar()
        self.goal_box = ttk.Combobox(task_bar, textvariable=self.goal_var, state="readonly", width=14,
                                     font=app.font("Microsoft YaHei UI", 10))
        self.goal_box.pack(side="left", padx=(6, 0))
        self.task_rows = tk.Frame(top, bg=BG)
        self.task_rows.pack(fill="both", expand=True, padx=12, pady=(0, 16))

        top.bind("<Escape>", lambda e: top.destroy())
        top.minsize(int(460 * s), int(380 * s))
        self.refresh()
        self.tick()
        top.lift()
        top.focus_force()
        self.task_entry.focus_set()

    # ---------- building blocks

    def section(self, parent, title):
        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill="x", padx=18, pady=(14, 0))
        tk.Label(bar, text=title, bg=BG, fg=FG_DIM, font=self.app.font("Microsoft YaHei UI", 10)).pack(side="left")
        right = tk.Label(bar, bg=BG, fg=FG_DIM, font=self.app.font("Microsoft YaHei UI", 10))
        right.pack(side="right")
        return right

    def entry(self, parent, hint, on_enter, width=None):
        e = tk.Entry(parent, bg=PANEL, fg=FG_DIM, insertbackground=FG, relief="flat",
                     font=self.app.font("Microsoft YaHei UI", 11), **({"width": width} if width else {}))
        e.hint = hint
        e.insert(0, hint)
        e.bind("<FocusIn>", lambda ev: self.clear_hint(e))
        e.bind("<FocusOut>", lambda ev: self.restore_hint(e))
        e.bind("<Return>", on_enter)
        return e

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

    def row(self, parent, done, text, note, on_toggle, on_delete):
        line = tk.Frame(parent, bg=BG)
        line.pack(fill="x", pady=2)
        box = tk.Label(line, text="☑" if done else "☐", bg=BG, cursor="hand2",
                       fg=GOOD if done else FG_DIM, font=self.app.font("Segoe UI Symbol", 14))
        box.pack(side="left", padx=(6, 8))
        body = tk.Frame(line, bg=BG)
        body.pack(side="left", fill="x", expand=True)
        text_font = tkfont.Font(family="Microsoft YaHei UI", size=round(11 * self.app.zoom), overstrike=bool(done))
        label = tk.Label(body, text=text, bg=BG, fg=FG_DIM if done else FG, cursor="hand2", font=text_font,
                         anchor="w", justify="left", wraplength=self.wrap)
        label.font = text_font  # keep a reference so Tk doesn't drop it
        label.pack(fill="x")
        if note:
            tk.Label(body, text=note, bg=BG, fg=ACCENT if not done else FG_DIM, anchor="w",
                     font=self.app.font("Microsoft YaHei UI", 9)).pack(fill="x")
        close = tk.Label(line, text="×", bg=BG, fg=FG_DIM, cursor="hand2", font=self.app.font("Segoe UI", 13))
        close.pack(side="right", padx=6)
        for w in (box, label):
            w.bind("<Button-1>", lambda e: on_toggle())
        close.bind("<Button-1>", lambda e: on_delete())

    # ---------- actions

    def add_goal(self, _=None):
        title = self.value(self.goal_entry)
        if not title:
            return
        try:
            deadline = parse_deadline(self.value(self.deadline_entry))
        except ValueError:
            self.deadline_entry.configure(bg="#7a2e2b")
            self.top.after(900, lambda: self.deadline_entry.configure(bg=PANEL))
            return
        self.app.todos.add_goal(title, deadline)
        for e in (self.goal_entry, self.deadline_entry):
            e.delete(0, "end")
        self.restore_hint(self.deadline_entry)
        self.goal_entry.focus_set()
        self.refresh()

    def add_task(self, _=None):
        text = self.value(self.task_entry)
        if text:
            goal_id = self.goal_ids[self.goal_box.current()] if self.goal_box.current() >= 0 else None
            self.app.todos.add(text, goal_id)
            self.task_entry.delete(0, "end")
            self.refresh()

    def act(self, fn, *args):
        fn(*args)
        self.refresh()

    def tick(self):
        if not self.top.winfo_exists():
            return
        row = self.app.library.current()
        self.session.configure(text=t("lib_in", time=fmt_duration(time.time() - row["start"])) if row else "")
        self.top.after(15000, self.tick)

    def refresh(self):
        todos = self.app.todos
        for frame in (self.goal_rows, self.task_rows):
            for w in frame.winfo_children():
                w.destroy()

        goals = todos.goals()
        if not goals:
            tk.Label(self.goal_rows, text=t("goal_empty"), bg=BG, fg=FG_DIM,
                     font=self.app.font("Microsoft YaHei UI", 10)).pack(anchor="w", padx=6, pady=4)
        for g in goals:
            note = " · ".join(filter(None, [countdown(g["deadline"]) if g["deadline"] else "",
                                            t("goal_tasks_done", n=g["tasks_done"]) if g["tasks_done"] else ""]))
            self.row(self.goal_rows, g["done"], g["title"], note,
                     lambda i=g["id"]: self.act(todos.toggle_goal, i), lambda i=g["id"]: self.act(todos.delete_goal, i))

        open_goals = todos.open_goals()
        previous = self.goal_box.current()
        self.goal_ids = [None] + [g["id"] for g in open_goals]
        self.goal_box.configure(values=[t("goal_none")] + [g["title"] for g in open_goals])
        self.goal_box.current(previous if 0 <= previous < len(self.goal_ids) else 0)

        rows = todos.today()
        done, total = todos.progress()
        self.progress.configure(text=t("todo_progress", done=done, total=total) if total else "")
        if not rows:
            tk.Label(self.task_rows, text=t("todo_empty"), bg=BG, fg=FG_DIM,
                     font=self.app.font("Microsoft YaHei UI", 10)).pack(anchor="w", padx=6, pady=4)
        for r in rows:
            self.row(self.task_rows, r["done"], r["text"], r["goal"] or "",
                     lambda i=r["id"]: self.act(todos.toggle, i), lambda i=r["id"]: self.act(todos.delete, i))
        # Re-fit the window to its content. Besides growing/shrinking with the lists, this makes Windows
        # repaint the whole window: without it, widgets that moved could be left drawn at their old spot.
        self.top.geometry("")
        self.top.update_idletasks()


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
