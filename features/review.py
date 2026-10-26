"""Word list and spaced-repetition review of the words you looked up."""

from tkinter import messagebox

import tkinter as tk

from i18n import t
from journal import Line, Section
from vocab import ReviewWindow, VocabWindow

from .base import Feature


class ReviewFeature(Feature):
    id = "review"
    name_key = "feat_review"

    def menu_items(self, menu):
        vocab = self.app.vocab
        menu.add_command(label=t("menu_review", n=vocab.due_count()), command=self.open_review)
        menu.add_command(label=t("menu_vocab", n=vocab.count()), command=self.open_words)
        recent = tk.Menu(menu, tearoff=0)
        items = vocab.recent()
        for item in items:
            recent.add_command(label=f"{item['word']}   {item['trans'][:20]}",
                               command=lambda it=item: self.app.recall(it))
        if not items:
            recent.add_command(label=t("menu_none"), state="disabled")
        menu.add_cascade(label=t("menu_recent"), menu=recent)

    def open_review(self):
        if self.window("review"):
            self.window("review").top.lift()
            return
        items, note = self.app.vocab.due(), ""
        if not items:
            items, note = self.app.vocab.random_pick(), t("review_random")
        if not items:
            messagebox.showinfo(t("review_title"), t("review_empty"), parent=self.app.root)
            return
        self.show("review", lambda: ReviewWindow(self.app, items, note))

    def open_words(self):
        self.show("words", lambda: VocabWindow(self.app))

    def journal_sections(self):
        return [words_section]


def words_section(app, start, end):
    rows = app.vocab.db.execute("SELECT * FROM words WHERE added >= ? AND added < ? ORDER BY added",
                                (start, end)).fetchall()
    if not rows:
        return None
    lines = []
    for r in rows:
        item = app.vocab.to_item(r)
        lines.append(Line(item["word"], note=item["trans"], right=app.pron_text(item),
                          on_click=lambda it=item: app.speak_item(it)))
    return Section(t("j_words"), t("j_words_sum", n=len(rows)), lines, hint=t("j_words_hint"))
