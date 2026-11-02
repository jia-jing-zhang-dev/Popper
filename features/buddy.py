"""Study buddy: chat with Claude (through the owner's Claude Code login) about their own course materials."""

import datetime as dt
import os
import random
import threading
import time

import exercise
from buddy import BuddyStore, ChatWindow, ClaudeBridge, FolderDialog, split_tags
from focus import day_range, idle_seconds
from i18n import t
from journal import Line, Section
from mastery import MasteryStore, MasteryWindow, SlideBuilder, course_code, exam_days, status

from .base import Feature


QUIET_FROM, QUIET_UNTIL = 23, 8  # no unprompted messages between 23:00 and 08:00
DAILY_MAX = 20                   # unprompted questions per day, at most
GAP_MINUTES = (15, 20)           # minutes of actual study between unprompted questions
EVENING_HOUR, EVENING_MINIMUM = 21, 30 * 60  # after 21:00, nudge if under 30 min of study today
DISCOVERY_HOUR, DISCOVERY_MINIMUM = 14, 30 * 60  # one "something new" a day, after 14:00 and 30 min of study
REVIEW_SHARE = 0.4                # when a missed question is due, how often it replaces a new one
EXAM_WINDOW = 30                  # days: exams closer than this decide which course gets asked about
NEAREST_SHARE = 0.7               # how often the course with the nearest exam is picked (the rest interleaves)
SLIDE_SCAN_MS = 6 * 3600 * 1000   # look for new slide decks every 6 hours


