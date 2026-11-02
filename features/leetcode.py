"""LeetCode plan: Easy/Medium fluency in 12 weeks, one problem at a time with the page, VS Code and slides open."""

import datetime as dt
import os
import threading
import time
import tkinter as tk

import customtkinter as ctk

import exercise
import leetcode
import mastery
from buddy import CARD, CHIP, dark_title_bar
from focus import day_range
from i18n import t
from journal import Line, Section
from leetcode import LeetCodeStore
from library import ACCENT, BG, FG, FG_DIM, GOOD

from .base import Feature

NUDGE_HOUR = 19  # an evening reminder if no problem was tried today
LEVEL_COLOURS = {"Easy": ("#1f4a33", GOOD), "Medium": ("#4d4224", "#f0b85a")}


class LeetCodeFeature(Feature):
    id = "leetcode"
    name_key = "feat_leetcode"

    def start(self):
        self.store = LeetCodeStore(self.app.vocab.db)
        self.ready = False
        self.note = ""

        def load():
            plan = leetcode.load_plan()
            self.app.ui_q.put(("call", lambda: self.loaded(plan)))
        threading.Thread(target=load, daemon=True).start()
        self.every(30 * 60_000, self.nudge)

    def loaded(self, plan):
        if plan:
            self.store.sync(plan)
            self.ready = True
        win = self.window("plan")
        if win:
            win.refresh()

    # ---------- the plan

    def start_date(self):
        """The plan starts the first time it's opened; that also adds its goal (12 weeks) to Goals."""
        day = self.app.settings.get("leetcode_start")
        if day:
            return dt.date.fromisoformat(day)
        today = dt.date.today()
        self.app.settings["leetcode_start"] = today.isoformat()
        self.app.save()
        self.app.todos.add_goal(t("lc_goal"), today + dt.timedelta(days=leetcode.PLAN_DAYS - 1))
        return today

    def root(self):
        return os.path.join(self.app.data_dir, "leetcode")

    def menu_items(self, menu):
        menu.add_command(label=t("menu_leetcode"), command=self.open)

    def open(self):
        self.app.clear_notice()
        self.start_date()
        self.show("plan", lambda: PlanWindow(self.app, self))

    def begin(self, slug):
        """Start a problem: its LeetCode page, its folder in VS Code and, if it's a CSE 373 idea, the slides."""
        p = self.store.problem(slug)
        self.store.start(slug)
        buddy = self.app.feature("buddy")
        hit = leetcode.open_problem(
            self.root(), slug, [x.strip() for x in (p["topics"] or "").split(",")],
            getattr(buddy, "mastery", None), mastery.open_slides, on_ready=lambda sol: self.app.ui_q.put(("call", lambda: self.opened(sol))))
        self.note = t("lc_opening", title=p["title"]) + (
            "  " + t("lc_slides", deck=os.path.splitext(os.path.basename(hit[0]))[0]) if hit else "")
        self.refresh()

    def opened(self, solution):
        if solution:
            exercise.open_in_vscode(self.root(), solution)
        else:
            self.note = t("lc_gen_failed")
            self.refresh()

    def finish(self, slug, rating):
        self.store.finish(slug, rating)
        self.note = ""
        if rating == "clean":
            self.app.set_mood("celebrate", 3)
        self.refresh()

    def cancel(self, slug):
        self.store.cancel(slug)
        self.note = ""
        self.refresh()

    def refresh(self):
        win = self.window("plan")
        if win:
            win.refresh()

    # ---------- nudges and journal

    def nudge(self):
        today = dt.date.today()
        if (dt.datetime.now().hour < NUDGE_HOUR or not self.ready or not self.app.settings.get("leetcode_start")
                or self.app.settings.get("leetcode_nudged") == today.isoformat()):
            return
        if not self.store.attempts(*day_range(today)):
            self.app.settings["leetcode_nudged"] = today.isoformat()
            self.app.save()
            self.app.notify(t("lc_nudge"), self.open)

    def journal_sections(self):
        return [self.journal_section]

    def journal_section(self, app, start, end):
        rows = self.store.attempts(start, end)
        if not rows:
            return None
        marks = {"clean": "✓", "hint": "~", "solution": "×"}
        lines = [Line(f"{marks.get(r['rating'], '?')} {r['title']}", note=r["difficulty"],
                      right=t("lc_min", m=round(r["minutes"] or 0))) for r in rows]
        return Section(t("j_leetcode"), t("j_leetcode_sum", n=len(rows)), lines)


