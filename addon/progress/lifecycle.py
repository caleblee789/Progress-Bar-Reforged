"""Small, idempotent helpers for registering modern Anki gui_hooks."""

from __future__ import annotations

import logging
from typing import Any, Callable


logger = logging.getLogger(__name__)


def _callbacks(hook: Any) -> list[Callable[..., Any]]:
    """Return registered callbacks across Anki's generated and test hooks.

    Anki 26's generated hook objects expose their callbacks as ``_hooks`` but
    are not iterable.  Older Anki releases and our test doubles use regular
    iterable containers instead.
    """

    callbacks = getattr(hook, "_hooks", hook)
    try:
        return list(callbacks)
    except TypeError:
        return []


def register_once(hook: Any, callback: Callable[..., Any], key: str) -> None:
    """Append a callback once, including after an add-on module reload.

    Marking callbacks lets us avoid duplicated refreshes when the add-on is
    reloaded in development.
    """

    for existing in _callbacks(hook):
        if getattr(existing, "_progress_bar_hook_key", None) == key:
            return
    setattr(callback, "_progress_bar_hook_key", key)
    hook.append(callback)


def unregister(hook: Any, key: str) -> None:
    """Remove callbacks registered by this package when a hook supports it."""

    for callback in _callbacks(hook):
        if getattr(callback, "_progress_bar_hook_key", None) != key:
            continue
        try:
            hook.remove(callback)
        except (AttributeError, ValueError, RuntimeError) as exc:
            logger.debug("Could not unregister Progress Bar hook %s: %s", key, exc)