class BuddyFeature(Feature):
    id = "buddy"
    name_key = "feat_buddy"
    default_on = False  # sends course material and what's on screen to Claude, so it's opt-in

    def start(self):
        self.store = BuddyStore(self.app.vocab.db)
        self.mastery = MasteryStore(self.app.vocab.db)
        workdir = os.path.join(self.app.data_dir, "buddy")
        self.bridge = ClaudeBridge(self.app, workdir)
        # reading slides takes minutes, so it gets its own Claude Code process and never blocks the chat
        self.builder = SlideBuilder(self, ClaudeBridge(self.app, workdir), self.mastery)
        self.pending_topic = None         # the slide topic the question being asked is about
        self.last_topic = None
        self.want_exercise = False        # the student asked for a coding exercise: open it right away
        self.pending_exercise = None      # (folder, file) saved while the chat was closed; opens with the chat
        self.tools = {}

        def detect():
            tools = exercise.detect_tools()
            self.app.ui_q.put(("call", lambda: setattr(self, "tools", tools)))
        threading.Thread(target=detect, daemon=True).start()
        self.waiting = False
        self.retried = False
        self.last_question = time.time()  # studying since Popper started counts toward the first question
        self.gap = random.uniform(*GAP_MINUTES) * 60
        self.active_seconds = 0           # fallback count when study time is off
        self.every(60_000, self.tick)
        self.app.root.after(20_000, lambda: self.on and self.folders() and self.builder.start())
        self.every(SLIDE_SCAN_MS, self.builder.start)

    # ---------- settings

    def folders(self):
        return list(self.app.settings.get("buddy_folders", []))

    def set_folders(self, folders):
        self.app.settings["buddy_folders"] = list(dict.fromkeys(folders))
        self.app.save()
        self.builder.start()

    # ---------- menu and windows

    def menu_items(self, menu):
        menu.add_command(label=t("menu_buddy"), command=self.open_chat)
        menu.add_command(label=t("menu_mastery"), command=self.open_mastery)

    def open_chat(self):
        self.app.clear_notice()
        self.show("chat", lambda: ChatWindow(self.app, self))
        if self.pending_exercise:
            exercise.open_in_vscode(*self.pending_exercise)
            self.pending_exercise = None

    def open_mastery(self):
        self.show("mastery", lambda: MasteryWindow(self.app, self))

    def mastery_changed(self):
        win = self.window("mastery")
        if win:
            win.refresh()

    def course_list(self):
        """[(course, days to its exam or None)], nearest exam first."""
        goals = self.app.todos.open_goals()
        courses = list(dict.fromkeys([course_code(f) for f in self.folders()] + self.mastery.courses()))
        pairs = [(c, exam_days(c, goals)) for c in courses]
        return sorted(pairs, key=lambda p: (p[1] is None, p[1] if p[1] is not None else 0))

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
        if self.tools:
            lines.append(t("buddy_ctx_tools", tools=exercise.describe(self.tools)))
        for course, _ in self.course_list():
            sm = self.mastery.summary(course)
            if sm["total"]:
                lines.append(t("buddy_ctx_ready", course=course, total=sm["total"], known=sm["known"],
                               shaky=sm["shaky"], new=sm["new"]))
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
        raw, code = exercise.take_code(result["text"])
        text, tags = split_tags(raw)
        topic_id = self.pending_topic
        self.on_tags(text, tags, kind)
        if code:
            text += "\n" + self.save_exercise(tags, code, text, topic_id)
        if kind == "question":
            self.pending_topic = None
            self.want_exercise = False
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
            verdict = tags["verdict"].lower()
            if question:
                self.store.grade(question["id"], verdict)
                topic_id = question["topic_id"] or self.mastery.find(tags.get("topic"))
                if topic_id and verdict in ("correct", "partial", "wrong"):
                    self.mastery.record(topic_id, verdict)
                    self.mastery_changed()
        elif "topic" in tags or kind == "question":
            topic_id = (self.pending_topic if kind == "question" else None) or self.mastery.find(tags.get("topic"))
            self.store.add_question(text, tags.get("topic"), tags.get("source"), topic_id)
            self.last_topic = topic_id
        if tags.get("interest"):
            self.store.like(tags["interest"], 2)
        elif kind == "chat" and tags.get("topic") and "verdict" not in tags:
            self.store.like(tags["topic"], 0.5)

    def ask_question(self, topic_id=None):
        """Ask one question, about a gap on the slides when the checklist is built (button and scheduler)."""
        self.last_question = time.time()
        self.gap = random.uniform(*GAP_MINUTES) * 60
        self.active_seconds = 0
        row = self.mastery.topic(topic_id) if topic_id else self.choose_topic()
        if row:
            self.pending_topic = row["id"]
            prompt = t("buddy_prompt_topic", topic=row["topic"], course=row["course"],
                       deck=os.path.basename(row["path"] or ""), file=row["text_file"] or row["path"] or "?",
                       slides=row["slides"] or "?", level=t("buddy_level_" + status(row)))
        else:
            prompt = t("buddy_prompt_question")
            titles = self.studying_now()
            if titles:
                prompt = t("buddy_ctx_now", titles="; ".join(titles)) + "\n" + prompt
        self.send(prompt, "question")

    def ask_exercise(self):
        """The chat's "Code it" button: a coding exercise on a slide topic about code, opened in VS Code."""
        if self.waiting or self.bridge.busy:
            return
        row = self.choose_topic(kind="code")
        self.want_exercise = True
        self.last_question = time.time()
        if row:
            self.pending_topic = row["id"]
            prompt = t("buddy_prompt_exercise", topic=row["topic"], course=row["course"],
                       deck=os.path.basename(row["path"] or ""), file=row["text_file"] or row["path"] or "?",
                       slides=row["slides"] or "?")
        else:
            prompt = t("buddy_prompt_exercise_any")
        self.send(prompt, "question")

    def save_exercise(self, tags, code, text, topic_id):
        """Write the starter code as a runnable folder; open VS Code now if the student is here for it.
        Returns the line added to the chat."""
        lang = exercise.lang_of(tags.get("exercise"), code[0])
        if not lang:
            return t("exercise_unknown", lang=tags.get("exercise") or code[0] or "?")
        row = self.mastery.topic(topic_id) if topic_id else None
        course = row["course"] if row else (tags.get("source") or "practice")
        topic = row["topic"] if row else (tags.get("topic") or "exercise")
        folder, main = exercise.make(os.path.join(self.app.data_dir, "exercises"), course, topic, lang, code[1],
                                     text, self.tools or {"python": None})
        name = os.path.basename(folder)
        if self.want_exercise or self.window("chat"):
            exercise.open_in_vscode(folder, main)
            return t("exercise_opened", name=name)
        self.pending_exercise = (folder, main)
        return t("exercise_saved", name=name)

    def ask_about(self, topic_id):
        """From the checklist: a question on that topic, in the chat."""
        self.open_chat()
        if not (self.waiting or self.bridge.busy):
            self.ask_question(topic_id)

    def choose_topic(self, kind=None):
        """Gap-first topic: the course on screen right now, else mostly the one whose exam is nearest."""
        courses = [(c, d) for c, d in self.course_list() if self.mastery.summary(c)["total"]]
        if not courses:
            return None
        screen = " ".join(self.studying_now()).replace(" ", "").upper()
        on_screen = [c for c, _ in courses if c.replace(" ", "").upper() in screen]
        exams = [(d, c) for c, d in courses
                 if d is not None and d <= EXAM_WINDOW and self.mastery.summary(c)["ready"] < 100]
        if on_screen:
            course = on_screen[0]
        elif exams and random.random() < NEAREST_SHARE:
            course = min(exams)[1]
        else:
            weights = [1 / (1 + d) if d is not None and d <= EXAM_WINDOW else 0.02 for _, d in courses]
            course = random.choices([c for c, _ in courses], weights)[0]
        return self.mastery.pick(course, avoid=self.last_topic, kind=kind)

    def ask_review(self, missed):
        """Come back to a missed question, worded differently."""
        self.last_question = time.time()
        self.gap = random.uniform(*GAP_MINUTES) * 60
        self.active_seconds = 0
        self.store.take_review(missed["id"])
        self.pending_topic = missed["topic_id"]
        self.send(t("buddy_prompt_review", question=missed["question"], topic=missed["topic"] or "?"), "question")

    def review_now(self):
        due = self.store.due_reviews()
        if due:
            self.ask_review(due[0])
        else:
            self.note(t("buddy_no_reviews"))

    def discover(self):
        """Once a day: something interesting just beyond the courses, picked from what the student likes."""
        interests = self.store.interests()
        prompt = t("buddy_prompt_discovery", interests=", ".join(interests) if interests else t("buddy_none_yet"))
        titles = self.studying_now()
        if titles:
            prompt = t("buddy_ctx_now", titles="; ".join(titles)) + "\n" + prompt
        self.send(prompt, "discovery")

    def journal_sections(self):
        return [self.journal_section, self.readiness_section]

    def readiness_section(self, app, start, end):
        """Exam readiness per course on today's page; slide topics answered that day on any page."""
        lines, summary = [], []
        if start <= time.time() < end:
            for course, days in self.course_list():
                sm = self.mastery.summary(course)
                if sm["total"]:
                    when = t("mastery_no_exam") if days is None else (
                        t("mastery_exam", days=days) if days else t("mastery_exam_today"))
                    lines.append(Line(f"{course} · {t('mastery_ready', ready=sm['ready'])}",
                                      note=t("mastery_counts", known=sm["known"], shaky=sm["shaky"], new=sm["new"]),
                                      right=when, on_click=self.open_mastery))
                    summary.append(f"{course} {sm['ready']}%")
        mark = {"correct": "✓", "partial": "~", "wrong": "×"}
        answered = self.mastery.answered_on(start, end)
        for topic, verdict in answered:
            lines.append(Line(f"{mark.get(verdict, '?')} {topic}"))
        if not lines:
            return None
        return Section(t("j_mastery"), "  ".join(summary[:3]) or t("j_mastery_sum", n=len(answered)), lines)

    def journal_section(self, app, start, end):
        asked, verdicts, topics = self.store.day_summary(start, end)
        if not asked:
            return None
        lines = [Line(t("j_buddy_result", correct=verdicts.get("correct", 0), partial=verdicts.get("partial", 0),
                        wrong=verdicts.get("wrong", 0)))]
        lines += [Line(topic) for topic in topics[:8]]
        return Section(t("j_buddy"), t("j_buddy_sum", n=asked), lines)

    # ---------- being a fussy friend

    def studying_now(self):
        focus = self.app.feature("focus")
        return focus.log.recent_study_titles() if focus.on else []

    def studied_since(self, since):
        """Seconds of real study since `since` (from study time if it's on, else time at the keyboard)."""
        focus = self.app.feature("focus")
        if focus.on:
            return focus.log.split(focus.log.by_key(since, time.time() + 60))[0]
        return self.active_seconds

    def quiet(self):
        hour = dt.datetime.now().hour
        return (hour >= QUIET_FROM or hour < QUIET_UNTIL
                or self.app.settings.get("buddy_snooze") == dt.date.today().isoformat())

    def said_today(self, kind):
        return any(m["kind"] == kind and m["role"] == "buddy" for m in self.store.messages(dt.date.today()))

    def tick(self):
        """Once a minute: decide whether to check in."""
        away = idle_seconds() > 180
        if not away:
            self.active_seconds += 60
        if self.waiting or self.bridge.busy or self.quiet() or away:
            return
        start, _ = day_range(dt.date.today())
        if dt.datetime.now().hour < 12 and not self.said_today("morning"):  # a "good morning" only in the morning
            self.morning()
            return
        if (dt.datetime.now().hour >= EVENING_HOUR and not self.said_today("evening")
                and self.studied_since(start) < EVENING_MINIMUM):
            self.evening()
            return
        open_q = self.store.open_question()
        if open_q and time.time() - open_q["ts"] < 40 * 60:
            return  # wait for an answer before asking more
        if (dt.datetime.now().hour >= DISCOVERY_HOUR and not self.said_today("discovery")
                and self.studied_since(start) >= DISCOVERY_MINIMUM):
            self.discover()
            return
        asked = self.store.db.execute("SELECT COUNT(*) FROM buddy_questions WHERE ts >= ?", (start,)).fetchone()[0]
        if asked < DAILY_MAX and self.studied_since(self.last_question) >= self.gap:
            due = self.store.due_reviews()
            if due and random.random() < REVIEW_SHARE:
                self.ask_review(due[0])
            else:
                self.ask_question()

    def local_message(self, text, kind, mood="talking"):
        """A message Popper writes itself (no Claude call)."""
        self.store.say("buddy", text, kind)
        win = self.window("chat")
        if win:
            win.add_line("buddy", text)
        else:
            self.app.notify(t("buddy_has_word"), self.open_chat, mood)

    def morning(self):
        today = dt.date.today()
        exams = []
        for g in self.app.todos.open_goals():
            if g["deadline"]:
                days = (dt.date.fromisoformat(g["deadline"]) - today).days
                if 0 <= days <= 21:
                    exams.append((days, g["title"]))
        lines = [t("buddy_morning")]
        for days, title in sorted(exams)[:3]:
            lines.append(t("buddy_morning_exam", title=title, days=days) if days
                         else t("buddy_morning_today", title=title))
        due = self.store.db.execute("SELECT COUNT(*) FROM buddy_questions WHERE due IS NOT NULL AND due <= ?",
                                    (time.time(),)).fetchone()[0]
        for course, days in self.course_list()[:2]:
            sm = self.mastery.summary(course)
            if sm["total"] and days is not None and days <= 21:
                lines.append(t("buddy_morning_ready", course=course, ready=sm["ready"], new=sm["new"],
                               shaky=sm["shaky"]))
        if due:
            lines.append(t("buddy_morning_review", n=due))
        self.local_message("\n".join(lines), "morning")

    def evening(self):
        studied = self.studied_since(day_range(dt.date.today())[0])
        self.local_message(t("buddy_evening", minutes=int(studied // 60)), "evening", mood="worried")

    def _busy(self, busy):
        win = self.window("chat")
        if win:
            win.set_busy(busy)
        self.app.refresh_mood()  # the bubble thinks while Claude does
