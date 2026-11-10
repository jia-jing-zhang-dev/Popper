"""Pomodoro: focus for 25 minutes, then a 5-minute break (a longer one after every fourth).

No countdown: the card's top row shows today's rounds as dots instead, the current one filling up like a
moon (○ ◔ ◑ ◕), so you know roughly where you are without watching the clock. Stopping a pomodoro early is fine but earns nothing. Each finished
pomodoro earns the cats one meal (`pet_meals`, up to MAX_MEALS saved up): with this feature on, the food bowl
can only be filled with a meal you earned. Finished pomodoros are kept in the `pomodoros` table for the journal.
The running timer is saved in settings (`pomo`), so it survives a restart.
"""

import datetime as dt
import time

from i18n import t
from journal import Line, Section
from library import ACCENT, GOOD, fmt_duration

from .base import Feature

LENGTHS = ((25, 5), (45, 10), (50, 10), (15, 3))   # (focus, break) minutes; the first is the default
LONG_BREAK = 15        # minutes, after every LONG_EVERY pomodoros in a day
LONG_EVERY = 4
MAX_MEALS = 3


class PomodoroStore:
    def __init__(self, db):
        self.db = db
        db.execute("""CREATE TABLE IF NOT EXISTS pomodoros (
                          id INTEGER PRIMARY KEY,
                          start REAL NOT NULL,
                          end REAL NOT NULL,
                          minutes INTEGER NOT NULL)""")
        db.commit()

    def add(self, start, end, minutes):
        self.db.execute("INSERT INTO pomodoros (start, end, minutes) VALUES (?, ?, ?)", (start, end, minutes))
        self.db.commit()

    def between(self, start, end):
        return self.db.execute("SELECT * FROM pomodoros WHERE end >= ? AND end < ? ORDER BY end", (start, end)).fetchall()

    def today(self):
        start = dt.datetime.combine(dt.date.today(), dt.time()).timestamp()
        return len(self.between(start, start + 86400))


def lengths(settings):
    pair = tuple(settings.get("pomo_lengths") or LENGTHS[0])
    return pair if pair in LENGTHS else LENGTHS[0]


PHASES = "○◔◑◕"   # the round in progress: just started, a quarter, half, three quarters done
GROUP = 4          # a small gap after every four rounds, like a set
MAX_DOTS = 8       # beyond this: "●×9"


def dots(done, part=None):
    """Today's finished rounds as ●, plus the one in progress (part 0..1) as a filling moon."""
    if done > MAX_DOTS:
        text = f"●×{done}"
    else:
        text = " ".join("●" * len(chunk) for chunk in
                        ["x" * min(GROUP, done - i) for i in range(0, done, GROUP)])
    if part is not None:
        text = (text + " " if text else "") + PHASES[min(len(PHASES) - 1, int(part * len(PHASES)))]
    return text


