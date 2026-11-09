"""The cat's bond: studying earns closeness with the first cat, which levels up, grows and unlocks things to wear (see bond.py)."""

from bond import (NICKNAME_LEVEL, SOURCES, BondStore, BondWindow, LevelUp, growth, level_of,
                  title_key, unlocked)
from i18n import t
from journal import Line, Section

from .base import Feature

SYNC_MS = 30_000


class BondFeature(Feature):
    id = "bond"
    name_key = "feat_bond"

    def start(self):
        self.store = BondStore(self.app.vocab.db)
        self.first = True
        self.app.root.after(4000, lambda: self.on and self.sync())
        self.every(SYNC_MS, self.sync)

    # ---------- state

    def level(self):
        return level_of(self.store.total())[0]

    def hat(self):
        """What the first cat wears: the owner's pick, if it's unlocked."""
        hat = self.app.settings.get("bond_hat")
        return hat if hat in unlocked(self.level()) else None

    def skin(self):
        """The first cat's skin, for the bond window's pictures."""
        try:
            return self.app.feature("pet").skins()[0]
        except StopIteration:
            return "A_adult"

    def pet_style(self):
        """(accessory, size factor) for the desktop pet; plain when the feature is off."""
        if not self.on:
            return None, 1.0
        return self.hat(), growth(self.level())

    def set_hat(self, name):
        self.app.settings["bond_hat"] = name
        self.app.save()
        self.restyle()

    def set_nick(self, nick):
        nick = nick.strip()[:20]
        if nick != self.app.settings.get("bond_nick", ""):
            self.app.settings["bond_nick"] = nick
            self.app.save()

    def restyle(self):
        pet = self.app.feature("pet")
        if getattr(pet, "cats", None):
            pet.cats[0].restyle()
        if self.window("main"):
            self.window("main").refresh()

    # ---------- picking up points

    def sync(self):
        focus = self.app.feature("focus")
        gained = self.store.sync(getattr(focus, "log", None) if focus.on else None)
        level = self.level()
        s = self.app.settings
        first = "bond_seen_level" not in s
        seen = s.get("bond_seen_level", 1)
        if level > seen:
            new = [name for name in unlocked(level) if name not in unlocked(seen)]
            if new:
                s["bond_hat"] = new[-1]  # put the newest thing on; the wardrobe can change it
            s["bond_seen_level"] = level
            self.app.save()
            self.restyle()
            LevelUp(self.app, level, seen, first=first)
        elif first:
            s["bond_seen_level"] = level
            self.app.save()
        elif gained and not self.first:
            self.app.hop()
            if gained >= 10:
                self.app.set_mood("celebrate", 2.5)
            if self.window("main"):
                self.window("main").refresh()
        self.first = False
        return gained

    # ---------- what the buddy and the card see

    def buddy_context(self):
        """A line for the study buddy's daily context, so the cat talks like the friend it has become."""
        level = self.level()
        line = t("buddy_ctx_bond", level=level, title=t(title_key(level)))
        nick = self.app.settings.get("bond_nick", "").strip()
        if nick and level >= NICKNAME_LEVEL:
            line += " " + t("buddy_ctx_nick", nick=nick)
        return line

    def menu_items(self, menu):
        level, into, need = level_of(self.store.total())
        menu.add_command(label=t("menu_bond", level=level, title=t(title_key(level)), into=into, need=need),
                         command=self.open)

    def open(self):
        self.show("main", lambda: BondWindow(self))

    def journal_sections(self):
        return [self.section]

    def section(self, app, start, end):
        got = self.store.between(start, end)
        if not got:
            return None
        lines = [Line(t(f"bond_src_{src}"), right=f"+{got[src]} ♥") for src in SOURCES if got.get(src)]
        return Section(t("j_bond"), t("j_bond_sum", n=sum(got.values())), lines)
