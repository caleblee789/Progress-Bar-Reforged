"""Qt font measurement helpers shared by progress-bar dialogs and delegates."""

from __future__ import annotations

from typing import Any


def horizontal_advance(metrics: Any, text: Any) -> int:
    """Measure text with the active font, with a small stub-safe fallback."""

    value = str(text or "")
    measure = getattr(metrics, "horizontalAdvance", None)
    if not callable(measure):
        measure = getattr(metrics, "width", None)
    if callable(measure):
        try:
            return max(0, int(measure(value)))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    # Only headless tests reach this path; live Qt always supplies font metrics.
    return len(value) * 8


def widget_text_width(widget: Any, text: Any, padding: int = 0, minimum: int = 0) -> int:
    metrics_getter = getattr(widget, "fontMetrics", None)
    metrics = metrics_getter() if callable(metrics_getter) else None
    return max(minimum, horizontal_advance(metrics, text) + padding)
