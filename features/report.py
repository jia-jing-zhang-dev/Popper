"""Study reports by email: a daily one when you shut down, a weekly one on Monday, a monthly one on the 1st.

When things go out (none of it can happen while the computer is off):
  - Shutting down after DAY_DONE_HOUR sends today's report (Windows gives a few seconds; the shutdown screen
    says why it waits). Before that hour a shutdown is usually a restart, so it waits.
  - Otherwise `catch_up` (a minute after start, then every 10 minutes) sends what's due: yesterday's report
    once it's past NEW_DAY_HOUR, last week's on Monday, last month's on the 1st.
Each day's report goes out once and is never resent, even if you study more after it (the owner asked).
Each report carries a short note from the study buddy (Claude) when there's time to ask for one: the evening
note is prepared ahead (after NOTE_HOUR) for the shutdown report; catch-up reports ask on the spot.
What was sent is remembered in settings["report_sent"]; the addresses in settings, the app password in
Windows Credential Manager.
"""

import ctypes
import datetime as dt
import re
import threading
import time
import tkinter as tk
import webbrowser

import report
from i18n import CAT, t
from library import ACCENT, BG, FG, FG_DIM, GOOD, LATE, PANEL

from .base import Feature

DAY_DONE_HOUR = 17      # a shutdown from this hour on counts as the end of the day
NEW_DAY_HOUR = 4        # studying past midnight still belongs to yesterday until this hour
NOTE_HOUR = 20          # from now on, prepare tonight's note for the shutdown report
CATCH_UP_MS = 10 * 60_000
APP_PASSWORD_URL = "https://myaccount.google.com/apppasswords"
NOTE_SYSTEM = """You are {name}, a cat who is a warm, honest study buddy for a university student. Write a short note \
(3 to 4 sentences, plain text, no Markdown, no emoji, no greeting line, no sign-off) for their {kind} study report. \
Name one specific thing that went well, compare them only with their own recent days (never with other people), and \
end with one small, concrete suggestion for the {next}. If they barely studied, be kind and practical, never guilt-tripping. \
Write in {language}."""

user32 = ctypes.windll.user32


