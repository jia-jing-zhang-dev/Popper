"""Study reports by email: what a day, week or month of studying looked like, sent from your own Gmail.

`collect` gathers the numbers (study time from focus_activity, words, tasks, pomodoros, library, goals, the
journal reflection); `daily`/`period` turn them into an email (subject, HTML, and a plain summary that the
study buddy reads to write its note). Highlights compare you with your own past days, never with anyone else.
Sending goes through Gmail's SMTP with an app password kept in Windows Credential Manager (`save_password`).
Nothing personal lives in this file: the addresses are in settings.json.
"""

import ctypes
import datetime as dt
import html
import smtplib
import time
from ctypes import wintypes
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from i18n import CAT, t

SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465
CRED_TARGET = "DesktopStudyCats/gmail-app-password"
MIN_DAY = 5 * 60          # a day with less than this (study + other) and nothing else done gets no report

# email colours (light, as most mail apps show a white page)
INK, DIM, LINE, PAPER = "#1f2430", "#6b7280", "#e5e7eb", "#f7f8fa"
STUDY, OTHER, ACCENT = "#2fa36b", "#e07a6a", "#3b82c4"


# ---------------------------------------------------------------- dates and numbers

def day_start(day):
    return dt.datetime.combine(day, dt.time()).timestamp()


def weekday(day):
    return t("rep_wd").split(",")[day.weekday()]


def fmt_day(day):
    return t("rep_date", wd=weekday(day), mon=t("rep_mon").split(",")[day.month - 1], m=day.month, d=day.day)


def fmt_month(day):
    return t("rep_month", name=t("rep_months").split(",")[day.month - 1], y=day.year, m=day.month)


def dur(seconds):
    minutes = int(round(seconds / 60))
    h, m = divmod(minutes, 60)
    return t("lib_hm", h=h, m=m) if h else t("lib_m", m=m)