class PlanWindow:
    """Progress, the problem in progress (with a timer and how it went), today's problems, and each pattern."""

    def __init__(self, app, feature):
        self.app, self.feature = app, feature
        top = self.top = tk.Toplevel(app.root)
        top.title(t("lc_title"))
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        dark_title_bar(top)
        s = app.scale
        self.body = ctk.CTkScrollableFrame(top, fg_color=BG, scrollbar_button_color="#3a4358")
        self.body.pack(fill="both", expand=True, padx=8, pady=8)
        top.bind("<Escape>", lambda e: top.destroy())
        top.geometry(f"{int(560 * s)}x{int(700 * s)}")
        self.timer = None
        self.refresh()
        top.lift()

    def cfont(self, size, weight="normal"):
        return ctk.CTkFont(family="Microsoft YaHei UI", size=round(self.app.font("Microsoft YaHei UI", size)[1] * 4 / 3),
                           weight=weight)

    def card(self):
        c = ctk.CTkFrame(self.body, fg_color=CARD, corner_radius=16)
        c.pack(fill="x", padx=6, pady=6)
        inner = ctk.CTkFrame(c, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)
        return inner

    def text(self, parent, text, size=10, weight="normal", color=FG, **pack):
        w = ctk.CTkLabel(parent, text=text, font=self.cfont(size, weight), text_color=color, anchor="w",
                         justify="left", wraplength=460)
        w.pack(fill="x", **pack)
        return w

    def button(self, parent, text, command, primary=False, side="left", width=10):
        b = ctk.CTkButton(parent, text=text, command=command, font=self.cfont(9, "bold" if primary else "normal"),
                          fg_color=ACCENT if primary else "#3a4358", hover_color="#5aa8e8" if primary else "#4a5570",
                          text_color=BG if primary else FG, corner_radius=10, height=30, width=width)
        b.pack(side=side, padx=(0, 6))
        return b

    def refresh(self):
        if self.timer:
            self.top.after_cancel(self.timer)
            self.timer = None
        for w in self.body.winfo_children():
            w.destroy()
        f, store = self.feature, self.feature.store
        if not f.ready:
            self.text(self.card(), t("lc_no_pkg") if leetcode.resources() is None else t("lc_loading"),
                      color=FG_DIM)
            return
        start = f.start_date()
        s = store.summary()

        head = self.card()
        self.text(head, t("lc_title"), size=15, weight="bold")
        self.text(head, t("lc_sub", minutes=leetcode.MINUTES_PER_DAY), size=9, color=FG_DIM, pady=(0, 8))
        bar = ctk.CTkProgressBar(head, progress_color=GOOD, fg_color="#3a4358", height=10, corner_radius=5)
        bar.set(s["done"] / s["total"] if s["total"] else 0)
        bar.pack(fill="x", pady=(0, 6))
        day = min(leetcode.PLAN_DAYS, (dt.date.today() - start).days + 1)
        pace = store.pace(start)
        pace_text = t("lc_ahead", n=pace) if pace > 0 else t("lc_behind", n=-pace) if pace < 0 else t("lc_on_pace")
        self.text(head, t("lc_progress", done=s["done"], total=s["total"], fluent=s["fluent"], day=day,
                          days=leetcode.PLAN_DAYS) + "  ·  " + pace_text, size=10, color="#dfe5ef")
        if f.note:
            self.text(head, f.note, size=9, color=ACCENT, pady=(4, 0))

        current = store.in_progress()
        if current:
            box = self.card()
            self.text(box, t("lc_now"), size=9, color=FG_DIM)
            self.text(box, f"{current['number']}. {current['title']}", size=13, weight="bold")
            clock = self.text(box, "", size=10, color=ACCENT, pady=(0, 8))

            def tick():
                clock.configure(text=t("lc_elapsed", m=int((time.time() - current["started"]) // 60)))
                self.timer = self.top.after(15_000, tick)
            tick()
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(fill="x")
            for rating, primary in (("clean", True), ("hint", False), ("solution", False)):
                self.button(row, t("lc_" + rating), lambda r=rating: f.finish(current["slug"], r), primary)
            row2 = ctk.CTkFrame(box, fg_color="transparent")
            row2.pack(fill="x", pady=(6, 0))
            self.button(row2, t("lc_reopen"), lambda: f.begin(current["slug"]))
            self.button(row2, t("lc_cancel"), lambda: f.cancel(current["slug"]))

        day_start, day_end = day_range(dt.date.today())
        again, new, done_today = store.today(day_start, day_end, start)
        today = self.card()
        self.text(today, t("lc_today"), size=12, weight="bold", pady=(0, 6))
        rows = [(r, "again") for r in again] + [(r, "new") for r in new]
        if not rows:
            self.text(today, t("lc_done_today", n=done_today), color=GOOD)
        for r, kind in rows:
            line = ctk.CTkFrame(today, fg_color="#323a4d", corner_radius=12)
            line.pack(fill="x", pady=4)
            ctk.CTkLabel(line, text="⟳" if kind == "again" else "★", width=26,
                         text_color="#f0b85a" if kind == "again" else ACCENT,
                         font=self.cfont(11, "bold")).pack(side="left", padx=(10, 4), pady=8)
            names = ctk.CTkFrame(line, fg_color="transparent")
            names.pack(side="left", fill="x", expand=True, pady=6)
            ctk.CTkLabel(names, text=f"{r['number']}. {r['title']}", font=self.cfont(10, "bold"), text_color=FG,
                         anchor="w").pack(fill="x")
            ctk.CTkLabel(names, text=t("pat_" + r["pattern"]) + "  ·  " + t("lc_" + kind), font=self.cfont(8),
                         text_color=FG_DIM, anchor="w").pack(fill="x")
            bg, fg = leetcode_colours(r["difficulty"])
            ctk.CTkLabel(line, text=f"  {r['difficulty']}  ", fg_color=bg, text_color=fg, corner_radius=8,
                         font=self.cfont(8, "bold")).pack(side="left", padx=6)
            go = self.button(line, t("lc_start"), lambda sl=r["slug"]: f.begin(sl), primary=True, side="right", width=72)
            go.pack_configure(padx=(6, 12), pady=8)

        pats = self.card()
        self.text(pats, t("lc_patterns"), size=12, weight="bold", pady=(0, 6))
        for pattern, done, total in store.by_pattern():
            row = ctk.CTkFrame(pats, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=t("pat_" + pattern), font=self.cfont(9), text_color="#dfe5ef", anchor="w",
                         width=170).pack(side="left")
            pb = ctk.CTkProgressBar(row, progress_color=GOOD if done == total else ACCENT, fg_color="#3a4358",
                                    height=8, corner_radius=4)
            pb.set(done / total if total else 0)
            pb.pack(side="left", fill="x", expand=True, padx=8)
            ctk.CTkLabel(row, text=f"{done}/{total}", font=self.cfont(9), text_color=FG_DIM, width=40).pack(side="left")


def leetcode_colours(level):
    return LEVEL_COLOURS.get(level, (CHIP, ACCENT))
