"""Copy this file to start a new feature. It isn't loaded until it's listed in features/__init__.py.

Checklist:
  1. Pick an `id` (it becomes the key in settings.json; never rename it later).
  2. Add the strings you use to BOTH "en" and "zh" in i18n.py, including `name_key`.
  3. If you store data, give it its own table in app.vocab.db (create it in your store's
     constructor with CREATE TABLE IF NOT EXISTS; add columns with a guarded ALTER TABLE).
  4. Add the class to FEATURES in features/__init__.py.
  5. Test it in-process (see CLAUDE.md → Testing) in both languages, then commit.
"""

from i18n import t

from .base import Feature


class ExampleFeature(Feature):
    id = "example"
    name_key = "feat_example"      # add "feat_example" to i18n.py
    default_on = False

    def start(self):
        # optional: something to run every minute while the feature is on
        self.every(60_000, self.tick)

    def menu_items(self, menu):
        menu.add_command(label=t("feat_example"), command=self.open)

    def open(self):
        # self.show("main", lambda: MyWindow(self.app)) opens one window, or brings it to the front
        self.app.flash("Hello from the example feature")

    def tick(self):
        pass

    def journal_sections(self):
        # functions (app, start, end) -> journal.Section | None, shown on each day's journal page
        return []