def clock(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M")


def week_of(day):
    """Monday..Sunday containing `day`."""
    start = day - dt.timedelta(days=day.weekday())
    return start, start + dt.timedelta(days=6)


def month_of(day):
    start = day.replace(day=1)
    nxt = (start + dt.timedelta(days=32)).replace(day=1)
    return start, nxt - dt.timedelta(days=1)


# ---------------------------------------------------------------- gathering

def table_exists(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def split(log, totals):
    """(study, other) seconds the way every report counts them: time in this app itself isn't study here.
    collect() and study_by_day() must agree, or a day's report looks like it keeps gaining study and is
    sent again and again (it was, on 2026-11-09)."""
    totals = {k: v for k, v in totals.items() if k != "app:popper"}
    return log.split(totals)


def study_by_day(app, first, last):
    """{date: (study seconds, other seconds)} for each day first..last."""
    log = app.feature("focus").log
    out, day = {}, first
    while day <= last:
        out[day] = split(log, log.by_key(day_start(day), day_start(day) + 86400))
        day += dt.timedelta(days=1)
    return out


def collect(app, first, last):
    """Everything a report for the days first..last (inclusive) shows."""
    db = app.vocab.db
    start, end = day_start(first), day_start(last) + 86400
    log = app.feature("focus").log
    rules = log.rules()
    totals = log.by_key(start, end)
    keys = {"study": {}, "other": {}}
    for key, seconds in totals.items():
        cat = log.category(key, rules)
        if cat == "study" and key != "app:popper":
            keys["study"][key] = seconds
        elif cat not in ("study", "ignore"):
            keys["other"][key] = seconds
    hours = [[0.0, 0.0] for _ in range(24)]
    first_study = last_study = None
    for minute, key, seconds in db.execute("SELECT minute, key, seconds FROM focus_activity WHERE minute >= ? AND minute < ? "
                                           "ORDER BY minute", (int(start // 60), int(end // 60))):
        cat = log.category(key, rules)
        if cat == "ignore":
            continue
        ts = minute * 60
        hours[dt.datetime.fromtimestamp(ts).hour][0 if cat == "study" else 1] += seconds
        if cat == "study":
            first_study = first_study if first_study is not None else ts
            last_study = ts + 60
    words = db.execute("SELECT word, trans FROM words WHERE added >= ? AND added < ? ORDER BY added", (start, end)).fetchall()
    tasks = db.execute("SELECT text, COALESCE(spent, 0) AS spent FROM todos WHERE done = 1 AND done_at >= ? AND done_at < ? "
                       "ORDER BY done_at", (start, end)).fetchall()
    goals_done = db.execute("SELECT title FROM goals WHERE done = 1 AND done_at >= ? AND done_at < ?", (start, end)).fetchall()
    today = dt.date.today()
    goals_open = []
    for row in db.execute("SELECT title, deadline FROM goals WHERE done = 0 AND deadline IS NOT NULL AND deadline != ''"):
        try:
            left = (dt.date.fromisoformat(row["deadline"]) - max(today, last)).days
        except ValueError:
            continue
        if 0 <= left <= 14:
            goals_open.append((row["title"], left))
    goals_open.sort(key=lambda g: g[1])
    pomos = (db.execute("SELECT COUNT(*), COALESCE(SUM(minutes), 0) FROM pomodoros WHERE end >= ? AND end < ?",
                        (start, end)).fetchone() if table_exists(db, "pomodoros") else (0, 0))
    library = 0.0
    for r in db.execute("SELECT start, end FROM library_sessions WHERE start < ? AND COALESCE(end, ?) > ?", (end, time.time(), start)):
        library += max(0.0, min(r["end"] or time.time(), end) - max(r["start"], start))
    reflections = [(d, app.journal.reflection(d)) for d in days(first, last)]
    return {
        "first": first, "last": last,
        "study": sum(keys["study"].values()), "other": sum(keys["other"].values()),
        "study_keys": sorted(keys["study"].items(), key=lambda kv: -kv[1]),
        "other_keys": sorted(keys["other"].items(), key=lambda kv: -kv[1]),
        "hours": hours, "first_study": first_study, "last_study": last_study,
        "words": [(w["word"], w["trans"] or "") for w in words],
        "tasks": [(r["text"], r["spent"]) for r in tasks], "goals_done": [g["title"] for g in goals_done],
        "goals_open": goals_open, "pomos": pomos[0], "pomo_minutes": pomos[1], "library": library,
        "reflections": [(d, text) for d, text in reflections if text and text.strip()],
        "per_day": study_by_day(app, first, last),
    }


def days(first, last):
    out, day = [], first
    while day <= last:
        out.append(day)
        day += dt.timedelta(days=1)
    return out


def has_activity(data):
    return data["study"] + data["other"] >= MIN_DAY or data["words"] or data["tasks"] or data["pomos"]


# ---------------------------------------------------------------- highlights (the built-in note)

def label(key):
    from focus import label_of
    return label_of(key)


def daily_highlights(app, data):
    day = data["first"]
    before = study_by_day(app, day - dt.timedelta(days=7), day - dt.timedelta(days=1))
    studied = [s for s, _ in before.values() if s >= 60]
    avg = sum(studied) / len(studied) if studied else 0
    same_day = before.get(day - dt.timedelta(days=7), (0, 0))[0]
    s = data["study"]
    out = []
    if s >= 3 * 3600:
        out.append(t("rep_n_great", d=dur(s)))
    elif s >= 600:
        out.append(t("rep_n_ok", d=dur(s)))
    else:
        out.append(t("rep_n_none"))
    if avg and abs(s - avg) >= 600:
        out.append(t("rep_n_vs_avg_up" if s > avg else "rep_n_vs_avg_down", d=dur(abs(s - avg))))
    if same_day >= 60 and abs(s - same_day) >= 600:
        out.append(t("rep_n_vs_last_up" if s > same_day else "rep_n_vs_last_down", d=dur(abs(s - same_day)), wd=weekday(day)))
    if data["study_keys"]:
        out.append(t("rep_n_focus", app=label(data["study_keys"][0][0])))
    if data["other_keys"] and data["other_keys"][0][1] >= 1800:
        key, sec = data["other_keys"][0]
        out.append(t("rep_n_slip", app=label(key), d=dur(sec)))
    out += goal_lines(data)
    return out


def period_highlights(app, data, prev, kind):
    per = [(d, s) for d, (s, _) in sorted(data["per_day"].items())]
    studied = [(d, s) for d, s in per if s >= 600]
    out = [t("rep_n_days", n=len(studied), total=len(per), d=dur(data["study"]))]
    if studied:
        best = max(studied, key=lambda x: x[1])
        out.append(t("rep_n_best", day=fmt_day(best[0]), d=dur(best[1])))
    if prev and abs(data["study"] - prev) >= 1800:
        out.append(t("rep_n_prev_up" if data["study"] > prev else "rep_n_prev_down", d=dur(abs(data["study"] - prev)),
                     unit=t(f"rep_unit_{kind}")))
    if data["other_keys"] and data["other_keys"][0][1] >= 3 * 3600:
        key, sec = data["other_keys"][0]
        out.append(t("rep_n_slip", app=label(key), d=dur(sec)))
    out += goal_lines(data)
    return out


def goal_lines(data):
    return [t("rep_n_goal_today", title=title) if left == 0 else t("rep_n_goal", title=title, n=left)
            for title, left in data["goals_open"][:2]]


def summary_text(kind, data, highlights):
    """A plain account of the numbers for the study buddy's note (no titles of windows, only app/site names)."""
    lines = [f"Report: {kind}, {data['first']} to {data['last']}",
             f"Studied: {round(data['study'] / 60)} min; not studying while at the computer: {round(data['other'] / 60)} min"]
    if kind == "day" and data["first_study"]:
        lines.append(f"Study from {clock(data['first_study'])} to {clock(data['last_study'])}")
    if kind != "day":
        lines.append("Per day (min): " + ", ".join(f"{d.isoformat()} {round(s / 60)}" for d, (s, _) in sorted(data["per_day"].items())))
    lines.append("Studied in: " + ", ".join(f"{label(k)} {round(s / 60)} min" for k, s in data["study_keys"][:6]))
    if data["other_keys"]:
        lines.append("Other time in: " + ", ".join(f"{label(k)} {round(s / 60)} min" for k, s in data["other_keys"][:4]))
    lines.append(f"Pomodoros: {data['pomos']}; new words: {len(data['words'])}; tasks done: {len(data['tasks'])}")
    if data["tasks"]:
        lines.append("Tasks done: " + "; ".join(text for text, _ in data["tasks"][:10]))
    if data["goals_open"]:
        lines.append("Deadlines: " + "; ".join(f"{g} in {n} days" for g, n in data["goals_open"][:4]))
    lines.append("Facts noticed: " + " ".join(highlights))
    return "\n".join(lines)


# ---------------------------------------------------------------- HTML

def esc(text):
    return html.escape(str(text))


def section(title, body):
    return (f'<tr><td style="padding:18px 24px 4px;font:600 15px Segoe UI,Arial,sans-serif;color:{INK}">{esc(title)}</td></tr>'
            f'<tr><td style="padding:4px 24px 8px;font:14px Segoe UI,Arial,sans-serif;color:{INK}">{body}</td></tr>')


def stat_row(stats):
    cells = "".join(
        f'<td style="padding:10px 8px;text-align:center;background:{PAPER};border-radius:8px">'
        f'<div style="font:600 20px Segoe UI,Arial,sans-serif;color:{color}">{esc(value)}</div>'
        f'<div style="font:12px Segoe UI,Arial,sans-serif;color:{DIM}">{esc(name)}</div></td><td style="width:6px"></td>'
        for name, value, color in stats)
    return f'<table cellspacing="0" cellpadding="0" style="width:100%"><tr>{cells}</tr></table>'


def bar_rows(items, total, color):
    """[(label, seconds)] as rows with a bar each."""
    if not items:
        return f'<span style="color:{DIM}">{esc(t("rep_none"))}</span>'
    top = max(s for _, s in items) or 1
    rows = "".join(
        f'<tr><td style="padding:3px 8px 3px 0;white-space:nowrap;font-size:13px">{esc(name)}</td>'
        f'<td style="width:60%"><div style="background:{color};height:10px;border-radius:5px;width:{max(2, int(100 * s / top))}%"></div></td>'
        f'<td style="padding-left:8px;white-space:nowrap;font-size:13px;color:{DIM}">{esc(dur(s))}</td></tr>'
        for name, s in items)
    return f'<table cellspacing="0" cellpadding="0" style="width:100%">{rows}</table>'


def timeline(hours):
    """24 hour columns: green for study, red for other time, height by minutes."""
    cells = []
    for h, (s, o) in enumerate(hours):
        sh, oh = int(36 * min(s, 3600) / 3600), int(36 * min(o, 3600) / 3600)
        blank = 36 - sh - oh
        cells.append(
            f'<td style="vertical-align:bottom;padding:0 1px">'
            f'<div style="height:{blank}px"></div>'
            + (f'<div style="height:{oh}px;background:{OTHER}"></div>' if oh else "")
            + (f'<div style="height:{sh}px;background:{STUDY}"></div>' if sh else "")
            + f'<div style="height:2px;background:{LINE}"></div></td>')
    ticks = "".join(f'<td style="font-size:10px;color:{DIM};text-align:center">{h if h % 3 == 0 else ""}</td>' for h in range(24))
    legend = (f'<div style="font-size:12px;color:{DIM};margin-top:4px"><span style="color:{STUDY}">■</span> {esc(t("rep_study"))} '
              f'&nbsp; <span style="color:{OTHER}">■</span> {esc(t("rep_other"))}</div>')
    return (f'<table cellspacing="0" cellpadding="0" style="width:100%;table-layout:fixed"><tr>{"".join(cells)}</tr>'
            f'<tr>{ticks}</tr></table>{legend}')


def mix(a, b, k):
    """The colour k (0..1) of the way from hex colour a to b."""
    ca, cb = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * k):02x}" for x, y in zip(ca, cb))


def calendar(per_day, first):
    """A month as a heat map (Monday first)."""
    top = max([s for s, _ in per_day.values()] + [3600])
    cells = ['<td></td>'] * first.weekday()
    for day, (s, _) in sorted(per_day.items()):
        level = 0.2 + 0.8 * min(1, s / top) if s >= 60 else 0
        bg = mix(PAPER, STUDY, level)
        fg = "#ffffff" if level > 0.55 else INK
        cells.append(f'<td style="background:{bg};color:{fg};text-align:center;padding:6px 0;border-radius:6px;font-size:12px">'
                     f'{day.day}<div style="font-size:10px">{esc(round(s / 3600, 1)) if s >= 60 else ""}</div></td>')
    rows, week = [], []
    for c in cells:
        week.append(c)
        if len(week) == 7:
            rows.append(week)
            week = []
    if week:
        rows.append(week + ['<td></td>'] * (7 - len(week)))
    head = "".join(f'<td style="font-size:11px;color:{DIM};text-align:center">{esc(w)}</td>' for w in t("rep_wd").split(","))
    body = "".join("<tr>" + "".join(r) + "</tr>" for r in rows)
    return f'<table cellspacing="3" cellpadding="0" style="width:100%;table-layout:fixed"><tr>{head}</tr>{body}</table>'


def page(heading, sub, sections):
    return (f'<!doctype html><html><body style="margin:0;background:{PAPER}">'
            f'<table cellspacing="0" cellpadding="0" style="width:100%;background:{PAPER}"><tr><td align="center" style="padding:20px 8px">'
            f'<table cellspacing="0" cellpadding="0" style="width:100%;max-width:620px;background:#ffffff;border-radius:12px;border:1px solid {LINE}">'
            f'<tr><td style="padding:22px 24px 2px;font:600 20px Segoe UI,Arial,sans-serif;color:{INK}">{esc(heading)}</td></tr>'
            f'<tr><td style="padding:0 24px 6px;font:13px Segoe UI,Arial,sans-serif;color:{DIM}">{esc(sub)}</td></tr>'
            + "".join(sections) +
            f'<tr><td style="padding:16px 24px 20px;font:12px Segoe UI,Arial,sans-serif;color:{DIM};border-top:1px solid {LINE}">'
            f'{esc(t("rep_footer"))}</td></tr></table></td></tr></table></body></html>')


def note_html(note, highlights):
    parts = []
    if note:
        parts.append(f'<div style="background:#eef6ff;border-left:3px solid {ACCENT};padding:10px 12px;border-radius:6px;line-height:1.5">'
                     + "<br>".join(esc(line) for line in note.strip().splitlines() if line.strip()) + "</div>")
    parts.append("<ul style=\"margin:8px 0 0;padding-left:20px;line-height:1.6\">"
                 + "".join(f"<li>{esc(h)}</li>" for h in highlights) + "</ul>")
    return "".join(parts)


def learned_sections(data, word_limit=30):
    out = []
    if data["tasks"] or data["goals_done"]:
        items = [f"✓ {esc(g)}" for g in data["goals_done"]]
        items += [f"✓ {esc(text)}" + (f' <span style="color:{DIM}">· {esc(dur(spent))}</span>' if spent >= 60 else "")
                  for text, spent in data["tasks"][:20]]
        out.append(section(t("rep_tasks_list"), "<br>".join(items)))
    if data["words"]:
        words = " · ".join(f"<b>{esc(w)}</b> <span style=\"color:{DIM}\">{esc(tr[:30])}</span>" for w, tr in data["words"][:word_limit])
        more = len(data["words"]) - word_limit
        out.append(section(t("rep_words_list", n=len(data["words"])), words + (f" … +{more}" if more > 0 else "")))
    if data["goals_open"]:
        out.append(section(t("rep_goals"), "<br>".join(
            esc(t("rep_n_goal_today", title=g) if n == 0 else t("rep_goal_left", title=g, n=n)) for g, n in data["goals_open"][:5])))
    return out


def daily(app, day, note=None, data=None):
    """(subject, html, summary, highlights) for one day."""
    data = data or collect(app, day, day)
    hl = daily_highlights(app, data)
    span = (t("rep_span", start=clock(data["first_study"]), end=clock(data["last_study"]))
            if data["first_study"] else "–")
    stats = [(t("rep_study"), dur(data["study"]), STUDY), (t("rep_other"), dur(data["other"]), OTHER), (t("rep_hours"), span, INK)]
    extra = [(t("rep_pomos"), str(data["pomos"]), ACCENT)] if data["pomos"] else []
    extra += [(t("rep_words"), str(len(data["words"])), ACCENT)] if data["words"] else []
    extra += [(t("rep_library"), dur(data["library"]), ACCENT)] if data["library"] >= 60 else []
    secs = [section(t("rep_note", cat=CAT["name"]), note_html(note, hl)),
            f'<tr><td style="padding:8px 24px">{stat_row(stats)}</td></tr>']
    if extra:
        secs.append(f'<tr><td style="padding:0 24px 4px">{stat_row(extra)}</td></tr>')
    secs.append(section(t("rep_timeline"), timeline(data["hours"])))
    secs.append(section(t("rep_where"), bar_rows([(label(k), s) for k, s in data["study_keys"][:8]], data["study"], STUDY)))
    if data["other_keys"]:
        secs.append(section(t("rep_distract"), bar_rows([(label(k), s) for k, s in data["other_keys"][:5]], data["other"], OTHER)))
    secs += learned_sections(data)
    for _, text in data["reflections"]:
        secs.append(section(t("rep_reflection"), esc(text).replace("\n", "<br>")))
    subject = t("rep_subj_day", cat=CAT["name"], date=fmt_day(day), d=dur(data["study"]))
    body = page(t("rep_h_day", date=fmt_day(day)), CAT["name"], secs)
    return subject, body, summary_text("day", data, hl), hl


def period(app, kind, first, last, note=None, data=None):
    """(subject, html, summary, highlights) for a week or a month."""
    data = data or collect(app, first, last)
    length = (last - first).days + 1
    prev_first = first - dt.timedelta(days=7) if kind == "week" else month_of(first - dt.timedelta(days=1))[0]
    prev_last = first - dt.timedelta(days=1)
    prev = sum(s for s, _ in study_by_day(app, prev_first, prev_last).values())
    hl = period_highlights(app, data, prev, kind)
    studied = [s for s, _ in data["per_day"].values() if s >= 600]
    stats = [(t("rep_study"), dur(data["study"]), STUDY), (t("rep_days_studied"), f"{len(studied)}/{length}", INK),
             (t("rep_avg"), dur(sum(studied) / len(studied)) if studied else "–", INK)]
    extra = [(t("rep_other"), dur(data["other"]), OTHER), (t("rep_pomos"), str(data["pomos"]), ACCENT),
             (t("rep_words"), str(len(data["words"])), ACCENT), (t("rep_tasks"), str(len(data["tasks"])), ACCENT)]
    secs = [section(t("rep_note", cat=CAT["name"]), note_html(note, hl)),
            f'<tr><td style="padding:8px 24px">{stat_row(stats)}</td></tr>',
            f'<tr><td style="padding:0 24px 4px">{stat_row(extra)}</td></tr>']
    if kind == "week":
        secs.append(section(t("rep_by_day"), bar_rows([(fmt_day(d), s) for d, (s, _) in sorted(data["per_day"].items())],
                                                      data["study"], STUDY)))
        heading = t("rep_h_week", start=fmt_day(first), end=fmt_day(last))
        subject = t("rep_subj_week", start=fmt_day(first), end=fmt_day(last), d=dur(data["study"]))
    else:
        secs.append(section(t("rep_calendar"), calendar(data["per_day"], first)))
        heading = t("rep_h_month", month=fmt_month(first))
        subject = t("rep_subj_month", month=fmt_month(first), d=dur(data["study"]))
    secs.append(section(t("rep_where"), bar_rows([(label(k), s) for k, s in data["study_keys"][:10]], data["study"], STUDY)))
    if data["other_keys"]:
        secs.append(section(t("rep_distract"), bar_rows([(label(k), s) for k, s in data["other_keys"][:6]], data["other"], OTHER)))
    secs += learned_sections(data, word_limit=40)
    return subject, page(heading, CAT["name"], secs), summary_text(kind, data, hl), hl


# ---------------------------------------------------------------- sending

def send(sender, password, to, subject, body_html, body_text, timeout=15):
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, sender, to
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=timeout) as smtp:
        smtp.login(sender, password.replace(" ", ""))
        smtp.sendmail(sender, [a.strip() for a in to.split(",") if a.strip()], msg.as_string())


# ---------------------------------------------------------------- Windows Credential Manager

class CREDENTIAL(ctypes.Structure):
    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)), ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR)]


CRED_TYPE_GENERIC, CRED_PERSIST_LOCAL_MACHINE = 1, 2
advapi32 = ctypes.windll.advapi32


def save_password(user, password):
    blob = password.encode("utf-16-le")
    buf = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)
    cred = CREDENTIAL(Type=CRED_TYPE_GENERIC, TargetName=CRED_TARGET, CredentialBlobSize=len(blob),
                      CredentialBlob=ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)), Persist=CRED_PERSIST_LOCAL_MACHINE,
                      UserName=user)
    return bool(advapi32.CredWriteW(ctypes.byref(cred), 0))


def load_password():
    p = ctypes.POINTER(CREDENTIAL)()
    if not advapi32.CredReadW(CRED_TARGET, CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
        return None
    try:
        size = p.contents.CredentialBlobSize
        return ctypes.string_at(p.contents.CredentialBlob, size).decode("utf-16-le")
    finally:
        advapi32.CredFree(p)


def delete_password():
    advapi32.CredDeleteW(CRED_TARGET, CRED_TYPE_GENERIC, 0)