class PomodoroFeature(Feature):
    id = "pomodoro"
    name_key = "feat_pomodoro"
    default_on = True

    def start(self):
        self.store = PomodoroStore(self.app.vocab.db)
        self.app.root.after(1000, self.tick_loop)

    # ---------- state: settings["pomo"] = {"phase": "focus" | "break", "start": ts, "end": ts} or None

    def state(self):
        return self.app.settings.get("pomo")

    def set_state(self, state):
        self.app.settings["pomo"] = state
        self.app.save()
        self.tick()

    def meals(self):
        return int(self.app.settings.get("pet_meals", 1))   # everyone starts with one meal in hand

    def use_meal(self):
        self.app.settings["pet_meals"] = max(0, self.meals() - 1)
        self.app.save()

    # ---------- menu

    def menu_items(self, menu):
        st = self.state()
        if not st:
            menu.add_command(label=t("menu_pomo_start", n=self.store.today() + 1), command=self.start_focus)
        elif st["phase"] == "focus":
            menu.add_command(label=t("menu_pomo_stop", n=self.store.today() + 1), command=self.stop)
        else:
            menu.add_command(label=t("menu_pomo_skip_break"), command=self.start_focus)

    def start_focus(self):
        focus, _ = lengths(self.app.settings)
        now = time.time()
        self.app.clear_notice()
        self.set_state({"phase": "focus", "start": now, "end": now + focus * 60})
        self.app.flash(t("pomo_started", n=self.store.today() + 1))

    def stop(self):
        self.set_state(None)
        self.app.flash(t("pomo_stopped"))

    # ---------- the clock

    def tick_loop(self):
        try:
            self.tick()
        finally:
            self.app.root.after(1000, self.tick_loop)

    def tick(self):
        st = self.state()
        if not self.on or not st:
            self.app.set_badge("pomo", None)
            return
        now = time.time()
        if now < st["end"]:
            done = self.store.today()
            if st["phase"] == "focus":
                part = (now - st["start"]) / max(1, st["end"] - st["start"])
                self.app.set_badge("pomo", dots(done, part), fg=ACCENT, on_click=lambda: self.where(part))
            else:
                self.app.set_badge("pomo", dots(done), fg=GOOD, on_click=lambda: self.app.flash(t("pomo_on_break")))
            return
        if st["phase"] == "focus":
            self.finish(st)
        else:
            self.app.settings["pomo"] = None
            self.app.save()
            self.app.set_badge("pomo", None)
            self.app.notify(t("pomo_break_over"), self.start_focus, mood="worried")
            self.app.root.after(2500, self.hungry_hint)   # after the card cat's little reaction to the note

    def where(self, part):
        """Clicking the dots: which round this is and roughly how far along, never the minutes left."""
        key = ("pomo_where_start", "pomo_where_quarter", "pomo_where_half", "pomo_where_end")[min(3, int(part * 4))]
        self.app.flash(t("pomo_where", n=self.store.today() + 1, how=t(key)), 2500)

    def hungry_hint(self):
        """Break's over, said the cats' way: one of them goes and sits by the empty bowl, or looks up at you."""
        pets = self.app.feature("pet")
        if not (pets.on and pets.cats):
            return
        free = [c for c in reversed(pets.cats) if not c.busy()]   # the cat without the card first
        if not free:
            return
        bowl = pets.items.get("food")
        if bowl and pets.needs()["food"] <= 0.01:
            free[0].beg(bowl)
        else:
            free[0].answer_you()

    def finish(self, st):
        """A pomodoro done: a meal for the cats, a break, and the cats say well done."""
        minutes = round((st["end"] - st["start"]) / 60)
        self.store.add(st["start"], st["end"], minutes)
        if self.meals() < MAX_MEALS:
            self.app.settings["pet_meals"] = self.meals() + 1
        _, rest = lengths(self.app.settings)
        n = self.store.today()
        if n % LONG_EVERY == 0:
            rest = LONG_BREAK
        end = max(time.time(), st["end"]) + rest * 60
        self.app.settings["pomo"] = {"phase": "break", "start": st["end"], "end": end}
        self.app.save()
        self.app.set_mood("celebrate", 6)
        pets = self.app.feature("pet")
        if pets.on and pets.cats:
            for cat in pets.cats:
                cat.answer_you()
            self.app.notify(t("pomo_done_feed", n=n, m=rest), pets.feed)
        else:
            self.app.notify(t("pomo_done", n=n, m=rest), lambda: None)
        self.tick()

    def journal_sections(self):
        return [pomodoro_section]


def pomodoro_section(app, start, end):
    rows = app.feature("pomodoro").store.between(start, end)
    if not rows:
        return None
    lines = [Line(f"{dt.datetime.fromtimestamp(r['start']).strftime('%H:%M')} – "
                  f"{dt.datetime.fromtimestamp(r['end']).strftime('%H:%M')}", right=f"{r['minutes']} min") for r in rows]
    total = sum(r["minutes"] for r in rows) * 60
    return Section(t("j_pomo"), t("j_pomo_sum", n=len(rows), time=fmt_duration(total)), lines)
