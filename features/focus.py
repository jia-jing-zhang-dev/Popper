"""Study time: works out on its own when you're actually studying, and keeps count."""

import datetime as dt

from focus import SAMPLE_MS, FocusLog, FocusWindow, day_range, label_of
from i18n import t
from journal import Line, Section
from library import fmt_duration

from .base import Feature


class FocusFeature(Feature):
    id = "focus"
    name_key = "feat_focus"
    default_on = False  # it watches which window is in front, so it's opt-in

    def start(self):
        self.log = FocusLog(self.app.vocab.db)
        self.every(SAMPLE_MS, self.log.sample)
        self.every(60_000, self.log.flush)

    def menu_items(self, menu):
        study, _ = self.log.split(self.log.by_key(*day_range(dt.date.today())))
        menu.add_command(label=t("menu_focus", time=fmt_duration(study)), command=self.open)

    def open(self):
        self.show("main", lambda: FocusWindow(self.app, self.log))

    def journal_sections(self):
        return [self.section]

    def section(self, app, start, end):
        totals = self.log.by_key(start, end)
        study, other = self.log.split(totals)
        if study < 60 and other < 60:
            return None
        rules = self.log.rules()
        lines = [Line(label_of(key), right=fmt_duration(seconds))
                 for key, seconds in sorted(totals.items(), key=lambda kv: -kv[1])
                 if seconds >= 60 and self.log.category(key, rules) == "study"][:8]
        if other >= 60:
            lines.append(Line(t("j_focus_other"), right=fmt_duration(other)))
        return Section(t("j_focus"), t("j_focus_sum", time=fmt_duration(study)), lines)
