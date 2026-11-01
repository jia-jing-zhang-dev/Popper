"""Study buddy: chat with Claude (through the owner's Claude Code login) about their own course materials."""

import datetime as dt
import os

from buddy import BuddyStore, ChatWindow, ClaudeBridge, FolderDialog, split_tags
from i18n import t

from .base import Feature


class BuddyFeature(Feature):
    id = "buddy"
    name_key = "feat_buddy"
    default_on = False  # sends course material and what's on screen to Claude, so it's opt-in

    def start(self):
        self.store = BuddyStore(self.app.vocab.db)
        self.bridge = ClaudeBridge(self.app, os.path.join(self.app.data_dir, "buddy"))
        self.waiting = False
        self.retried = False

    # ---------- settings

    def folders(self):
        return list(self.app.settings.get("buddy_folders", []))

    def set_folders(self, folders):
        self.app.settings["buddy_folders"] = list(dict.fromkeys(folders))
        self.app.save()

    # ---------- menu and windows

    def menu_items(self, menu):
        menu.add_command(label=t("menu_buddy"), command=self.open_chat)

    def open_chat(self):
        self.app.clear_notice()
        self.show("chat", lambda: ChatWindow(self.app, self))

    def open_folders(self):
        self.show("folders", lambda: FolderDialog(self.app, self))

    def snooze_today(self):
        self.app.settings["buddy_snooze"] = dt.date.today().isoformat()
        self.app.save()
        self.note(t("buddy_snoozed"))

    def note(self, text):
        """A grey line in the chat (not stored, not sent to Claude)."""
        win = self.window("chat")
        if win:
            win.view.configure(state="normal")
            win.view.insert("end", text + "\n", "note")
            win.view.configure(state="disabled")
            win.view.see("end")

    # ---------- talking to Claude

    def context(self):
        """What the buddy should know at the start of each day's conversation."""
        today = dt.date.today()
        lines = [t("buddy_ctx_today", date=today.isoformat(), weekday=today.strftime("%A"))]
        folders = [os.path.basename(f) for f in self.folders()]
        if folders:
            lines.append(t("buddy_ctx_courses", courses=", ".join(folders)))
        for g in self.app.todos.open_goals():
            if g["deadline"]:
                days = (dt.date.fromisoformat(g["deadline"]) - today).days
                if days >= 0:
                    lines.append(t("buddy_ctx_goal", title=g["title"], days=days, date=g["deadline"]))
        return "\n".join(["[context]"] + lines + ["[/context]"])

    def send(self, prompt, kind):
        """Send one message in today's session; the first message of a day carries the context."""
        day = dt.date.today()
        session_id = self.store.session(day)
        if not session_id:
            prompt = self.context() + "\n\n" + prompt
        self.waiting = True
        self._busy(True)
        self.bridge.ask(prompt, self.folders(), session_id,
                        lambda r, p=prompt, k=kind, d=day, s=session_id: self.on_reply(r, p, k, d, s))

    def chat(self, text):
        self.store.say("me", text)
        win = self.window("chat")
        if win:
            win.add_line("me", text)
        self.send(text, "chat")

    def on_reply(self, result, prompt, kind, day, session_id):
        self.waiting = False
        self._busy(False)
        if not result["ok"]:
            if session_id and not self.retried:  # the saved session may be gone: start today's again
                self.retried = True
                self.store.set_session(day, "")
                self.send(prompt, kind)
                return
            self.retried = False
            self.note(t("buddy_error", error=result["error"]))
            return
        self.retried = False
        if result.get("session_id"):
            self.store.set_session(day, result["session_id"])
        text, tags = split_tags(result["text"])
        self.on_tags(text, tags, kind)
        self.store.say("buddy", text, kind)
        win = self.window("chat")
        if win:
            win.add_line("buddy", text)
        elif kind != "chat":
            self.app.notify(t("buddy_has_message"), self.open_chat)

    def on_tags(self, text, tags, kind):
        """Book-keeping from the tags at the end of a reply."""
        if "verdict" in tags:
            question = self.store.open_question()
            if question:
                self.store.grade(question["id"], tags["verdict"].lower())
        elif "topic" in tags or kind == "question":
            self.store.add_question(text, tags.get("topic"), tags.get("source"))
        if tags.get("interest"):
            self.store.like(tags["interest"], 2)

    def ask_question(self):
        """Ask for one question about what the student is studying (used by the button and the scheduler)."""
        self.send(t("buddy_prompt_question"), "question")

    def _busy(self, busy):
        win = self.window("chat")
        if win:
            win.set_busy(busy)
