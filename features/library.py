"""Library check-in: one button checks in or out; the library log shows time, streak and heatmap."""

import datetime as dt
import time
from tkinter import messagebox

from i18n import t
from journal import Line, Section
from library import LibraryWindow, fmt_duration, fmt_long

from .base import Feature


class LibraryFeature(Feature):
    id = "library"
    name_key = "feat_library"
    default_on = False

    def start(self):
        self.every(30000, self.close_stale)

    def menu_items(self, menu):
        session = self.app.library.current()
        label = (t("menu_lib_in_now", time=fmt_duration(time.time() - session["start"])) if session
                 else t("menu_lib"))
        menu.add_command(label=label, command=self.toggle)
        menu.add_command(label=t("menu_lib_stats"), command=self.open_log)

    def toggle(self):
        """Check in (and open today's to-dos) or check out, whichever applies."""
        app, todos = self.app, self.app.feature("todos")
        if app.library.current():
            seconds = app.library.check_out()
            message = t("flash_lib_out", time=fmt_long(seconds))
            done, total = app.todos.progress()
            if todos.on and total:
                message += t("flash_lib_tasks", done=done, total=total)
            app.flash(message, ms=4000)
        else:
            app.library.check_in()
            app.flash(t("flash_lib_in", time=time.strftime("%H:%M")), ms=3000)
            if todos.on:
                todos.open()
        if self.window("log"):
            self.window("log").refresh()

    def open_log(self):
        self.show("log", lambda: LibraryWindow(self.app))

    def close_stale(self):
        """End a session nobody checked out of."""
        if self.app.library.close_stale():
            messagebox.showinfo(t("lib_title"), t("lib_auto_closed"), parent=self.app.root)
            if self.window("log"):
                self.window("log").refresh()

    def journal_sections(self):
        return [library_section]


def library_section(app, start, end):
    rows = app.library.db.execute(
        "SELECT * FROM library_sessions WHERE start < ? AND COALESCE(end, ?) > ? ORDER BY start",
        (end, time.time(), start)).fetchall()
    if not rows:
        return None
    lines, total = [], 0
    for r in rows:
        a, b = max(r["start"], start), min(r["end"] or time.time(), end)
        total += b - a
        until = dt.datetime.fromtimestamp(r["end"]).strftime("%H:%M") if r["end"] else t("lib_ongoing")
        lines.append(Line(f"{dt.datetime.fromtimestamp(r['start']).strftime('%H:%M')} – {until}",
                          right=fmt_duration(b - a)))
    return Section(t("j_library"), t("j_library_sum", time=fmt_duration(total)), lines)