class ReportFeature(Feature):
    id = "report"
    name_key = "feat_report"
    default_on = True    # sends nothing until addresses and an app password are set

    def start(self):
        self.sending = False
        self.note = None          # (day, study seconds when written, text) for the shutdown report
        self.asking = False
        self.app.root.protocol("WM_SAVE_YOURSELF", self.on_shutdown)
        self.app.root.after(60_000, self.loop)

    # ---------- settings

    def cfg(self):
        s = self.app.settings
        return {"to": s.get("report_to", ""), "from": s.get("report_from", ""),
                "daily": s.get("report_daily", True), "weekly": s.get("report_weekly", True),
                "monthly": s.get("report_monthly", True)}

    def ready(self):
        c = self.cfg()
        return self.on and c["to"] and c["from"] and report.load_password() and self.app.feature("focus").on

    def sent(self):
        return self.app.settings.setdefault("report_sent", {"day": {}, "week": [], "month": []})

    def mark(self, kind, key, study=0, sent=True):
        s = self.sent()
        if kind == "day":
            s["day"][key] = study
            for old in sorted(s["day"])[:-14]:
                del s["day"][old]
        else:
            s[kind] = (s[kind] + [key])[-12:]
        if sent:
            self.app.settings["report_last"] = {"what": kind, "key": key, "at": time.time()}
        self.app.save()

    def menu_items(self, menu):
        menu.add_command(label=t("menu_report"), command=self.open)

    def open(self):
        self.show("main", lambda: ReportWindow(self))

    # ---------- what's due

    def due(self, now=None, at_shutdown=False):
        """[(kind, first, last)] reports to send now."""
        now = now or dt.datetime.now()
        c, sent, out = self.cfg(), self.sent(), []
        today = now.date()
        if c["daily"]:
            if at_shutdown and now.hour >= DAY_DONE_HOUR:
                candidates = [today]
            elif now.hour >= NEW_DAY_HOUR or at_shutdown:
                candidates = [today - dt.timedelta(days=1)]
            else:
                candidates = [today - dt.timedelta(days=2)]
            for day in candidates:
                if day.isoformat() not in sent["day"]:
                    out.append(("day", day, day))
        if not at_shutdown and now.hour >= NEW_DAY_HOUR:
            if c["weekly"]:
                first, last = report.week_of(today - dt.timedelta(days=7))
                if first.isoformat() not in sent["week"]:
                    out.append(("week", first, last))
            if c["monthly"]:
                first, last = report.month_of(today.replace(day=1) - dt.timedelta(days=1))
                if first.isoformat()[:7] not in sent["month"]:
                    out.append(("month", first, last))
        return out

    def key(self, kind, first):
        return first.isoformat()[:7] if kind == "month" else first.isoformat()

    # ---------- building and sending

    def build(self, kind, first, last, note=None):
        data = report.collect(self.app, first, last)
        if not report.has_activity(data):
            return None, data
        if kind == "day":
            return report.daily(self.app, first, note=note, data=data), data
        return report.period(self.app, kind, first, last, note=note, data=data), data

    def deliver(self, built, test=False):
        subject, body, summary, highlights = built
        subject += t("rep_test_tag") if test else ""
        c = self.cfg()
        text = "\n".join(highlights) + "\n\n" + summary
        report.send(c["from"], report.load_password(), c["to"], subject, body, text)

    def send_due(self, items, ask_note=True):
        """Send each due report in the background, one after another, with a note from the buddy if possible."""
        if self.sending or not items:
            return
        self.sending = True

        def next_item(rest):
            if not rest:
                self.sending = False
                return
            kind, first, last = rest[0]
            built, data = self.build(kind, first, last)
            if built is None:     # nothing happened that day: remember it, send nothing
                self.mark(kind, self.key(kind, first), data["study"], sent=False)
                return next_item(rest[1:])

            def go(note):
                if note:
                    built2, _ = self.build(kind, first, last, note=note)
                    final = built2 or built
                else:
                    final = built

                def work():
                    try:
                        self.deliver(final)
                        ok, err = True, None
                    except Exception as e:  # network, login... try again next round
                        ok, err = False, e
                    self.app.ui_q.put(("call", lambda: done(ok, err)))

                def done(ok, err):
                    if ok:
                        self.mark(kind, self.key(kind, first), data["study"])
                        self.app.settings.pop("report_error", None)
                        self.app.save()
                        next_item(rest[1:])
                    else:
                        self.app.settings["report_error"] = describe(err)
                        self.app.save()
                        self.sending = False
                threading.Thread(target=work, daemon=True).start()

            if ask_note:
                self.ask_note(kind, built[2], go)
            else:
                go(None)
        next_item(list(items))

    def ask_note(self, kind, summary, then):
        """The buddy's note, or None (then the built-in highlights stand alone)."""
        buddy = self.app.feature("buddy")
        bridge = getattr(buddy, "bridge", None)
        if not (buddy.on and bridge):
            return then(None)
        language = "Simplified Chinese" if self.app.settings["ui_lang"] == "zh" else "English"
        nxt = {"day": "next day", "week": "next week", "month": "next month"}[kind]
        system = NOTE_SYSTEM.format(name=CAT["name"], kind={"day": "daily"}.get(kind, kind + "ly"), next=nxt, language=language)
        bridge.ask(summary, None, lambda r: then(clean(r.get("text")) if r.get("ok") else None), system=system, timeout=120)

    # ---------- timing

    def loop(self):
        try:
            if self.ready():
                self.catch_up()
                self.prepare_note()
        finally:
            self.app.root.after(CATCH_UP_MS, self.loop)

    def catch_up(self):
        self.send_due(self.due())

    def prepare_note(self):
        """After NOTE_HOUR, have tonight's note ready in case the computer is shut down (no time to ask then)."""
        now = dt.datetime.now()
        if now.hour < NOTE_HOUR or self.asking or not self.cfg()["daily"]:
            return
        day = now.date()
        study = report.study_by_day(self.app, day, day)[day][0]
        if self.note and self.note[0] == day and study - self.note[1] < 30 * 60:
            return
        built, _ = self.build("day", day, day)
        if built is None:
            return
        self.asking = True

        def got(text):
            self.asking = False
            if text:
                self.note = (day, study, text)
        self.ask_note("day", built[2], got)

    def on_shutdown(self):
        """Windows is shutting down: send today's report now if it's due (a few seconds at most)."""
        try:
            if not self.ready():
                return
            items = [i for i in self.due(at_shutdown=True) if i[0] == "day"]
            if not items:
                return
            hwnd = user32.GetParent(self.app.root.winfo_id()) or self.app.root.winfo_id()
            user32.ShutdownBlockReasonCreate(hwnd, t("rep_shutdown"))
            try:
                for kind, first, last in items:
                    note = self.note[2] if self.note and self.note[0] == first else None
                    built, data = self.build(kind, first, last, note=note)
                    if built:
                        self.deliver(built)
                    self.mark(kind, self.key(kind, first), data["study"], sent=bool(built))
            finally:
                user32.ShutdownBlockReasonDestroy(hwnd)
        except Exception as e:   # never stand in the way of a shutdown; catch-up tries again at the next start
            self.app.settings["report_error"] = describe(e)
            self.app.save()


def clean(text):
    if not text:
        return None
    text = re.sub(r"[*_#`>]+", "", text).strip()
    return text or None


def describe(err):
    import smtplib
    if isinstance(err, smtplib.SMTPAuthenticationError):
        return t("rep_err_auth")
    return t("rep_err", err=f"{err.__class__.__name__}: {err}"[:160])


# ---------------------------------------------------------------- setup window

