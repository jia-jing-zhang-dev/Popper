"""Journal: one page per day with everything you did, plus a written reflection.

A page is made of sections. Each feature contributes its own through Feature.journal_sections():
functions `(app, start, end) -> Section | None` that read one kind of activity for a day.
"""

import datetime as dt
import time
import tkinter as tk
from dataclasses import dataclass, field

from i18n import t
from library import ACCENT, BG, FG, FG_DIM, PANEL, day_label

JOURNAL_DAYS = 120   # how far back the day list goes
SAVE_DELAY_MS = 700  # reflections are saved this long after you stop typing


class Journal:
    """Written reflections, one per day."""

    def __init__(self, db):
        self.db = db
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS journal (
                day        TEXT PRIMARY KEY,
                reflection TEXT,
                updated    REAL
            )""")
        self.db.commit()

    def reflection(self, day):
        row = self.db.execute("SELECT reflection FROM journal WHERE day=?", (day.isoformat(),)).fetchone()
        return row[0] if row else ""

    def save(self, day, text):
        if text.strip():
            self.db.execute("INSERT INTO journal (day, reflection, updated) VALUES (?, ?, ?) "
                            "ON CONFLICT(day) DO UPDATE SET reflection=excluded.reflection, updated=excluded.updated",
                            (day.isoformat(), text, time.time()))
        else:
            self.db.execute("DELETE FROM journal WHERE day=?", (day.isoformat(),))
        self.db.commit()

    def days_written(self, since):
        return {dt.date.fromisoformat(d) for (d,) in
                self.db.execute("SELECT day FROM journal WHERE day >= ?", (since.isoformat(),))}


# ---------------------------------------------------------------- sections

@dataclass
class Line:
    text: str
    note: str = ""          # dim text after the main text (a goal, a translation...)
    right: str = ""         # right-aligned value (a duration)
    on_click: object = None
    on_double: object = None


@dataclass
class Section:
    title: str
    summary: str            # short form for the day list and the page header, e.g. "3 tasks"
    lines: list = field(default_factory=list)
    hint: str = ""


def day_bounds(day):
    start = dt.datetime.combine(day, dt.time()).timestamp()
    return start, start + 86400


def page(app, day):
    start, end = day_bounds(day)
    return [s for s in (make(app, start, end) for make in app.journal_sections()) if s]


def active_days(app, days=JOURNAL_DAYS):
    """Days with anything in the journal, newest first; today is always there."""
    first = dt.date.today() - dt.timedelta(days=days - 1)
    since = dt.datetime.combine(first, dt.time()).timestamp()
    found = {dt.date.today()} | app.journal.days_written(first)
    found |= {d for d in app.library.daily_totals(since) if d >= first}
    found |= set(app.todos.done_by_day(since))
    for (added,) in app.vocab.db.execute("SELECT added FROM words WHERE added >= ?", (since,)):
        found.add(dt.date.fromtimestamp(added))
    return sorted(found, reverse=True)


# ---------------------------------------------------------------- window

class JournalWindow:
    def __init__(self, app, day=None):
        self.app = app
        self.day = day or dt.date.today()
        self.save_job = None
        top = self.top = tk.Toplevel(app.root)
        top.title(t("journal_title"))
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        s = app.scale
        f = app.font

        # day list
        left = tk.Frame(top, bg=BG)
        left.pack(side="left", fill="y", padx=(16, 8), pady=16)
        tk.Label(left, text=t("journal_title"), bg=BG, fg=FG, font=f("Microsoft YaHei UI", 15)).pack(anchor="w")
        self.days = tk.Listbox(left, bg=PANEL, fg=FG, selectbackground=ACCENT, selectforeground=BG,
                               activestyle="none", relief="flat", highlightthickness=0, exportselection=False,
                               width=26, font=f("Microsoft YaHei UI", 10))
        self.days.pack(fill="y", expand=True, pady=(10, 0))
        self.days.bind("<<ListboxSelect>>", self.on_select)

        # the day's page
        right = tk.Frame(top, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(8, 16), pady=16)
        self.title = tk.Label(right, bg=BG, fg=FG, font=f("Microsoft YaHei UI", 15), anchor="w")
        self.title.pack(fill="x")
        self.summary = tk.Label(right, bg=BG, fg=ACCENT, font=f("Microsoft YaHei UI", 10), anchor="w")
        self.summary.pack(fill="x", pady=(2, 8))

        body = tk.Frame(right, bg=PANEL)
        body.pack(fill="both", expand=True)
        self.view = tk.Text(body, bg=PANEL, fg=FG, relief="flat", wrap="word", cursor="arrow", width=1, height=1,
                            padx=int(12 * s), pady=int(8 * s), spacing1=int(2 * s), spacing3=int(2 * s),
                            font=f("Microsoft YaHei UI", 10), highlightthickness=0,
                            selectbackground=PANEL, inactiveselectbackground=PANEL)
        scroll = tk.Scrollbar(body, command=self.view.yview)
        self.view.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.view.pack(side="left", fill="both", expand=True)
        self.view.tag_configure("section", foreground=ACCENT, font=f("Microsoft YaHei UI Semibold", 11),
                                spacing1=int(12 * s))
        self.view.tag_configure("hint", foreground=FG_DIM, font=f("Microsoft YaHei UI", 8))
        self.view.tag_configure("note", foreground=FG_DIM)
        self.view.tag_configure("right", foreground=FG_DIM)
        self.view.tag_configure("empty", foreground=FG_DIM)
        self.view.bind("<Configure>", lambda e: self.view.configure(tabs=(max(e.width - int(30 * s), 100), "right")))

        head = tk.Frame(right, bg=BG)
        head.pack(fill="x", pady=(14, 4))
        tk.Label(head, text=t("j_reflect"), bg=BG, fg=FG, font=f("Microsoft YaHei UI", 11)).pack(side="left")
        self.saved = tk.Label(head, bg=BG, fg=FG_DIM, font=f("Microsoft YaHei UI", 9))
        self.saved.pack(side="right")
        self.note = tk.Text(right, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", wrap="word", height=7,
                            width=1, padx=int(12 * s), pady=int(8 * s), font=f("Microsoft YaHei UI", 11),
                            highlightthickness=0, undo=True)
        self.note.pack(fill="x")
        self.note.tag_configure("placeholder", foreground=FG_DIM)
        self.note.bind("<FocusIn>", self.clear_placeholder)
        self.note.bind("<FocusOut>", lambda e: (self.save_now(), self.show_placeholder()))
        self.note.bind("<KeyRelease>", self.schedule_save)

        top.protocol("WM_DELETE_WINDOW", self.close)
        top.bind("<Escape>", lambda e: self.close())
        top.geometry(f"{int(980 * s)}x{int(680 * s)}")
        self.refresh()
        top.lift()
        top.focus_force()

    # ---------- reflection

    def placeholder_on(self):
        return "placeholder" in self.note.tag_names("1.0")

    def show_placeholder(self):
        if not self.note.get("1.0", "end").strip():
            self.note.delete("1.0", "end")
            self.note.insert("1.0", t("j_reflect_hint"), "placeholder")

    def clear_placeholder(self, _=None):
        if self.placeholder_on():
            self.note.delete("1.0", "end")

    def text(self):
        return "" if self.placeholder_on() else self.note.get("1.0", "end").rstrip()

    def schedule_save(self, _=None):
        if self.save_job:
            self.top.after_cancel(self.save_job)
        self.save_job = self.top.after(SAVE_DELAY_MS, self.save_now)

    def save_now(self):
        if self.save_job:
            self.top.after_cancel(self.save_job)
            self.save_job = None
        if self.app.journal.reflection(self.day) != self.text():
            self.app.journal.save(self.day, self.text())
            self.saved.configure(text=t("j_saved", time=time.strftime("%H:%M")))
            self.fill_days()

    def close(self):
        self.save_now()
        self.top.destroy()

    # ---------- days

    def on_select(self, _=None):
        sel = self.days.curselection()
        if sel and self.day_list[sel[0]] != self.day:
            self.save_now()
            self.day = self.day_list[sel[0]]
            self.refresh()

    def fill_days(self):
        self.day_list = active_days(self.app)
        if self.day not in self.day_list:
            self.day_list = sorted(set(self.day_list) | {self.day}, reverse=True)
        self.days.delete(0, "end")
        written = self.app.journal.days_written(self.day_list[-1])
        for day in self.day_list:
            sections = page(self.app, day)
            bits = [sec.summary for sec in sections]
            mark = "✎ " if day in written else ""
            self.days.insert("end", f" {mark}{day_label(day)}" + (f"   {bits[0]}" if bits else ""))
        i = self.day_list.index(self.day)
        self.days.selection_clear(0, "end")
        self.days.selection_set(i)
        self.days.see(i)

    def refresh(self):
        self.fill_days()
        sections = page(self.app, self.day)
        self.title.configure(text=t("j_day_title", date=day_label(self.day), full=self.day.isoformat()))
        self.summary.configure(text="   ·   ".join(sec.summary for sec in sections))

        v = self.view
        v.configure(state="normal")
        v.delete("1.0", "end")
        if not sections:
            v.insert("end", t("j_nothing"), "empty")
        for n, sec in enumerate(sections):
            v.insert("end", f"{sec.title}\n", "section")
            for k, line in enumerate(sec.lines):
                tag = f"line-{n}-{k}"
                v.insert("end", line.text, tag)
                if line.note:
                    v.insert("end", f"   {line.note}", (tag, "note"))
                v.insert("end", f"\t{line.right}\n" if line.right else "\n", (tag, "right"))
                if line.on_click:  # e.g. hear a word; nothing on the page changes
                    v.tag_bind(tag, "<Button-1>", lambda e, fn=line.on_click: fn())
                if line.on_double:  # e.g. put a task back on today's list; the page changes
                    v.tag_bind(tag, "<Double-1>", lambda e, fn=line.on_double: (fn(), self.refresh()))
                if line.on_click or line.on_double:
                    v.tag_bind(tag, "<Enter>", lambda e: v.configure(cursor="hand2"))
                    v.tag_bind(tag, "<Leave>", lambda e: v.configure(cursor="arrow"))
            if sec.hint:
                v.insert("end", f"{sec.hint}\n", "hint")
        v.configure(state="disabled")

        self.note.delete("1.0", "end")
        self.note.insert("1.0", self.app.journal.reflection(self.day))
        self.note.edit_reset()
        self.saved.configure(text="")
        if self.top.focus_get() is not self.note:
            self.show_placeholder()
