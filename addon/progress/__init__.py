"""Progress-domain state and scheduler helpers.

The UI controller imports from this package; it deliberately has no Qt widget
dependencies, which keeps scheduler and persistence behavior testable without
an Anki window.
"""

from .state import ProgressState

__all__ = ["ProgressState"]