class ReportWindow:
    def __init__(self, feature):
        self.feature, self.app = feature, feature.app
        app = self.app
        f = lambda size, bold=False: app.font("Microsoft YaHei UI", size)
        top = self.top = tk.Toplevel(app.root)
        top.title(t("rep_title"))
        top.configure(bg=BG)
        top.attributes("-topmost", True)
        top.resizable(False, False)
        top.bind("<Escape>", lambda e: top.destroy())
        s = app.scale
        body = tk.Frame(top, bg=BG)
        body.pack(fill="both", expand=True, padx=int(18 * s), pady=int(14 * s))
        tk.Label(body, text=t("rep_hint"), bg=BG, fg=FG_DIM, font=f(9), justify="left",
                 wraplength=int(460 * s)).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        c = feature.cfg()
        self.to_var = tk.StringVar(value=c["to"])
        self.from_var = tk.StringVar(value=c["from"])
        self.pw_var = tk.StringVar()
        have_pw = bool(report.load_password())

        def entry(r, key, var, show=None, hint=None):
            tk.Label(body, text=t(key), bg=BG, fg=FG, font=f(10)).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 12))
            box = tk.Frame(body, bg=BG)
            box.grid(row=r, column=1, sticky="w", pady=4)
            e = tk.Entry(box, textvariable=var, width=30, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=f(11),
                         show=show or "")
            e.pack(side="left", ipady=3)
            if hint:
                tk.Label(box, text=hint, bg=BG, fg=FG_DIM, font=f(9)).pack(side="left", padx=(8, 0))
            return e
        entry(1, "rep_to", self.to_var)
        entry(2, "rep_from", self.from_var)
        entry(3, "rep_password", self.pw_var, show="•", hint=t("rep_password_saved") if have_pw else None)
        link = tk.Label(body, text=t("rep_get_password"), bg=BG, fg=ACCENT, cursor="hand2", font=f(9))
        link.grid(row=4, column=1, sticky="w")
        link.bind("<Button-1>", lambda e: webbrowser.open(APP_PASSWORD_URL))

        self.checks = {}
        row = tk.Frame(body, bg=BG)
        row.grid(row=5, column=1, sticky="w", pady=(10, 4))
        for key in ("daily", "weekly", "monthly"):
            var = tk.BooleanVar(value=c[key])
            self.checks[key] = var
            lbl = tk.Label(row, bg=BG, fg=ACCENT, cursor="hand2", font=f(10))
            lbl.pack(side="left", padx=(0, 14))

            def draw(lbl=lbl, var=var, key=key):
                lbl.configure(text=("☑ " if var.get() else "☐ ") + t(f"rep_{key}"))
            lbl.bind("<Button-1>", lambda e, var=var, draw=draw: (var.set(not var.get()), draw()))
            draw()

        buttons = tk.Frame(body, bg=BG)
        buttons.grid(row=6, column=0, columnspan=2, sticky="w", pady=(14, 4))
        for key, cmd, color in (("rep_save", self.save, ACCENT), ("rep_test", self.test, GOOD)):
            b = tk.Label(buttons, text=t(key), bg=PANEL, fg=color, padx=12, pady=4, cursor="hand2", font=f(10))
            b.pack(side="left", padx=(0, 10))
            b.bind("<Button-1>", lambda e, cmd=cmd: cmd())
        self.status = tk.Label(body, text="", bg=BG, fg=FG_DIM, font=f(9), justify="left", wraplength=int(460 * s))
        self.status.grid(row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.show_status()
        if not feature.app.feature("focus").on:
            self.status.configure(text=t("rep_need_focus"), fg=LATE)

    def show_status(self):
        s = self.app.settings
        if s.get("report_error"):
            self.status.configure(text=s["report_error"], fg=LATE)
        elif s.get("report_last"):
            last = s["report_last"]
            when = dt.datetime.fromtimestamp(last["at"]).strftime("%m-%d %H:%M")
            self.status.configure(text=t("rep_last", what=t(f"rep_kind_{last['what']}"), period=last["key"], when=when), fg=FG_DIM)
        elif not self.feature.ready():
            self.status.configure(text=t("rep_not_set"), fg=FG_DIM)

    def save(self):
        s = self.app.settings
        s["report_to"] = self.to_var.get().strip()
        s["report_from"] = self.from_var.get().strip()
        for key, var in self.checks.items():
            s[f"report_{key}"] = var.get()
        pw = self.pw_var.get().strip()
        if pw:
            report.save_password(s["report_from"], pw)
            self.pw_var.set("")
        self.app.save()
        self.status.configure(text=t("rep_saved"), fg=GOOD)

    def test(self):
        """Send today so far, right now, marked as a test (the built-in note: no waiting for Claude)."""
        self.save()
        if not self.feature.ready():
            self.status.configure(text=t("rep_not_set"), fg=LATE)
            return
        self.status.configure(text=t("rep_sending"), fg=FG_DIM)
        day = dt.date.today()
        built = report.daily(self.app, day)

        def work():
            try:
                self.feature.deliver(built, test=True)
                result = (t("rep_sent_ok", to=self.feature.cfg()["to"]), GOOD)
            except Exception as e:
                result = (describe(e), LATE)
            self.app.ui_q.put(("call", lambda: self.top.winfo_exists() and self.status.configure(text=result[0], fg=result[1])))
        threading.Thread(target=work, daemon=True).start()
