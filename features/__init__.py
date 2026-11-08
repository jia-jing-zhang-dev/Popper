"""Popper's features. This list sets their order in the right-click menu, in Settings and in the journal.

To add a feature, copy _template.py, then add its class here.
"""

from .bond import BondFeature
from .buddy import BuddyFeature
from .focus import FocusFeature
from .journal import JournalFeature
from .library import LibraryFeature
from .pet import PetFeature
from .review import ReviewFeature
from .todos import TodosFeature
from .usage import UsageFeature

FEATURES = [PetFeature, BondFeature, BuddyFeature, ReviewFeature, TodosFeature, FocusFeature, LibraryFeature, JournalFeature,
            UsageFeature]
