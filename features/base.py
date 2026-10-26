"""What every Popper feature looks like.

Looking words up is the card itself and always on. Everything else (review, goals and to-dos, the
library check-in, the journal...) is a Feature: one module in this folder, listed in
features/__init__.py, switched on or off in Settings → Features.

Shared data (app.vocab, app.library, app.todos, app.journal) lives on the app, because features read
each other's data (the journal shows tasks and words, the library log counts new words).
"""


class Feature:
    id = ""            # key in settings.json; never rename it once released
    name_key = ""      # i18n key of the name shown in Settings
    default_on = True  # whether it's on for someone who never touched Settings

    def __init__(self, app):
        self.app = app
        self._windows = {}

    @property
    def on(self):
        return self.app.feature_on(self.id)

    # ---------- hooks: override what you need

    def start(self):
        """Called once at startup, whether or not the feature is on. Schedule timers here (see every)."""

    def menu_items(self, menu):
        """Add entries to the card's right-click menu. Only called while the feature is on."""

    def journal_sections(self):
        """Functions `(app, start, end) -> journal.Section | None` that add to each journal page."""
        return []

    # ---------- helpers

    def every(self, ms, fn):
        """Run fn every `ms` milliseconds while the feature is on."""
        def run():
            try:
                if self.on:
                    fn()
            finally:
                self.app.root.after(ms, run)
        self.app.root.after(ms, run)

    def show(self, key, make):
        """Bring this feature's window `key` to the front (refreshing it), or create it with make()."""
        win = self.window(key)
        if win:
            win.top.lift()
            if hasattr(win, "refresh"):
                win.refresh()
            return win
        self._windows[key] = make()
        return self._windows[key]

    def window(self, key):
        """The open window `key`, or None."""
        win = self._windows.get(key)
        return win if win and win.top.winfo_exists() else None
