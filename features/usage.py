"""Claude usage: the plan limits ("5-hour: 52% used, resets in 3 h 49 min") live on the card.

Claude Code's one-shot mode answers `/usage` locally: no model call, nothing taken from the quota,
about two seconds. Popper runs it every few minutes in the background and parses lines like
    Current session: 52% used · resets Nov 1, 7pm (America/New_York)
"""

import datetime as dt
import json
import os
import re
import subprocess
import threading

from buddy import find_claude
from i18n import t

from .base import Feature

REFRESH_MS = 5 * 60_000
LINE_RE = re.compile(r"^Current ([^:\n]+?):\s*(\d+)% used\s*·\s*resets\s+(.+?)\s*(?:\(([^)]+)\))?\s*$", re.M)
CALM, BUSY, CLOSE = "#9aa3b5", "#e0c46c", "#e57373"  # under 50%, 50-80%, 80% and up


def parse_reset(text, tz_name=None, now=None):
    """'Nov 1, 7pm' or 'Nov 1, 7:30pm' -> local datetime, or None."""
    now = now or dt.datetime.now()
    for fmt in ("%b %d, %I%p", "%b %d, %I:%M%p", "%b %d %I%p", "%b %d %I:%M%p"):
        try:
            when = dt.datetime.strptime(text.replace(" ", " ").strip(), fmt).replace(year=now.year)
            break
        except ValueError:
            continue
    else:
        return None
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            when = when.replace(tzinfo=ZoneInfo(tz_name)).astimezone().replace(tzinfo=None)
        except Exception:
            pass  # no tz database: the reset time is taken as local time
    if when < now - dt.timedelta(days=180):  # "Jan 2" seen in late December
        when = when.replace(year=now.year + 1)
    return when


def parse_usage(text):
    """[{"label", "percent", "resets"}] for each limit in `/usage` output, session limit first."""
    limits = []
    for name, percent, reset, tz in LINE_RE.findall(text or ""):
        limits.append({"label": name.strip().lower(), "percent": int(percent), "resets": parse_reset(reset, tz)})
    limits.sort(key=lambda x: x["label"] != "session")
    return limits


def time_left(when):
    if not when:
        return "?"
    minutes = max(0, int((when - dt.datetime.now()).total_seconds() // 60))
    hours, minutes = divmod(minutes, 60)
    if hours >= 48:
        return t("usage_dh", d=hours // 24, h=hours % 24)
    return t("usage_hm", h=hours, m=minutes) if hours else t("usage_m", m=minutes)


class UsageFeature(Feature):
    id = "usage"
    name_key = "feat_usage"
    default_on = False

    def start(self):
        self.limits = None  # None: not read yet or couldn't read
        self.reading = False
        self.every(REFRESH_MS, self.refresh)
        self.app.root.after(3000, lambda: self.on and self.refresh())
        self.app.root.after(1000, self.render_loop)

    def refresh(self):
        if self.reading:
            return
        self.reading = True
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        limits = None
        exe = find_claude()
        if exe:
            try:
                proc = subprocess.run([exe, "-p", "/usage", "--output-format", "json", "--strict-mcp-config"],
                                      cwd=os.path.join(self.app.data_dir), capture_output=True, text=True,
                                      encoding="utf-8", timeout=60, stdin=subprocess.DEVNULL,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
                limits = parse_usage(json.loads(proc.stdout or "{}").get("result", "")) or None
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
        self.app.ui_q.put(("call", lambda: self._got(limits)))

    def _got(self, limits):
        self.reading = False
        self.limits = limits
        self.render()

    def render_loop(self):
        """Every minute: redraw the countdown, or take the badge away when the feature is off."""
        self.render()
        self.app.root.after(60_000, self.render_loop)

    def label(self, limit):
        return t("usage_session") if limit["label"] == "session" else (
            t("usage_week") if "week" in limit["label"] else limit["label"])

    def render(self):
        if not self.on or not self.limits:
            self.app.set_badge("usage", None)
            return
        main = self.limits[0]
        p = main["percent"]
        color = CLOSE if p >= 80 else BUSY if p >= 50 else CALM
        self.app.set_badge("usage", t("usage_badge", percent=p), color, on_click=self.show_detail)

    def show_detail(self):
        if self.limits:
            lines = [t("usage_detail", label=self.label(x), percent=x["percent"], left=time_left(x["resets"]))
                     for x in self.limits]
            self.app.flash("   ".join(lines), ms=5000)
        self.refresh()

    def menu_items(self, menu):
        if not self.limits:
            menu.add_command(label=t("menu_usage_none"), command=self.refresh)
            return
        for x in self.limits:
            menu.add_command(label=t("menu_usage", label=self.label(x), percent=x["percent"],
                                     left=time_left(x["resets"])), command=self.refresh)
