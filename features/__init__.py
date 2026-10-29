"""Popper's features. This list sets their order in the right-click menu, in Settings and in the journal.

To add a feature, copy _template.py, then add its class here.
"""

from .focus import FocusFeature
from .journal import JournalFeature
from .library import LibraryFeature
from .review import ReviewFeature
from .todos import TodosFeature

FEATURES = [ReviewFeature, TodosFeature, FocusFeature, LibraryFeature, JournalFeature]
