"""Long-term goals and dated to-dos with stopwatches."""

from i18n import t
from journal import Line, Section
from library import TodoWindow, fmt_clock, fmt_duration

from .base import Feature


class TodosFeature(Feature):
    id = "todos"
    name_key = "feat_todos"

    def menu_items(self, menu):
        done, total = self.app.todos.progress()
        menu.add_command(label=t("menu_todo", done=done, total=total) if total else t("todo_title"),
                         command=self.open)

    def open(self):
        self.show("todos", lambda: TodoWindow(self.app))

    def journal_sections(self):
        return [tasks_section]


def tasks_section(app, start, end):
    rows = app.todos.db.execute(
        "SELECT todos.*, goals.title AS goal FROM todos LEFT JOIN goals ON goals.id = todos.goal_id "
        "WHERE todos.done=1 AND todos.done_at >= ? AND todos.done_at < ? ORDER BY todos.done_at",
        (start, end)).fetchall()
    if not rows:
        return None
    total = sum(r["spent"] or 0 for r in rows)
    lines = [Line(f"✓ {r['text']}", note=r["goal"] or "", right=fmt_clock(r["spent"]) if r["spent"] else "—",
                  on_double=lambda i=r["id"]: app.todos.reopen(i)) for r in rows]
    summary = t("j_tasks_sum", n=len(rows)) + (f" · {fmt_duration(total)}" if total >= 60 else "")
    return Section(t("j_tasks"), summary, lines, hint=t("j_tasks_hint"))
