"""The journal: one page per day, made of the sections every other feature contributes."""

from i18n import t
from journal import JournalWindow

from .base import Feature


class JournalFeature(Feature):
    id = "journal"
    name_key = "feat_journal"

    def menu_items(self, menu):
        menu.add_command(label=t("menu_journal"), command=self.open)

    def open(self):
        self.show("journal", lambda: JournalWindow(self.app))
