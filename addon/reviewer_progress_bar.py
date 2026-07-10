from __future__ import unicode_literals
import re
import sys
import logging
from typing import Any, Dict, List, Optional, Tuple
from copy import deepcopy
from pathlib import Path
from . import config as addon_config
from .config import (
    Settings,
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _normalize_dimension,
)
from . import history
from .history import HISTORY_PROGRESS_KEY, SessionHistoryDialog
from .ui import progress_bar as progress_ui
from .ui.theme import (
    combo_qss,
    deck_breakdown_qss,
    resolve_theme_tokens,
    settings_dialog_qss,
    shortcut_qss,
    ui_palette,
)

from aqt.qt import *
try:
    from aqt.qt import pyqtSignal  # Qt5
except Exception:  # pragma: no cover - fallback for test stubs
    def pyqtSignal(*_args, **_kwargs):  # type: ignore[override]
        class _DummySignal:
            def connect(self, *_a, **_kw):
                return None

            def emit(self, *_a, **_kw):
                return None

        return _DummySignal()
try:
    from aqt.qt import QTreeWidgetItem
except Exception:
    QTreeWidgetItem = None  # type: ignore[assignment]
from aqt import mw
from aqt.utils import tooltip

import math
import time

from datetime import datetime, timedelta, timezone

from aqt import gui_hooks
from .progress import ProgressState
from .progress.lifecycle import register_once
from .progress import scheduler as progress_scheduler
from .ui.metrics import horizontal_advance, widget_text_width

settings: Settings
config: Dict[str, Any] = {}
_validation_errors: List[str] = []
_logger = logging.getLogger(__name__)
_reported_ui_failures: set[str] = set()


def _report_ui_failure(operation: str, exc: BaseException) -> None:
    """Keep non-fatal Qt fallbacks visible without flooding paint events."""

    if operation in _reported_ui_failures:
        return
    _reported_ui_failures.add(operation)
    _logger.warning("Progress Bar UI fallback in %s: %s", operation, exc, exc_info=True)

# Set up variables

_progress_state = ProgressState()
# Compatibility aliases for third-party callers that historically imported these
# dictionaries. New controller code uses _progress_state directly.
remainCount = _progress_state.remaining
doneCount = _progress_state.completed
totalCount = _progress_state.total
rawRemainCount = _progress_state.raw_remaining
rawDoneCount = _progress_state.raw_completed
rawTotalCount = _progress_state.raw_total
actionableRevCount = _progress_state.actionable_review
actionableLrnCount = _progress_state.actionable_learning
actionableNewCount = _progress_state.actionable_new
buriedRevCount = _progress_state.buried_review
buriedLrnCount = _progress_state.buried_learning
buriedNewCount = _progress_state.buried_new
currDID: Optional[int] = None  # Compatibility mirror; controller state is canonical.
_current_main_window_state: Optional[str] = "deckBrowser"
_warning_active = False
_deck_breakdown_dialog: Optional["DeckBreakdownDialog"] = None
_session_history_dialog: Optional[SessionHistoryDialog] = None
_TODAY_PACE_MIN_CARDS = 5
DONATE_URL = "https://www.buymeacoffee.com/caleblee78f"
DONATE_TOOLTIP = "Donate to support the creator"
DONATE_IMAGE_PATH = Path(__file__).resolve().parent / "assets" / "buy_me_a_coffee.png"
CALEB_ADDONS_MENU_TITLE = "Caleb M. Add-ons Settings"
CALEB_ADDONS_MENU_OBJECT_NAME = "caleb_m_addons_menu"

def __getattr__(name: str):
    if name in {"progressBar", "toggle_shortcut"}:
        return getattr(progress_ui, name)
    if name == "_last_cards_per_minute":
        return _progress_state.last_cards_per_minute
    if name == "_latest_breakdown_rows":
        return _progress_state.latest_breakdown_rows
    if name == "_latest_breakdown_summary":
        return _progress_state.latest_breakdown_summary
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _qt_object_name(widget: Any) -> str:
    getter = getattr(widget, "objectName", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            return ""
    return str(getter or "")


def _qt_menu_title(menu: Any) -> str:
    getter = getattr(menu, "title", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            return ""
    return str(getter or "")


def _qt_action_text(action: Any) -> str:
    text = getattr(action, "text", None)
    if callable(text):
        try:
            return str(text())
        except Exception:
            return ""
    return str(text or getattr(action, "label", ""))


def _menu_actions(menu: Any) -> List[Any]:
    actions_attr = getattr(menu, "actions", None)
    try:
        actions = actions_attr() if callable(actions_attr) else actions_attr
    except Exception:
        actions = []
    return list(actions or [])


def _set_caleb_menu_object_name(menu: Any) -> None:
    setter = getattr(menu, "setObjectName", None)
    if callable(setter):
        try:
            setter(CALEB_ADDONS_MENU_OBJECT_NAME)
        except (AttributeError, RuntimeError, TypeError) as exc:
            _report_ui_failure("set settings menu object name", exc)


def _iter_submenus(menu: Any):
    for submenu in getattr(menu, "submenus", []) or []:
        if submenu is not None:
            yield submenu

    for action in _menu_actions(menu):
        if isinstance(action, tuple) and len(action) >= 2:
            action = action[1]
        menu_getter = getattr(action, "menu", None)
        if not callable(menu_getter):
            continue
        try:
            submenu = menu_getter()
        except Exception:
            submenu = None
        if submenu is not None:
            yield submenu


def _get_caleb_addons_menu(menu_bar: Any):
    existing = getattr(mw, "_caleb_m_addons_menu", None)
    if existing is not None:
        return existing

    for submenu in _iter_submenus(menu_bar):
        if (
            _qt_object_name(submenu) == CALEB_ADDONS_MENU_OBJECT_NAME
            or _qt_menu_title(submenu) == CALEB_ADDONS_MENU_TITLE
        ):
            _set_caleb_menu_object_name(submenu)
            mw._caleb_m_addons_menu = submenu
            return submenu

    add_menu = getattr(menu_bar, "addMenu", None)
    if not callable(add_menu):
        return menu_bar

    submenu = add_menu(CALEB_ADDONS_MENU_TITLE)
    _set_caleb_menu_object_name(submenu)
    mw._caleb_m_addons_menu = submenu
    return submenu


def _install_settings_menu_action() -> None:
    existing = getattr(mw, "_progress_bar_settings_action", None)
    if existing is not None:
        return

    menu_bar = getattr(getattr(mw, "form", None), "menubar", None)
    if menu_bar is None:
        menu_bar_getter = getattr(mw, "menuBar", None)
        menu_bar = menu_bar_getter() if callable(menu_bar_getter) else None
    if menu_bar is None or not hasattr(menu_bar, "addMenu"):
        return

    submenu = _get_caleb_addons_menu(menu_bar)
    for action in _menu_actions(submenu):
        if isinstance(action, tuple) and len(action) >= 2:
            action = action[1]
        if _qt_action_text(action) == "Progress Bar settings":
            mw._progress_bar_settings_action = action
            return

    settings_action = QAction("Progress Bar settings", mw)
    settings_action.triggered.connect(_open_config_dialog)
    submenu.addAction(settings_action)
    mw._progress_bar_settings_action = settings_action

lrn_weight = 1.0
new_weight = 1.0
rev_weight = 1.0


def _notify_validation_errors(errors: List[str]) -> None:
    if not errors:
        return
    message = "Progress Bar settings adjusted:\n" + "\n".join(errors)
    tooltip(message, parent=mw, period=4000)


def _reload_settings(show_messages: bool = False) -> None:
    global settings
    global config
    global _validation_errors
    addon_config.reload_settings(mw, notify=_notify_validation_errors if show_messages else None)
    settings = addon_config.settings
    _validation_errors = list(addon_config.validation_errors)
    config = settings.raw_config
    _update_legacy_exports()
    if _validation_errors and not show_messages:
        print("Progress Bar settings adjusted:\n" + "\n".join(_validation_errors))


def _apply_settings(show_messages: bool = False) -> None:
    _reload_settings(show_messages=show_messages)
    if settings.progress_bar_enabled and mw.col is not None and getattr(mw.col, "db", None) is not None:
        add_info()
    progress_ui.update_toggle_shortcut(toggleProgressBar)
    _reinitialize_progress_bar()
    refresh = globals().get("_refresh_open_theme_surfaces")
    if callable(refresh):
        refresh()


def _update_legacy_exports() -> None:
    """Expose commonly-used config values on the module for compatibility."""

    global progress_bar_enabled
    global maxWidth
    global warnings_enabled
    global time_warning_minutes
    global warning_palette
    global pace_warnings_enabled
    global target_review_minutes
    global daily_target_cards

    progress_bar_enabled = settings.progress_bar_enabled
    maxWidth = settings.max_width
    warnings_enabled = settings.warnings_enabled
    time_warning_minutes = settings.time_warning_minutes
    warning_palette = settings.warning_palette
    pace_warnings_enabled = settings.pace_warnings_enabled
    target_review_minutes = settings.target_review_minutes
    daily_target_cards = settings.daily_target_cards


def _apply_config(new_config: Dict[str, Any]) -> None:
    """Apply the provided configuration values for tests and callers."""

    addon_config.apply_config(mw, new_config)
    _reload_settings(show_messages=False)
    refresh = globals().get("_refresh_open_theme_surfaces")
    if callable(refresh):
        refresh()


_reload_settings(show_messages=True)

PERSISTED_PROGRESS_KEY = "progress_bar_persistent_counts"
_PERSIST_INTERVAL_SECONDS = 15.0


def _current_day_stamp() -> int:
    if mw.col is None:
        return 0
    cutoff = getattr(mw.col.sched, "day_cutoff", None)
    if cutoff is None:
        return 0
    return cutoff // 86400


def _prepare_counts_for_new_profile() -> None:
    _progress_state.reset_for_profile()


def _ensure_persisted_progress_loaded() -> None:
    today = _current_day_stamp()

    if _progress_state.progress_restored and _progress_state.restored_day_stamp == today:
        return

    if _progress_state.progress_restored and _progress_state.restored_day_stamp != today:
        _prepare_counts_for_new_profile()

    if mw.pm is None or mw.col is None:
        return

    profile = getattr(mw.pm, "profile", None)
    if not isinstance(profile, dict):
        _progress_state.progress_restored = True
        _progress_state.restored_day_stamp = today
        return

    stored = profile.get(PERSISTED_PROGRESS_KEY)
    if not isinstance(stored, dict):
        _progress_state.progress_restored = True
        _progress_state.restored_day_stamp = today
        return

    try:
        stored_day = int(stored.get("day"))
    except (TypeError, ValueError, OverflowError):
        stored_day = None
    if stored_day != today:
        profile.pop(PERSISTED_PROGRESS_KEY, None)
        mw.pm.save()
        _progress_state.progress_restored = True
        _progress_state.restored_day_stamp = today
        return

    data = stored.get("data")
    if not isinstance(data, dict):
        profile.pop(PERSISTED_PROGRESS_KEY, None)
        mw.pm.save()
        _progress_state.progress_restored = True
        _progress_state.restored_day_stamp = today
        return

    for did_key, counts in data.items():
        try:
            did = int(did_key)
        except (TypeError, ValueError):
            continue

        if not isinstance(counts, dict):
            continue

        try:
            done = float(counts.get("done", 0.0))
            total = float(counts.get("total", done))
            raw_done = int(counts.get("raw_done", 0))
            raw_total = int(counts.get("raw_total", raw_done))
        except (TypeError, ValueError, OverflowError):
            continue

        if not math.isfinite(done) or not math.isfinite(total):
            continue

        done = max(0.0, done)
        total = max(0.0, total)
        raw_done = max(0, raw_done)
        raw_total = max(0, raw_total)

        if total < done:
            total = done
        if raw_total < raw_done:
            raw_total = raw_done

        doneCount[did] = done
        totalCount[did] = total
        rawDoneCount[did] = raw_done
        rawTotalCount[did] = raw_total

    _progress_state.progress_restored = True
    _progress_state.restored_day_stamp = today


def _persist_progress_snapshot(*, force: bool = False) -> None:
    if mw.pm is None or mw.col is None:
        return

    _ensure_persisted_progress_loaded()

    profile = getattr(mw.pm, "profile", None)
    if not isinstance(profile, dict):
        return

    today = _current_day_stamp()
    snapshot: Dict[str, Dict[str, Any]] = {}

    for did, total in totalCount.items():
        done = doneCount.get(did, 0.0)
        raw_total = rawTotalCount.get(did, 0)
        raw_done = rawDoneCount.get(did, 0)

        if total <= 0 and done <= 0 and raw_total <= 0 and raw_done <= 0:
            continue

        snapshot[str(did)] = {
            "done": done,
            "total": total,
            "raw_done": raw_done,
            "raw_total": raw_total,
        }

    now = time.monotonic()
    persisted_changed = snapshot != _progress_state.last_snapshot
    too_soon = (now - _progress_state.last_persisted_ts) < _PERSIST_INTERVAL_SECONDS

    if not force and too_soon:
        return
    if not persisted_changed and not force:
        return

    if snapshot:
        profile[PERSISTED_PROGRESS_KEY] = {"day": today, "data": snapshot}
    else:
        profile.pop(PERSISTED_PROGRESS_KEY, None)

    deck_tree = mw.col.sched.deck_due_tree()
    deck_ids_for_query: List[int] = []
    for node in deck_tree.children:
        deck_ids_for_query.extend(_collect_deck_ids(node))
    deck_ids_for_query = list(dict.fromkeys(deck_ids_for_query))
    history.update_daily_history(profile, today, deck_ids_for_query, _revlog_stats_between)

    mw.pm.save()
    _progress_state.last_snapshot = snapshot
    _progress_state.last_persisted_ts = now


def add_info():
    # card types: 0=new, 1=lrn, 2=rev, 3=relrn
    # queue types: 0=new, 1=(re)lrn, 2=rev, 3=day (re)lrn,
    #   4=preview, -1=suspended, -2=sibling buried, -3=manually buried

    # revlog types: 0=lrn, 1=rev, 2=relrn, 3=early review
    # positive revlog intervals are in days (rev), negative in seconds (lrn)
    # odue/odid store original due/did when cards moved to filtered deck
    if mw.col is None or getattr(mw.col, "db", None) is None or getattr(mw.col, "sched", None) is None:
        return

    x = (mw.col.sched.day_cutoff - 86400 * settings.no_days) * 1000
    y = (mw.col.sched.day_cutoff - 86400) * 1000
    """Calculate progress using weights and card counts from the sched."""
    # Get studied cards  and true retention stats
    x_new, x_new_pass, x_learn, x_learn_pass, x_flunked, x_passed = mw.col.db.first("""
                select
                sum(case when ease = 1 and type == 0 and lastIvl == 0 then 1 else 0 end), /* xnew agains */
                sum(case when ease > 1 and type == 0 and lastIvl == 0 then 1 else 0 end), /* xnew pass */
                sum(case when ease = 1 and type in (0, 2) and type != 1 and type != 3 then 1 else 0 end), /* xlearn agains */
                sum(case when ease > 1 and type in (0, 2) and type != 1 and type != 3 then 1 else 0 end), /* xlearn pass */
                sum(case when ease = 1 and type in (1, 3) and type != 0 and type != 2 then 1 else 0 end), /* x_flunked */
                sum(case when ease > 1 and type in (1, 3) and type != 0 and type != 2 then 1 else 0 end) /* x_passed */
                from revlog where id between ? and ?""", x, y)
    x_new = x_new or 0
    x_new_pass = x_new_pass or 0

    x_learn = x_learn or 0
    x_learn_pass = x_learn_pass or 0

    x_flunked = x_flunked or 0
    x_passed = x_passed or 0

    """Calculate progress using weights and card counts from the sched."""

    #retention rate for review cards
    tr = (float(x_flunked / (float(max(1, x_passed + x_flunked)))))

    x_learn_agains = float(x_learn / max(1, (x_learn + x_learn_pass)))
    x_new_agains = float(x_new / max(1, (x_new + x_new_pass)))

    global lrn_weight
    global new_weight
    global rev_weight

    lrn_weight = float((1 + (1 * x_learn_agains * settings.lrn_steps)) / 1)
    new_weight = float((1 + (1 * x_new_agains * settings.lrn_steps)) / 1)
    rev_weight = float((1 + (1 * tr * settings.lrn_steps)) / 1)


register_once(gui_hooks.main_window_did_init, add_info, "main_window_did_init")


def initPB() -> None:
    """Initialize and set parameters for progress bar, adding it to the dock."""
    if addon_config.settings is None:
        _reload_settings(show_messages=False)
    if addon_config.settings is None:
        return
    if not settings.progress_bar_enabled:
        return
    progress_ui.init_progress_bar()
    progress_ui.set_click_handler(_open_deck_breakdown_dialog)


def _remove_progress_bar() -> None:
    """Tear down any existing progress bar dock."""
    progress_ui.remove_progress_bar()


def _reinitialize_progress_bar() -> None:
    """Recreate the progress bar with the latest configuration and refresh counts."""
    if not _should_show_progress_bar_for_state(_progress_state.main_window_state):
        _remove_progress_bar()
        return
    progress_ui.reinitialize_progress_bar()
    progress_ui.set_click_handler(_open_deck_breakdown_dialog)
    if settings.progress_bar_enabled and mw.col is not None and getattr(mw.col, "db", None) is not None:
        _ensure_persisted_progress_loaded()
        updateCountsForAllDecks(True)
        updatePB()


def _should_show_progress_bar_for_state(state: Optional[str]) -> bool:
    if not settings.progress_bar_enabled:
        return False
    if state == "profileManager":
        return False
    if settings.display_location == "review":
        return state == "review"
    if state in {"deckBrowser", "overview", "review"}:
        return settings.display_location == "review_and_home"
    return False


def _find_node_by_id(node, deck_id: int):
    if node.deck_id == deck_id:
        return node
    for child in node.children:
        found = _find_node_by_id(child, deck_id)
        if found is not None:
            return found
    return None


def _collect_deck_ids(node) -> List[int]:
    deck_ids = [node.deck_id]
    for child in node.children:
        deck_ids.extend(_collect_deck_ids(child))
    return deck_ids


def _done_counts_by_deck_since(cutoff: int) -> Dict[int, Tuple[int, int, int]]:
    return progress_scheduler.completed_counts_by_deck(mw.col.db, cutoff)


def _queue_counts_for_node(node) -> Tuple[int, int, int, int, int, int]:
    return progress_scheduler.queue_counts_for_node(
        mw.col.db, mw.col.sched, node, _collect_deck_ids
    )


def _revlog_stats_since(cutoff: int, deck_ids: List[int]):
    return progress_scheduler.revlog_stats(mw.col.db, cutoff, None, deck_ids)


def _revlog_stats_between(start: int, end: int, deck_ids: List[int]):
    return progress_scheduler.revlog_stats(mw.col.db, start, end, deck_ids)


def _current_tzinfo():
    tzinfo = (
        datetime.now().astimezone().tzinfo
        if settings.use_system_timezone
        else timezone(timedelta(hours=settings.tz))
    )
    return tzinfo or timezone.utc


def _historical_seconds_per_card(today: int) -> Optional[float]:
    profile = getattr(getattr(mw, "pm", None), "profile", None)
    if not isinstance(profile, dict):
        return None

    total_cards = 0
    total_seconds = 0.0
    for entry in history.read_history_records(profile):
        if int(entry.get("day", 0)) == today:
            continue
        cards = int(entry.get("cards", 0) or 0)
        avg_seconds = float(entry.get("avg_seconds", 0.0) or 0.0)
        if cards <= 0 or avg_seconds <= 0:
            continue
        total_cards += cards
        total_seconds += avg_seconds * cards

    if total_cards <= 0 or total_seconds <= 0:
        return None
    return total_seconds / total_cards


def _pace_estimate_for_today(cards_today: int, seconds_today: int) -> Optional[Tuple[float, str]]:
    if cards_today >= _TODAY_PACE_MIN_CARDS and seconds_today > 0:
        return (max(1.0, float(seconds_today)) / cards_today, "today")

    historical_seconds = _historical_seconds_per_card(_current_day_stamp())
    if historical_seconds and historical_seconds > 0:
        return (historical_seconds, "history")

    return None


def _pace_projection_text(source: str) -> str:
    if source == "today":
        return "Projected time remaining based on today's pace."
    return "Projected time remaining based on previous averages."


def _format_eta_time(seconds_remaining: int, tzinfo) -> str:
    if seconds_remaining <= 0:
        return "N/A"
    now_tz = datetime.now(tz=tzinfo)
    eta_dt = now_tz + timedelta(seconds=seconds_remaining)
    eta_display = eta_dt.strftime("%I:%M %p")
    days_ahead = (eta_dt.date() - now_tz.date()).days
    if days_ahead > 0:
        eta_display = f"{eta_display}+{days_ahead}"
    return eta_display


def _deck_breakdown_for_node(node, cards_per_minute: Optional[float], tzinfo):
    did = node.deck_id
    actionable_new = actionableNewCount.get(did, 0)
    actionable_lrn = actionableLrnCount.get(did, 0)
    actionable_rev = actionableRevCount.get(did, 0)
    buried_new = buriedNewCount.get(did, 0)
    buried_lrn = buriedLrnCount.get(did, 0)
    buried_rev = buriedRevCount.get(did, 0)

    actionable_total = actionable_new + actionable_lrn + actionable_rev
    eta_text = "N/A"
    if cards_per_minute and cards_per_minute > 0 and actionable_total > 0:
        seconds_remaining = int(round((actionable_total / cards_per_minute) * 60))
        eta_text = _format_eta_time(seconds_remaining, tzinfo)

    return {
        "name": getattr(node, "name", str(did)),
        "deck_id": did,
        "actionable": (actionable_new, actionable_lrn, actionable_rev),
        "buried": (buried_new, buried_lrn, buried_rev),
        "eta": eta_text,
        "children": [
            _deck_breakdown_for_node(child, cards_per_minute, tzinfo)
            for child in node.children
        ],
    }


def _update_breakdown_rows(target_nodes, cards_per_minute: Optional[float]) -> None:
    tzinfo = _current_tzinfo()
    _progress_state.latest_breakdown_rows = [
        _deck_breakdown_for_node(node, cards_per_minute, tzinfo) for node in target_nodes
    ]
    _progress_state.latest_breakdown_summary = _build_breakdown_summary(
        _progress_state.latest_breakdown_rows, cards_per_minute, tzinfo
    )
    _refresh_breakdown_dialog()


def _refresh_breakdown_dialog() -> None:
    global _deck_breakdown_dialog
    if _deck_breakdown_dialog is not None:
        try:
            _deck_breakdown_dialog.update_rows(
                _progress_state.latest_breakdown_rows, _progress_state.latest_breakdown_summary
            )
        except RuntimeError:
            _deck_breakdown_dialog = None


def _refresh_open_theme_surfaces(settings_dialog: Optional["ProgressBarConfigDialog"] = None) -> None:
    global _deck_breakdown_dialog
    global _session_history_dialog
    if settings_dialog is not None:
        try:
            settings_dialog.apply_theme()
        except RuntimeError:
            pass
    if _deck_breakdown_dialog is not None:
        try:
            _deck_breakdown_dialog.apply_theme()
        except RuntimeError:
            _deck_breakdown_dialog = None
    if _session_history_dialog is not None:
        try:
            _session_history_dialog.apply_theme()
        except RuntimeError:
            _session_history_dialog = None


def _fit_progress_bar_format(full_text: str, compact_text: str, minimal_text: str) -> str:
    """Choose a label that fits the live progress bar without clipping."""

    bar = progress_ui.progressBar
    if bar is None:
        return full_text
    if getattr(settings, "compact_mode", False):
        return compact_text
    try:
        width_candidates: List[int] = []
        for widget in (bar, getattr(bar, "parentWidget", lambda: None)(), getattr(progress_ui, "progress_dock", None)):
            width_getter = getattr(widget, "width", None)
            if callable(width_getter):
                width_candidates.append(int(width_getter()))
        if getattr(settings, "orientation", None) == Qt.Orientation.Horizontal and getattr(settings, "dock_area", None) in (
            Qt.DockWidgetArea.TopDockWidgetArea,
            Qt.DockWidgetArea.BottomDockWidgetArea,
        ):
            main_width_getter = getattr(mw, "width", None)
            if callable(main_width_getter):
                width_candidates.append(int(main_width_getter()))
        live_width = max([width for width in width_candidates if width > 0], default=0)
        available = max(0, live_width - 16)
        metrics = bar.fontMetrics()
        measure = getattr(metrics, "horizontalAdvance", None)
        if not callable(measure):
            measure = getattr(metrics, "width", None)
        if not callable(measure) or int(measure(full_text)) <= available:
            return full_text
        if int(measure(compact_text)) <= available:
            return compact_text
        return minimal_text
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return full_text


def _open_deck_breakdown_dialog() -> None:
    global _deck_breakdown_dialog

    if _deck_breakdown_dialog is None:
        _deck_breakdown_dialog = DeckBreakdownDialog(mw)
    else:
        try:
            _deck_breakdown_dialog.apply_theme()
        except RuntimeError:
            _deck_breakdown_dialog = DeckBreakdownDialog(mw)

    _deck_breakdown_dialog.request_auto_fit()
    _deck_breakdown_dialog.update_rows(_progress_state.latest_breakdown_rows)
    _deck_breakdown_dialog.show()
    _deck_breakdown_dialog.raise_()
    _deck_breakdown_dialog.activateWindow()


def updatePB():
    # Get studied cards  and true retention stats. TODAY'S VALUES

    # If the progress bar isn't initialized yet, there's nothing to update.
    if progress_ui.progressBar is None:
        return

    a = (mw.col.sched.day_cutoff - 86400) * 1000

    deck_tree = mw.col.sched.deck_due_tree()
    if currDID is None:
        target_nodes = list(deck_tree.children)
    else:
        node = _find_node_by_id(deck_tree, currDID)
        if node is None:
            target_nodes = list(deck_tree.children)
        else:
            target_nodes = [node]

    target_decks = [node.deck_id for node in target_nodes]
    deck_ids_for_query: List[int] = []
    for node in target_nodes:
        deck_ids_for_query.extend(_collect_deck_ids(node))
    deck_ids_for_query = list(dict.fromkeys(deck_ids_for_query))  # preserve order, ensure uniqueness

    stats_today = _revlog_stats_since(a, deck_ids_for_query)
    if stats_today:
        cards, failed, flunked, passed, passed_supermature, flunked_supermature, thetime = stats_today
    else:
        cards = failed = flunked = passed = passed_supermature = flunked_supermature = thetime = 0

    cards = cards or 0
    failed = failed or 0
    flunked = flunked or 0
    passed = passed or 0
    passed_supermature = passed_supermature or 0
    flunked_supermature = flunked_supermature or 0
    thetime = thetime or 0
    try:
        temp_value = (passed / float(passed + flunked)) * 100
        temp = "%0.2f%%" % temp_value
    except ZeroDivisionError:
        temp_value = None
        temp = "N/A"
    try:
        temp_supermature_value = (passed_supermature / float(passed_supermature + flunked_supermature)) * 100
        temp_supermature = "%0.2f%%" % temp_supermature_value
    except ZeroDivisionError:
        temp_supermature_value = None
        temp_supermature = "N/A"
    try:
        again_value = (failed / cards) * 100
        again = "%0.2f%%" % again_value
    except ZeroDivisionError:
        again_value = None
        again = "N/A"

    # Yesterday-only metrics (strict previous day window)
    y_start = (mw.col.sched.day_cutoff - 86400 * 2) * 1000
    y_end = (mw.col.sched.day_cutoff - 86400) * 1000

    stats_yesterday = _revlog_stats_between(y_start, y_end, deck_ids_for_query)
    if stats_yesterday:
        (
            ycards,
            yfailed,
            yflunked,
            ypassed,
            ypassed_supermature,
            yflunked_supermature,
            ythetime,
        ) = stats_yesterday
    else:
        ycards = yfailed = yflunked = ypassed = ypassed_supermature = yflunked_supermature = ythetime = 0

    ycards = ycards or 0
    yfailed = yfailed or 0
    yflunked = yflunked or 0
    ypassed = ypassed or 0
    ypassed_supermature = ypassed_supermature or 0
    yflunked_supermature = yflunked_supermature or 0
    ythetime = ythetime or 0

    try:
        ytemp = "%0.2f%%" % (ypassed / float(ypassed + yflunked) * 100)
    except ZeroDivisionError:
        ytemp = "N/A"
    try:
        ytemp_supermature = "%0.2f%%" % (ypassed_supermature / float(ypassed_supermature + yflunked_supermature) * 100)
    except ZeroDivisionError:
        ytemp_supermature = "N/A"
    try:
        y_again = "%0.2f%%" % ((yfailed / ycards) * 100)
    except ZeroDivisionError:
        y_again = "N/A"

    """Update progress bar range and value with currDID, totalCount[] and doneCount[]"""
    weighted_done = sum(doneCount.get(deck_id, 0.0) for deck_id in target_decks)
    weighted_remain = sum(remainCount.get(deck_id, 0.0) for deck_id in target_decks)
    weighted_total = weighted_done + weighted_remain

    raw_done = sum(rawDoneCount.get(deck_id, 0) for deck_id in target_decks)
    raw_remain = sum(rawRemainCount.get(deck_id, 0) for deck_id in target_decks)
    raw_total = raw_done + raw_remain

    actionable_rev_total = sum(
        actionableRevCount.get(deck_id, 0) for deck_id in target_decks
    )
    actionable_lrn_total = sum(
        actionableLrnCount.get(deck_id, 0) for deck_id in target_decks
    )
    actionable_new_total = sum(
        actionableNewCount.get(deck_id, 0) for deck_id in target_decks
    )
    buried_rev_total = sum(buriedRevCount.get(deck_id, 0) for deck_id in target_decks)
    buried_lrn_total = sum(buriedLrnCount.get(deck_id, 0) for deck_id in target_decks)
    buried_new_total = sum(buriedNewCount.get(deck_id, 0) for deck_id in target_decks)

    actionable_left = (
        actionable_new_total + actionable_lrn_total + actionable_rev_total
    )
    # The remaining total intentionally excludes buried cards; they are surfaced
    # separately in the breakdown. Validation scenario: New 139 (+61 buried),
    # Learning 0, Review 239 (+3 buried) => actionable_left = 139 + 0 + 239 = 378.
    var_diff = actionable_left

    if cards > 0:
        safe_time = max(thetime, 1)
        secspeed_value = safe_time / cards
        secspeed_display = f"{secspeed_value:.02f}"
    else:
        secspeed_value = 0
        secspeed_display = "N/A"

    if ycards > 0:
        safe_ytime = max(ythetime, 1)
        ysecspeed_value = safe_ytime / ycards
        ysecspeed_display = f"{ysecspeed_value:.02f}"
    else:
        ysecspeed_value = 0
        ysecspeed_display = "N/A"

    pace_estimate = _pace_estimate_for_today(int(cards), int(thetime))
    if pace_estimate is not None:
        pace_seconds_per_card, pace_source = pace_estimate
        speed = 60.0 / pace_seconds_per_card
        seconds_remaining = int(round(var_diff * pace_seconds_per_card))
        projection_text = _pace_projection_text(pace_source)
    else:
        speed = 0
        seconds_remaining = 0
        pace_source = ""
        projection_text = "Projected time remaining is unavailable until enough review history is available."

    # Daily goal tracking
    card_goal = max(0, settings.daily_target_cards)
    minute_goal = max(0, settings.target_review_minutes)
    elapsed_minutes = thetime / 60.0
    cards_vs_goal = None
    time_vs_goal = None
    projected_minutes = None
    projected_total_minutes = None

    if card_goal > 0:
        cards_vs_goal = (raw_done, card_goal)
        remaining_cards_goal = max(0, card_goal - raw_done)
    else:
        remaining_cards_goal = None

    if minute_goal > 0:
        time_vs_goal = (elapsed_minutes, minute_goal)
        remaining_minutes_goal = max(0.0, minute_goal - elapsed_minutes)
    else:
        remaining_minutes_goal = None

    if speed > 0:
        projected_minutes = seconds_remaining / 60.0
        projected_total_minutes = elapsed_minutes + projected_minutes
    pace_warning_messages: List[str] = []

    # Time spent today (hours:minutes)
    x = math.floor(thetime / 3600)
    y = math.floor((thetime - (x * 3600)) / 60)

    # Break down remaining into hours/minutes for display
    hrhr = seconds_remaining // 3600
    hrmin = (seconds_remaining % 3600) // 60

    # ETA display using system timezone by default, or the configured offset when overridden
    eta_display = _format_eta_time(seconds_remaining, _current_tzinfo())

    cutoff_seconds = 0
    if mw.col is not None and getattr(mw.col, "sched", None) is not None:
        try:
            cutoff_seconds = max(0, int(round(mw.col.sched.day_cutoff - time.time())))
        except Exception:
            cutoff_seconds = 0

    progress_scale = 1000
    progress_max = int(round(weighted_total * progress_scale))
    progress_value = int(round(weighted_done * progress_scale))

    if progress_max <= 0:
        progress_ui.progressBar.setRange(0, 1)
        progress_ui.progressBar.setValue(1)
    else:
        progress_ui.progressBar.setRange(0, progress_max)
        progress_ui.progressBar.setValue(min(progress_value, progress_max))

    warning_messages: List[str] = []
    warning_summary_parts: List[str] = []
    warning_active = False
    if settings.warnings_enabled:
        if settings.time_warning_minutes > 0 and seconds_remaining > settings.time_warning_minutes * 60:
            warning_active = True
            warning_messages.append(f"Warning: projected time > {settings.time_warning_minutes}m.")
            warning_summary_parts.append(f"time>{settings.time_warning_minutes}m")
        if settings.again_warning_percent > 0 and again_value is not None and again_value >= settings.again_warning_percent:
            warning_active = True
            warning_messages.append(f"Warning: Again rate ≥ {settings.again_warning_percent:.0f}%.")
            warning_summary_parts.append(f"Again≥{settings.again_warning_percent:.0f}%")
        if settings.retention_warning_percent > 0:
            if temp_value is not None and temp_value < settings.retention_warning_percent:
                warning_active = True
                warning_messages.append(f"Warning: true retention < {settings.retention_warning_percent:.0f}%.")
                warning_summary_parts.append(f"Retention<{settings.retention_warning_percent:.0f}%")
            if temp_supermature_value is not None and temp_supermature_value < settings.retention_warning_percent:
                warning_active = True
                warning_messages.append(f"Warning: super-mature retention < {settings.retention_warning_percent:.0f}%.")
                warning_summary_parts.append(f"Super-mature retention<{settings.retention_warning_percent:.0f}%")

    projected_finish_after_cutoff: Optional[int] = None
    if seconds_remaining > 0 and cutoff_seconds > 0:
        projected_finish_after_cutoff = seconds_remaining - cutoff_seconds

    if settings.pace_warnings_enabled:
        if cards_vs_goal is not None:
            done_cards, goal_cards = cards_vs_goal
            if goal_cards > 0 and done_cards < goal_cards and speed > 0 and raw_total > 0:
                projected_cards = done_cards + (seconds_remaining * speed / 60)
                if projected_cards + 1e-6 < goal_cards:
                    warning_active = True
                    pace_warning_messages.append("Warning: projected cards will miss the goal.")
                    warning_summary_parts.append("Cards<goal")
        if time_vs_goal is not None and projected_minutes is not None and minute_goal > 0:
            if elapsed_minutes + projected_minutes < minute_goal - 1e-6:
                warning_active = True
                pace_warning_messages.append("Warning: projected time below target minutes.")
                warning_summary_parts.append("Time<goal")
        if projected_finish_after_cutoff is not None and projected_finish_after_cutoff > 0:
            warning_active = True
            minutes_past = projected_finish_after_cutoff / 60.0
            pace_warning_messages.append(f"Warning: projected finish {minutes_past:.0f}m after today's cutoff.")
            warning_summary_parts.append("ETA>cutoff")


    percent = 100 if raw_total == 0 else (100 * raw_done / raw_total)
    percentdiff = 100 - percent

    tooltip_lines: List[str] = []
    completed_tooltip_lines: List[str] = []
    remaining_tooltip_lines: List[str] = []

    goal_text_parts: List[str] = []
    goal_tooltip_lines: List[str] = []

    if cards_vs_goal is not None:
        done_cards, goal_cards = cards_vs_goal
        progress_pct = 100.0 if goal_cards == 0 else min(100.0, (done_cards / goal_cards) * 100)
        goal_text_parts.append(f"Cards {done_cards}/{goal_cards} ({progress_pct:.0f}%)")
        goal_tooltip_lines.append(
            f"Card goal: {done_cards}/{goal_cards} cards ({progress_pct:.0f}% complete)."
        )
        if remaining_cards_goal is not None:
            goal_tooltip_lines.append(f"Cards remaining to goal: {remaining_cards_goal}.")

    if time_vs_goal is not None:
        elapsed, goal_minutes = time_vs_goal
        progress_pct = 100.0 if goal_minutes == 0 else min(100.0, (elapsed / goal_minutes) * 100)
        goal_text_parts.append(f"Time {elapsed:.0f}/{goal_minutes}m ({progress_pct:.0f}%)")
        goal_tooltip_lines.append(
            f"Time goal: {elapsed:.0f}/{goal_minutes} minutes ({progress_pct:.0f}% complete)."
        )
        if remaining_minutes_goal is not None:
            goal_tooltip_lines.append(f"Minutes remaining to goal: {remaining_minutes_goal:.0f}.")
        if projected_total_minutes is not None:
            pace_label = "today's pace" if pace_source == "today" else "previous averages"
            goal_tooltip_lines.append(f"Projected total time using {pace_label}: {projected_total_minutes:.0f} minutes.")

    if projected_finish_after_cutoff is not None and cutoff_seconds > 0:
        cutoff_delta_minutes = projected_finish_after_cutoff / 60.0
        if projected_finish_after_cutoff > 0:
            goal_tooltip_lines.append(f"Projected to finish {cutoff_delta_minutes:.0f} minutes after today's cutoff.")
        else:
            goal_tooltip_lines.append(f"Projected to finish {abs(cutoff_delta_minutes):.0f} minutes before today's cutoff.")

    mode = getattr(settings, "mode", "stats")
    if mode == "simple":
        output = f"{raw_done}/{raw_total} ({percent:.0f}%)" if settings.show_percent else f"{raw_done}/{raw_total}"
        tooltip_lines.append(
            f"Cards completed: {raw_done} ({percent:.02f}% of today's total)."
        )
        tooltip_lines.append(
            f"Cards remaining: {var_diff:.0f} ({percentdiff:.02f}% of today's session)."
        )
        completed_tooltip_lines.append(
            f"Cards completed: {raw_done} ({percent:.02f}% of today's total)."
        )
        remaining_tooltip_lines.append(
            f"Cards remaining: {var_diff:.0f} ({percentdiff:.02f}% of today's session)."
        )
    elif mode == "time_left":
        output = f"{raw_done}/{raw_total} ({percent:.0f}%)" if settings.show_percent else f"{raw_done}/{raw_total}"
        output += f"     |     {var_diff:.0f} left"
        output += f"     |     {x:02d}:{y:02d} spent"
        tooltip_lines.append(
            f"Cards completed: {raw_done} ({percent:.02f}% of today's total)."
        )
        tooltip_lines.append(
            f"Cards remaining: {var_diff:.0f} ({percentdiff:.02f}% of today's session)."
        )
        tooltip_lines.append(
            f"Time spent reviewing so far today: {x:02d}:{y:02d}."
        )
        completed_tooltip_lines.append(
            f"Cards completed: {raw_done} ({percent:.02f}% of today's total)."
        )
        completed_tooltip_lines.append(
            f"Time spent reviewing so far today: {x:02d}:{y:02d}."
        )
        remaining_tooltip_lines.append(
            f"Cards remaining: {var_diff:.0f} ({percentdiff:.02f}% of today's session)."
        )
        if speed > 0:
            output += f"     |     {hrhr:02d}:{hrmin:02d} more"
            output += f"     |     ETA {eta_display}"
            tooltip_lines.append(projection_text)
            tooltip_lines.append(
                f"Estimated finish time adjusted for your {'system' if settings.use_system_timezone else 'custom'} timezone: {eta_display}."
            )
            remaining_tooltip_lines.append(projection_text)
            remaining_tooltip_lines.append(
                f"Estimated finish time adjusted for your {'system' if settings.use_system_timezone else 'custom'} timezone: {eta_display}."
            )
        else:
            output += "     |     --:-- more"
            output += "     |     ETA N/A"
            tooltip_lines.append(projection_text)
            tooltip_lines.append(
                "Estimated finish time unavailable until enough review history or today's pace is available."
            )
            remaining_tooltip_lines.append(projection_text)
    elif settings.show_number:
        base_displayed = True
        if settings.show_percent:
            output = f"{raw_done} ({percent:.02f}%) done"
            tooltip_lines.append(
                f"Cards completed: {raw_done} ({percent:.02f}% of today's total)."
            )
            completed_tooltip_lines.append(
                f"Cards completed: {raw_done} ({percent:.02f}% of today's total)."
            )
            output += f"     |     {var_diff:.0f} ({percentdiff:.02f}%) left"
            tooltip_lines.append(
                f"Cards remaining: {var_diff:.0f} ({percentdiff:.02f}% of today's session)."
            )
            remaining_tooltip_lines.append(
                f"Cards remaining: {var_diff:.0f} ({percentdiff:.02f}% of today's session)."
            )
        else:
            output = f"{raw_done} done"
            tooltip_lines.append(f"Cards completed so far today: {raw_done}.")
            output += f"     |     {var_diff:.0f} left"
            tooltip_lines.append(f"Cards remaining in the active queues: {var_diff:.0f}.")
            completed_tooltip_lines.append(f"Cards completed so far today: {raw_done}.")
            remaining_tooltip_lines.append(
                f"Cards remaining in the active queues: {var_diff:.0f}."
            )
        if settings.show_yesterday:
            output += f"     |     {secspeed_display} ({ysecspeed_display}) s/card"
            tooltip_lines.append(
                "Seconds per card today (yesterday in parentheses)."
            )
            completed_tooltip_lines.append(
                "Seconds per card today (yesterday in parentheses)."
            )
        else:
            output += f"     |     {secspeed_display} s/card"
            tooltip_lines.append(
                "Average seconds spent per card for the current session."
            )
            completed_tooltip_lines.append(
                "Average seconds spent per card for the current session."
            )
        if settings.show_again:
            if settings.show_yesterday:
                output += f"     |     {again} ({y_again}) Again"
                tooltip_lines.append(
                    "Again answers today (yesterday in parentheses)."
                )
                completed_tooltip_lines.append(
                    "Again answers today (yesterday in parentheses)."
                )
            else:
                output += f"     |     {again} Again"
                tooltip_lines.append("Again answers given during today's reviews.")
                completed_tooltip_lines.append(
                    "Again answers given during today's reviews."
                )
        if settings.show_retention:
            if settings.show_yesterday:
                output += f"     |     {temp} ({ytemp}) Retention"
                tooltip_lines.append(
                    "Today's true retention percentage (yesterday in parentheses)."
                )
                completed_tooltip_lines.append(
                    "Today's true retention percentage (yesterday in parentheses)."
                )
            else:
                output += f"     |     {temp} Retention"
                tooltip_lines.append("Today's true retention percentage.")
                completed_tooltip_lines.append("Today's true retention percentage.")
        if settings.show_super_mature_retention:
            if settings.show_yesterday:
                output += f"     |     {temp_supermature} ({ytemp_supermature}) SMTR"
                tooltip_lines.append(
                    "Super-mature retention rate today (yesterday in parentheses)."
                )
                completed_tooltip_lines.append(
                    "Super-mature retention rate today (yesterday in parentheses)."
                )
            else:
                output += f"     |     {temp_supermature} SMTR"
                tooltip_lines.append("Super-mature retention rate for today's reviews.")
                completed_tooltip_lines.append(
                    "Super-mature retention rate for today's reviews."
                )
        output += f"     |     {x:02d}:{y:02d} spent"
        tooltip_lines.append(
            f"Time spent reviewing so far today: {x:02d}:{y:02d}."
        )
        completed_tooltip_lines.append(
            f"Time spent reviewing so far today: {x:02d}:{y:02d}."
        )
        if goal_text_parts:
            output += "     |     Goals " + " · ".join(goal_text_parts)
        if speed > 0:
            output += f"     |     {hrhr:02d}:{hrmin:02d} more"
            tooltip_lines.append(projection_text)
            remaining_tooltip_lines.append(projection_text)
            output += f"     |     ETA {eta_display}"
            tooltip_lines.append(
                f"Estimated finish time adjusted for your {'system' if settings.use_system_timezone else 'custom'} timezone: {eta_display}."
            )
            remaining_tooltip_lines.append(
                f"Estimated finish time adjusted for your {'system' if settings.use_system_timezone else 'custom'} timezone: {eta_display}."
            )
        else:
            output += "     |     --:-- more"
            tooltip_lines.append(projection_text)
            output += "     |     ETA N/A"
            tooltip_lines.append(
                "Estimated finish time unavailable until enough review history or today's pace is available."
            )
            remaining_tooltip_lines.append(projection_text)
        if settings.show_debug:
            output += f"     |     {new_weight:.02f} New Weight"
            tooltip_lines.append(
                f"Weight applied to new cards when calculating progress: {new_weight:.02f}."
            )
            completed_tooltip_lines.append(
                f"Weight applied to new cards when calculating progress: {new_weight:.02f}."
            )
            output += f"     |     {lrn_weight:.02f} Lrn Weight"
            tooltip_lines.append(
                f"Weight applied to learning cards in the progress formula: {lrn_weight:.02f}."
            )
            completed_tooltip_lines.append(
                f"Weight applied to learning cards in the progress formula: {lrn_weight:.02f}."
            )
            output += f"     |     {rev_weight:.02f} Rev Weight"
            tooltip_lines.append(
                f"Weight applied to review cards in the progress formula: {rev_weight:.02f}."
            )
            completed_tooltip_lines.append(
                f"Weight applied to review cards in the progress formula: {rev_weight:.02f}."
            )
    else:
        output = "Goals " + " · ".join(goal_text_parts) if goal_text_parts else ""

    if goal_tooltip_lines:
        tooltip_lines.extend(goal_tooltip_lines)
        completed_tooltip_lines.extend(goal_tooltip_lines)
        remaining_tooltip_lines.extend(goal_tooltip_lines)

    def _format_breakdown(label: str, actionable: int, buried: int) -> str:
        if buried:
            return f"{label}: {actionable} + {buried}"
        return f"{label}: {actionable} +0"

    breakdown_lines = [
        _format_breakdown("New", actionable_new_total, buried_new_total),
        _format_breakdown("Learning", actionable_lrn_total, buried_lrn_total),
        _format_breakdown("To Review", actionable_rev_total, buried_rev_total),
    ]
    tooltip_lines.extend(breakdown_lines)
    tooltip_lines.append("Due today excludes buried cards (shown as +).")
    remaining_tooltip_lines.extend(breakdown_lines)
    remaining_tooltip_lines.append("Due today excludes buried cards (shown as +).")

    warning_summary_text: Optional[str] = None
    if settings.warnings_enabled or settings.pace_warnings_enabled:
        if warning_summary_parts:
            warning_summary_text = f"Warnings: {', '.join(warning_summary_parts)}"
        else:
            warning_summary_text = "Warnings: None active"
        tooltip_lines.append(warning_summary_text + ".")
        completed_tooltip_lines.append(warning_summary_text + ".")
        remaining_tooltip_lines.append(warning_summary_text + ".")

    all_warning_messages = warning_messages + pace_warning_messages
    if all_warning_messages:
        tooltip_lines.append("")
        tooltip_lines.extend(all_warning_messages)
        completed_tooltip_lines.append("")
        completed_tooltip_lines.extend(all_warning_messages)
        remaining_tooltip_lines.append("")
        remaining_tooltip_lines.extend(all_warning_messages)

    if tooltip_lines:
        default_tooltip = "\n".join(tooltip_lines)
    else:
        default_tooltip = (
            "Progress metrics are hidden. Enable numbers in the add-on settings to view details."
        )

    completed_tooltip = "\n".join(completed_tooltip_lines) if completed_tooltip_lines else default_tooltip
    remaining_tooltip = "\n".join(remaining_tooltip_lines) if remaining_tooltip_lines else default_tooltip
    progress_fraction = 0.0
    if progress_max > 0:
        progress_fraction = min(1.0, max(0.0, progress_value / progress_max))

    if settings.stacked_segments and isinstance(progress_ui.progressBar, progress_ui.SegmentedProgressBar):
        progress_ui.progressBar.setSegmentData(
            actionable_new_total,
            actionable_lrn_total,
            actionable_rev_total,
            progress_fraction,
        )

    format_output = output
    if warning_summary_text and output:
        format_output += f"     |     {warning_summary_text}"
    elif warning_summary_text:
        format_output = warning_summary_text
    if warning_active:
        format_output = (format_output + " ⚠").strip() if format_output else "⚠"
    compact_output = f"{raw_done}/{raw_total} ({percent:.0f}%)  |  {var_diff:.0f} left"
    if speed > 0:
        compact_output += f"  |  ETA {eta_display}"
    if warning_active:
        compact_output += "  ⚠"
    minimal_output = f"{raw_done}/{raw_total}  |  {var_diff:.0f} left"
    if warning_active:
        minimal_output += "  ⚠"
    format_output = _fit_progress_bar_format(format_output, compact_output, minimal_output)
    progress_ui.progressBar.setFormat(format_output)
    global _warning_active
    if warning_active != _warning_active:
        progress_ui.apply_bar_style(warning_active)
        _warning_active = warning_active

    progress_ui.update_progress_tooltips(
        default_tooltip,
        completed_text=completed_tooltip,
        remaining_text=remaining_tooltip,
        fraction=progress_fraction,
    )

    _progress_state.last_cards_per_minute = speed if speed > 0 else None
    _update_breakdown_rows(target_nodes, _progress_state.last_cards_per_minute)

    _persist_progress_snapshot()

    progress_ui.nmApplyStyle()


def setScrollingPB() -> None:
    """Make progress bar in waiting style if the state is resetRequired (happened after editing cards.)"""
    if progress_ui.progressBar is None:
        return
    progress_ui.set_scrolling_bar_state()


#used to calculate var_diff
def calcProgress(rev: int, lrn: int, new: int) -> float:
    ret = 0.0
    if settings.include_rev:
        ret += rev * rev_weight
    if settings.include_lrn:
        ret += lrn * lrn_weight
    if settings.include_new or (settings.include_new_after_revs and rev == 0):
        ret += new * new_weight
    return ret


def calcRawCounts(rev: int, lrn: int, new: int) -> int:
    return rev + lrn + new


def updateCountsForAllDecks(updateTotal: bool) -> None:
    """
    Update counts.
    After adding, editing or deleting cards (afterStateChange hook), updateTotal should be set to True to update
    totalCount[] based on doneCount[] and remainCount[]. No card should have been answered before this hook is
    triggered, so the change in remainCount[] should be caused by editing collection and therefore goes into
    totalCount[].
    When the user answer a card (showQuestion hook), updateTotal should be set to False to update doneCount[] based on
    totalCount[] and remainCount[]. No change to collection should have been made before this hook is
    triggered, so the change in remainCount[] should be caused by answering cards and therefore goes into
    doneCount[].
    In the later case, remainCount[] may still increase based on the weights of New, Lrn and Rev cards (see comments
    of "Calculation weights" above), in which case totalCount[] may still get updated based on forceForward setting.
    :param updateTotal: True for afterStateChange hook, False for showQuestion hook
    """

    if mw.col is None:
        return

    today_cutoff = (mw.col.sched.day_cutoff - 86400) * 1000
    done_by_deck = _done_counts_by_deck_since(today_cutoff)

    for node in mw.col.sched.deck_due_tree().children:
        updateCountsForTree(node, updateTotal, done_by_deck)


def updateCountsForTree(node, updateTotal: bool, done_by_deck: Dict[int, Tuple[int, int, int]]) -> None:
    did = node.deck_id
    (
        rev_count,
        lrn_count,
        new_count,
        buried_rev,
        buried_lrn,
        buried_new,
    ) = _queue_counts_for_node(node)

    rev_done = 0
    lrn_done = 0
    new_done = 0
    for deck_id in _collect_deck_ids(node):
        rev_add, lrn_add, new_add = done_by_deck.get(deck_id, (0, 0, 0))
        rev_done += rev_add
        lrn_done += lrn_add
        new_done += new_add

    actionableRevCount[did] = rev_count
    actionableLrnCount[did] = lrn_count
    actionableNewCount[did] = new_count
    buriedRevCount[did] = buried_rev
    buriedLrnCount[did] = buried_lrn
    buriedNewCount[did] = buried_new

    remain = calcProgress(rev_count, lrn_count, new_count)
    raw_remain = calcRawCounts(rev_count, lrn_count, new_count)

    updateCountsForDeck(did, remain, raw_remain, rev_done, lrn_done, new_done, updateTotal)

    for child in node.children:
        updateCountsForTree(child, updateTotal, done_by_deck)


def updateCountsForDeck(
    did: int,
    remain: float,
    raw_remain: int,
    rev_done: int,
    lrn_done: int,
    new_done: int,
    updateTotal: bool,
) -> None:
    remainCount[did] = remain
    rawRemainCount[did] = raw_remain

    raw_done_total = rev_done + lrn_done + new_done
    rawDoneCount[did] = raw_done_total

    doneCount[did] = calcProgress(rev_done, lrn_done, new_done)

    if updateTotal and settings.force_forward:
        totalCount[did] = max(totalCount.get(did, 0.0), doneCount[did] + remainCount[did])
        rawTotalCount[did] = max(rawTotalCount.get(did, 0), rawDoneCount[did] + rawRemainCount[did])
    else:
        totalCount[did] = doneCount[did] + remainCount[did]
        rawTotalCount[did] = rawDoneCount[did] + rawRemainCount[did]


def afterStateChangeCallBack(state: str, oldState: str) -> None:
    global currDID
    global _current_main_window_state

    _current_main_window_state = state
    _progress_state.main_window_state = state

    if not settings.progress_bar_enabled:
        _remove_progress_bar()
        return

    if state == "resetRequired":
        if settings.scrolling_bar_when_editing:
            setScrollingPB()
        return
    elif state == "deckBrowser":
        currDID = None
        _progress_state.current_deck_id = None
        if not _should_show_progress_bar_for_state(state):
            _remove_progress_bar()
            return
        # initPB() has to be here, since objects are not prepared yet when the add-on is loaded.
        if not progress_ui.progressBar and settings.progress_bar_enabled:
            initPB()
    elif state == "profileManager":
        _remove_progress_bar()
        currDID = None
        _progress_state.current_deck_id = None
        return
    else:  # "overview" or "review"
        if not _should_show_progress_bar_for_state(state):
            _remove_progress_bar()
            return
        # showInfo("mw.col.decks.current()['id'])= %d" % mw.col.decks.current()['id'])
        if not progress_ui.progressBar:
            initPB()
        currDID = mw.col.decks.current()['id']
        _progress_state.current_deck_id = currDID

    # showInfo("updateCountsForAllDecks(True), currDID = %d" % (currDID if currDID else 0))
    _ensure_persisted_progress_loaded()
    updateCountsForAllDecks(True)  # see comments at updateCountsForAllDecks()
    updatePB()


def showQuestionCallBack() -> None:
    # showInfo("updateCountsForAllDecks(False), currDID = %d" % (currDID if currDID else 0))
    if not settings.progress_bar_enabled or mw.col is None:
        return
    updateCountsForAllDecks(False)  # see comments at updateCountsForAllDecks()
    updatePB()


def _on_state_did_change(new_state: str, old_state: str) -> None:
    """Modern Anki hook adapter for main-window state changes."""

    afterStateChangeCallBack(new_state, old_state)


def _on_reviewer_did_show_question(*_args: Any) -> None:
    """Modern Anki hook adapter; the displayed card is not needed here."""

    showQuestionCallBack()


# The package supports Anki 2.1.49+, whose generated gui_hooks API replaces
# the legacy string-based addHook callbacks.
register_once(gui_hooks.state_did_change, _on_state_did_change, "state_did_change")
register_once(
    gui_hooks.reviewer_did_show_question,
    _on_reviewer_did_show_question,
    "reviewer_did_show_question",
)


def _on_profile_did_open() -> None:
    _prepare_counts_for_new_profile()


def _on_profile_will_close() -> None:
    global currDID
    global _current_main_window_state
    global _deck_breakdown_dialog
    global _session_history_dialog

    try:
        _persist_progress_snapshot(force=True)
    except Exception as err:
        print(f"Progress Bar could not persist profile state: {err}")

    for dialog in (_deck_breakdown_dialog, _session_history_dialog):
        if dialog is not None:
            try:
                dialog.close()
            except (AttributeError, RuntimeError):
                pass
    _deck_breakdown_dialog = None
    _session_history_dialog = None
    _remove_progress_bar()
    currDID = None
    _current_main_window_state = "profileManager"
    _progress_state.current_deck_id = None
    _progress_state.main_window_state = "profileManager"
    _prepare_counts_for_new_profile()


register_once(gui_hooks.profile_did_open, _on_profile_did_open, "profile_did_open")
register_once(gui_hooks.profile_will_close, _on_profile_will_close, "profile_will_close")


def _on_theme_did_change(*_args) -> None:
    if getattr(settings, "theme", "auto") != "auto":
        return
    _apply_settings(show_messages=False)


_theme_did_change_hook = getattr(gui_hooks, "theme_did_change", None)
if _theme_did_change_hook is not None:
    register_once(_theme_did_change_hook, _on_theme_did_change, "theme_did_change")


def _current_theme_choice() -> str:
    current_settings = getattr(addon_config, "settings", None)
    if current_settings is not None:
        return getattr(current_settings, "theme", "auto")
    return str(config.get("theme", "auto"))


def _ui_tokens(theme: Optional[str] = None):
    return resolve_theme_tokens(theme or _current_theme_choice())


def _ui_palette(theme: Optional[str] = None) -> Dict[str, str]:
    return ui_palette(theme or _current_theme_choice())


def _open_donation_page() -> None:
    QDesktopServices.openUrl(QUrl(DONATE_URL))


class SettingRow(QWidget):
    """Uniform row with title, microcopy, and a control."""

    def __init__(
        self,
        title: str,
        description: str,
        control: QWidget,
        palette: Dict[str, str],
        tooltip_text: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._base_style = ""
        self._title_text = title
        self._description_text = description
        self._palette = palette
        self._highlighted = False
        self._tip_btn = None

        layout = QHBoxLayout()
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            f"font-weight: 600; font-size: 13px; color: {palette['section_header_text']}; margin-bottom: 2px;"
        )
        text_col.addWidget(self.title_label)

        self.description_label = QLabel(description)
        self.description_label.setWordWrap(True)
        self.description_label.setStyleSheet(f"color: {palette['helper_text']}; font-size: 12px; line-height: 1.4;")
        text_col.addWidget(self.description_label)

        text_col.addStretch()
        layout.addLayout(text_col, 1)

        control_layout = QHBoxLayout()
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(6)

        control_layout.addWidget(control, 1)

        if tooltip_text:
            tip_btn = QToolButton()
            self._tip_btn = tip_btn
            tip_btn.setText("ⓘ")
            tip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            tip_btn.setToolTip(tooltip_text)
            tip_btn.setStyleSheet(
                f"QToolButton {{ border: none; font-weight: 700; color: {palette['muted_text']}; font-size: 14px; padding: 4px; }}"
                f"QToolButton:hover {{ color: {palette['focus_border']}; }}"
            )
            control_layout.addWidget(tip_btn)

        layout.addLayout(control_layout, 0)

        self.setLayout(layout)
        self._base_style = f"border-bottom: 1px solid {self._palette['row_divider']};"
        self.setStyleSheet(self._base_style)
        self.control = control

    def apply_theme(self, palette: Dict[str, str]) -> None:
        self._palette = palette
        self.title_label.setStyleSheet(
            f"font-weight: 600; font-size: 13px; color: {palette['section_header_text']}; margin-bottom: 2px;"
        )
        self.description_label.setStyleSheet(f"color: {palette['helper_text']}; font-size: 12px; line-height: 1.4;")
        if self._tip_btn is not None:
            self._tip_btn.setStyleSheet(
                f"QToolButton {{ border: none; font-weight: 700; color: {palette['muted_text']}; font-size: 14px; padding: 4px; }}"
                f"QToolButton:hover {{ color: {palette['focus_border']}; }}"
            )
        self._base_style = f"border-bottom: 1px solid {self._palette['row_divider']};"
        self.set_highlighted(self._highlighted)

    def matches(self, query: str) -> bool:
        if not query:
            return True
        haystack = f"{self._title_text} {self._description_text}".lower()
        return query.lower() in haystack

    def set_highlighted(self, on: bool) -> None:
        self._highlighted = bool(on)
        if not on:
            self.setStyleSheet(self._base_style)
            return
        self.setStyleSheet(
            self._base_style
            + f"\nbackground: {self._palette['tab_selected_bg']}; border-radius: 6px; border: 1px solid {self._palette['focus_border']};"
        )


class ColorPickerField(QWidget):
    """Color picker widget with visual preview and text input."""

    colorChanged = pyqtSignal(str)

    def __init__(self, default_color: str, palette: Dict[str, str], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._palette = palette
        self._default = default_color or ""
        self._current_color = self._default

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Color preview button
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(40, 32)
        self._color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._color_btn.setToolTip("Click to pick a color")
        self._color_btn.clicked.connect(self._pick_color)
        self._update_color_preview()

        # Text input
        self._text_edit = QLineEdit()
        self._text_edit.setPlaceholderText("e.g., #ffffff or aliceblue")
        self._text_edit.setStyleSheet(
            f"""
            QLineEdit {{
                padding: 6px 8px;
                border: 1px solid {palette['field_border']};
                border-radius: 5px;
                background: {palette['field_bg']};
                color: {palette['primary_text']};
            }}
            QLineEdit:focus {{
                border-color: {palette['focus_border']};
                box-shadow: {palette['focus_shadow']};
            }}
            """
        )
        self._text_edit.textChanged.connect(self._on_text_changed)
        self._text_edit.setPlaceholderText("Color name or hex (e.g., #3399cc)")

        # Clear button
        self._clear_btn = QToolButton()
        self._clear_btn.setText("✕")
        self._clear_btn.setToolTip("Clear color (use theme default)")
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.clicked.connect(self._clear_color)

        layout.addWidget(self._color_btn)
        layout.addWidget(self._text_edit, 1)
        layout.addWidget(self._clear_btn)

        self.setLayout(layout)
        self._update_text_from_color()

    def _update_color_preview(self) -> None:
        """Update the color preview button."""
        from .config import _to_qcolor
        color = _to_qcolor(self._current_color) if self._current_color else QColor(128, 128, 128)
        if not color.isValid():
            color = QColor(128, 128, 128)
        
        # Create a simple color preview
        style = f"""
            QPushButton {{
                background-color: {color.name()};
                border: 2px solid {self._palette['field_border']};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                border-color: {self._palette['focus_border']};
            }}
        """
        self._color_btn.setStyleSheet(style)

    def _pick_color(self) -> None:
        """Open native color picker dialog."""
        from .config import _to_qcolor
        initial_color = _to_qcolor(self._current_color) if self._current_color else QColor(51, 153, 204)
        if not initial_color.isValid():
            initial_color = QColor(51, 153, 204)
        
        color = QColorDialog.getColor(initial_color, self, "Pick a color")
        if color.isValid():
            self.set_color(color.name())
            self.colorChanged.emit(self.value())

    def _on_text_changed(self, text: str) -> None:
        """Handle text input changes."""
        from .config import _to_qcolor
        text = text.strip()
        color = _to_qcolor(text) if text else None
        
        if text and color and color.isValid():
            self._current_color = text
            self._update_color_preview()
            self.colorChanged.emit(self.value())
        elif not text:
            self._current_color = ""
            self._update_color_preview()
            self.colorChanged.emit(self.value())

    def _clear_color(self) -> None:
        """Clear the color to use theme default."""
        self._text_edit.clear()
        self._current_color = ""
        self._update_color_preview()
        self.colorChanged.emit(self.value())

    def _update_text_from_color(self) -> None:
        """Update text field from current color."""
        self._text_edit.setText(self._current_color)

    def value(self) -> str:
        """Get the current color value."""
        return self._current_color or ""

    def set_color(self, color: str) -> None:
        """Set the color value."""
        self._current_color = color or ""
        self._update_text_from_color()
        self._update_color_preview()
        self.colorChanged.emit(self.value())


class _ShortcutRecorderFilter(QObject):
    """Keep QKeySequenceEdit from capturing keys after incidental focus."""

    def __init__(self, owner: "ShortcutField") -> None:
        super().__init__(owner)
        self._owner = owner

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        event_type = event.type()
        event_types = getattr(QEvent, "Type", QEvent)
        if event_type == getattr(event_types, "MouseButtonPress", object()):
            self._owner._arm_recording()
            return False
        if event_type == getattr(event_types, "FocusIn", object()) and not self._owner._recording_armed:
            self._owner._disarm_recording(refocus_web=False)
            return True
        if event_type == getattr(event_types, "FocusOut", object()):
            self._owner._recording_armed = False
            return False
        return False


class ShortcutField(QWidget):
    """Cross-platform shortcut editor with conflict detection and reset."""

    shortcutChanged = pyqtSignal(str)

    def __init__(self, default_shortcut: str, palette: Dict[str, str], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._palette = palette
        self._default = default_shortcut
        self._last_conflict: Optional[str] = None
        self._programmatic_update = False
        self._recording_armed = False
        self.setObjectName("shortcutField")

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        field_row = QHBoxLayout()
        field_row.setContentsMargins(0, 0, 0, 0)
        field_row.setSpacing(6)

        self._editor = QKeySequenceEdit()
        self._editor.setObjectName("shortcutRecorder")
        self._editor.setClearButtonEnabled(True)
        if hasattr(self._editor, "setMaximumSequenceLength"):
            try:
                self._editor.setMaximumSequenceLength(1)
            except (AttributeError, RuntimeError, TypeError) as exc:
                _report_ui_failure("set shortcut sequence length", exc)
        click_focus = getattr(getattr(Qt, "FocusPolicy", Qt), "ClickFocus", None)
        if click_focus is not None and hasattr(self._editor, "setFocusPolicy"):
            self._editor.setFocusPolicy(click_focus)
        self._recorder_filter = _ShortcutRecorderFilter(self)
        if hasattr(self._editor, "installEventFilter"):
            self._editor.installEventFilter(self._recorder_filter)
        self._editor.keySequenceChanged.connect(self._on_changed)

        self._record_hint = QLabel("Click, then press keys.")

        self._reset_btn = QToolButton()
        self._reset_btn.setObjectName("shortcutResetButton")
        self._reset_btn.setText("Reset to default")
        self._reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset_btn.clicked.connect(self.reset_to_default)

        field_row.addWidget(self._editor, 1)
        field_row.addWidget(self._reset_btn)

        layout.addLayout(field_row)
        layout.addWidget(self._record_hint)

        self._warning_label = QLabel("")
        self._warning_label.setObjectName("shortcutConflictLabel")
        layout.addWidget(self._warning_label)

        self.setLayout(layout)
        self.apply_theme(palette)
        self.reset_to_default()

    def apply_theme(self, palette: Optional[Dict[str, str]] = None) -> None:
        tokens = _ui_tokens()
        self._palette = palette or tokens.as_palette()
        self._editor.setStyleSheet(shortcut_qss(tokens))
        self._apply_editor_palette()
        self._reset_btn.setStyleSheet(settings_dialog_qss(tokens))
        self._record_hint.setStyleSheet(f"color: {self._palette['muted_text']};")
        self._warning_label.setStyleSheet(f"color: {self._palette['danger_text']}; font-weight: 600;")
        self.update()

    def value(self) -> str:
        text = self._editor.keySequence().toString()
        return text or self._default

    def reset_to_default(self) -> None:
        self._set_editor_sequence(self._default)
        self._update_warning(None)
        self.shortcutChanged.emit(self.value())

    def set_shortcut(self, shortcut: str) -> None:
        target = shortcut or self._default
        self._set_editor_sequence(target)
        self._update_warning(self._detect_conflict(QKeySequence(target)))
        self.shortcutChanged.emit(self.value())

    def _on_changed(self, sequence: QKeySequence) -> None:
        conflict = self._detect_conflict(sequence)
        self._update_warning(conflict)
        self.shortcutChanged.emit(self.value())
        if not self._programmatic_update and not sequence.isEmpty():
            self._disarm_recording(refocus_web=False)

    def _set_editor_sequence(self, shortcut: str) -> None:
        self._programmatic_update = True
        try:
            self._editor.setKeySequence(QKeySequence(shortcut))
        finally:
            self._programmatic_update = False

    def _arm_recording(self) -> None:
        self._recording_armed = True
        self._record_hint.setText("Press shortcut keys.")

    def _disarm_recording(self, refocus_web: bool = False) -> None:
        self._recording_armed = False
        self._record_hint.setText("Click, then press keys.")
        if hasattr(self._editor, "clearFocus"):
            try:
                self._editor.clearFocus()
            except (AttributeError, RuntimeError) as exc:
                _report_ui_failure("clear shortcut focus", exc)
        if refocus_web and hasattr(mw, "web") and hasattr(mw.web, "setFocus"):
            try:
                mw.web.setFocus()
            except (AttributeError, RuntimeError) as exc:
                _report_ui_failure("restore reviewer focus", exc)

    def _apply_editor_palette(self) -> None:
        palette_cls = globals().get("QPalette")
        color_cls = globals().get("QColor")
        if palette_cls is None or color_cls is None or not hasattr(self._editor, "setPalette"):
            return
        try:
            widget_palette = palette_cls()
            roles = getattr(palette_cls, "ColorRole", palette_cls)
            role_colors = {
                "Base": self._palette["field_bg"],
                "Window": self._palette["field_bg"],
                "Button": self._palette["field_bg"],
                "Text": self._palette["primary_text"],
                "WindowText": self._palette["primary_text"],
                "ButtonText": self._palette["primary_text"],
                "Highlight": self._palette["table_selection_bg"],
                "HighlightedText": self._palette["table_selection_text"],
            }
            groups = getattr(palette_cls, "ColorGroup", None)
            group_names = ("Active", "Inactive", "Disabled") if groups is not None else ()
            if group_names:
                for group_name in group_names:
                    group = getattr(groups, group_name, None)
                    if group is None:
                        continue
                    for role_name, color in role_colors.items():
                        role = getattr(roles, role_name, None)
                        if role is None:
                            continue
                        resolved_color = color
                        if group_name == "Disabled":
                            if role_name in {"Base", "Window", "Button"}:
                                resolved_color = self._palette["disabled_bg"]
                            elif role_name in {"Text", "WindowText", "ButtonText", "HighlightedText"}:
                                resolved_color = self._palette["disabled_text"]
                        widget_palette.setColor(group, role, color_cls(resolved_color))
            else:
                for role_name, color in role_colors.items():
                    role = getattr(roles, role_name, None)
                    if role is not None:
                        widget_palette.setColor(role, color_cls(color))
            self._editor.setPalette(widget_palette)
            if hasattr(self._editor, "setAutoFillBackground"):
                self._editor.setAutoFillBackground(True)
            if hasattr(self._editor, "findChildren"):
                for child in self._editor.findChildren(QWidget):
                    if hasattr(child, "setPalette"):
                        child.setPalette(widget_palette)
                    if hasattr(child, "setAutoFillBackground"):
                        child.setAutoFillBackground(True)
        except (AttributeError, RuntimeError, TypeError) as exc:
            _report_ui_failure("apply shortcut palette", exc)

    def _detect_conflict(self, sequence: QKeySequence) -> Optional[str]:
        if sequence.isEmpty():
            return "Click to record a shortcut."

        candidates = list(mw.findChildren(QAction))
        shortcut_class = globals().get("QShortcut")
        if shortcut_class is not None:
            candidates.extend(mw.findChildren(shortcut_class))

        for action in candidates:
            if action is progress_ui.toggle_shortcut:
                continue
            try:
                shortcut_getter = getattr(action, "shortcut", None)
                if not callable(shortcut_getter):
                    shortcut_getter = getattr(action, "key", None)
                other = shortcut_getter() if callable(shortcut_getter) else None
            except Exception:
                continue
            if not other or other.isEmpty():
                continue
            if other.matches(sequence) == QKeySequence.SequenceMatch.ExactMatch:
                text_value = getattr(action, "text", None)
                text = text_value() if callable(text_value) else text_value
                object_name = getattr(action, "objectName", lambda: "")()
                text = text or object_name or "another shortcut"
                return f"Conflicts with {text}."
        return None

    def _update_warning(self, warning: Optional[str]) -> None:
        self._last_conflict = warning
        if warning:
            self._warning_label.setText(warning)
        else:
            self._warning_label.setText("")

    def has_conflict(self) -> bool:
        return bool(self._last_conflict)


BREAKDOWN_INFO_TEXT = (
    "Due today counts exclude buried siblings. Buried cards due today are listed separately. "
    "ETAs use today's pace after 5 cards or previous averages before then."
)
_ETA_SORT_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*([AP]M)(?:\+(\d+))?$", re.IGNORECASE)


def _qt_user_role(offset: int = 0):
    role_container = getattr(Qt, "ItemDataRole", Qt)
    role = getattr(role_container, "UserRole", 32)
    try:
        return int(role) + offset
    except Exception:
        return int(getattr(role, "value", 32)) + offset


_BREAKDOWN_COUNTS_ROLE = _qt_user_role(0)
_BREAKDOWN_MUTED_ROLE = _qt_user_role(1)
_BREAKDOWN_TOTAL_ROLE = _qt_user_role(2)
_BREAKDOWN_CHILD_ROLE = _qt_user_role(3)
_CSS_RGBA_RE = re.compile(
    r"^rgba\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*([0-9]*\.?[0-9]+)\s*\)$",
    re.IGNORECASE,
)


def _normalize_counts(counts: Any) -> Tuple[int, int, int]:
    if not isinstance(counts, (list, tuple)):
        return (0, 0, 0)
    values = list(counts)[:3]
    while len(values) < 3:
        values.append(0)
    normalized: List[int] = []
    for value in values:
        try:
            normalized.append(max(0, int(value or 0)))
        except (TypeError, ValueError):
            normalized.append(0)
    return normalized[0], normalized[1], normalized[2]


def _count_total(counts: Any) -> int:
    return sum(_normalize_counts(counts))


def _qcolor_from_css(value: str):
    text = str(value or "").strip()
    match = _CSS_RGBA_RE.match(text)
    if not match:
        return QColor(text)

    red = max(0, min(255, int(match.group(1))))
    green = max(0, min(255, int(match.group(2))))
    blue = max(0, min(255, int(match.group(3))))
    alpha = max(0.0, min(1.0, float(match.group(4))))
    color = QColor(red, green, blue)
    if hasattr(color, "setAlphaF"):
        color.setAlphaF(alpha)
    elif hasattr(color, "setAlpha"):
        color.setAlpha(int(round(alpha * 255)))
    return color


def _format_counts_compact(counts: Any) -> str:
    new, lrn, rev = _normalize_counts(counts)
    total = new + lrn + rev
    return f"{total}  N {new} · L {lrn} · R {rev}"


def _format_counts_accessible(label: str, counts: Any) -> str:
    new, lrn, rev = _normalize_counts(counts)
    total = new + lrn + rev
    return f"{label}: {total}; New {new}, Learning {lrn}, Review {rev}"


def _card_word(count: int) -> str:
    return "card" if count == 1 else "cards"


def _summary_finish_display(eta_text: str) -> str:
    return eta_text if eta_text and eta_text != "N/A" else "No ETA yet"


def _breakdown_summary_title(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "Today"
    if len(rows) == 1:
        name = str(rows[0].get("name", "")).strip()
        return f"{name} Today" if name else "Today"
    return "All Decks Today"


def _format_summary_main(summary: Dict[str, Any]) -> str:
    actionable_total = _count_total(summary.get("actionable", (0, 0, 0)))
    buried_total = _count_total(summary.get("buried", (0, 0, 0)))
    finish = _summary_finish_display(str(summary.get("eta", "N/A") or "N/A"))
    return (
        f"{actionable_total} {_card_word(actionable_total)} due today · "
        f"{buried_total} buried · Finish estimate: {finish}"
    )


def _format_summary_clipboard(summary: Dict[str, Any]) -> str:
    new, lrn, rev = _normalize_counts(summary.get("actionable", (0, 0, 0)))
    buried_new, buried_lrn, buried_rev = _normalize_counts(summary.get("buried", (0, 0, 0)))
    lines = [
        str(summary.get("title", "Today")),
        _format_summary_main(summary),
        f"New {new} · Learning {lrn} · Review {rev}",
        f"Buried: {buried_new + buried_lrn + buried_rev} (New {buried_new} · Learning {buried_lrn} · Review {buried_rev})",
    ]
    return "\n".join(lines)


def _build_breakdown_summary(
    rows: List[Dict[str, Any]],
    cards_per_minute: Optional[float] = None,
    tzinfo=None,
) -> Dict[str, Any]:
    actionable = [0, 0, 0]
    buried = [0, 0, 0]
    for row in rows:
        row_actionable = _normalize_counts(row.get("actionable", (0, 0, 0)))
        row_buried = _normalize_counts(row.get("buried", (0, 0, 0)))
        for index, value in enumerate(row_actionable):
            actionable[index] += value
        for index, value in enumerate(row_buried):
            buried[index] += value

    actionable_total = sum(actionable)
    eta_text = "N/A"
    if cards_per_minute and cards_per_minute > 0 and actionable_total > 0:
        eta_tzinfo = tzinfo or _current_tzinfo()
        seconds_remaining = int(round((actionable_total / cards_per_minute) * 60))
        eta_text = _format_eta_time(seconds_remaining, eta_tzinfo)
    elif len(rows) == 1:
        eta_text = str(rows[0].get("eta", "N/A") or "N/A")

    summary = {
        "title": _breakdown_summary_title(rows),
        "actionable": tuple(actionable),
        "buried": tuple(buried),
        "eta": eta_text,
    }
    summary["main"] = _format_summary_main(summary)
    summary["clipboard"] = _format_summary_clipboard(summary)
    return summary


def _clone_breakdown_row(row: Dict[str, Any], children: List[Dict[str, Any]]) -> Dict[str, Any]:
    cloned = dict(row)
    cloned["children"] = children
    return cloned


def _filter_breakdown_rows(rows: List[Dict[str, Any]], hide_empty: bool) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        children = _filter_breakdown_rows(list(row.get("children", [])), hide_empty)
        actionable_total = _count_total(row.get("actionable", (0, 0, 0)))
        if not hide_empty or actionable_total > 0 or children:
            filtered.append(_clone_breakdown_row(row, children))
    return filtered


def _eta_sort_key(eta_text: Any) -> Tuple[int, int]:
    text = str(eta_text or "N/A").strip()
    match = _ETA_SORT_RE.match(text)
    if not match:
        return (9999, 9999)

    hour = int(match.group(1))
    minute = int(match.group(2))
    suffix = match.group(3).upper()
    day_offset = int(match.group(4) or 0)
    hour %= 12
    if suffix == "PM":
        hour += 12
    return (day_offset, hour * 60 + minute)


def _sort_breakdown_rows(rows: List[Dict[str, Any]], mode: str) -> List[Dict[str, Any]]:
    cloned = [
        _clone_breakdown_row(row, _sort_breakdown_rows(list(row.get("children", [])), mode))
        for row in rows
    ]
    if mode == "actionable":
        return sorted(
            cloned,
            key=lambda row: (
                -_count_total(row.get("actionable", (0, 0, 0))),
                str(row.get("name", "")).lower(),
            ),
        )
    if mode == "eta":
        return sorted(
            cloned,
            key=lambda row: (
                _eta_sort_key(row.get("eta", "N/A")),
                -_count_total(row.get("actionable", (0, 0, 0))),
                str(row.get("name", "")).lower(),
            ),
        )
    return cloned


class _WorkloadSegmentBar(QWidget):
    """Read-only stacked workload mix bar used in the deck breakdown dashboard."""

    def __init__(self, palette: Dict[str, str], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._palette = palette
        self._counts: Tuple[int, int, int] = (0, 0, 0)
        self._display_counts: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._animation = None
        if hasattr(self, "setMinimumHeight"):
            self.setMinimumHeight(14)
        if hasattr(self, "setMouseTracking"):
            self.setMouseTracking(True)
        self.setAccessibleName("Workload type breakdown")
        self.setAccessibleDescription("Stacked bar showing New, Learning, and Review cards due today.")
        self.setToolTip("No cards due today")

    def set_counts(self, counts: Tuple[int, int, int], animate: bool = True) -> None:
        target = tuple(float(value) for value in _normalize_counts(counts))
        self._counts = _normalize_counts(counts)
        animation_cls = globals().get("QVariantAnimation")
        if animate and animation_cls is not None and target != self._display_counts:
            if self._animation is not None and hasattr(self._animation, "stop"):
                try:
                    self._animation.stop()
                except (AttributeError, RuntimeError) as exc:
                    _report_ui_failure("stop workload animation", exc)
            start = self._display_counts
            self._animation = animation_cls(self)
            try:
                self._animation.setDuration(180)
                self._animation.setStartValue(0.0)
                self._animation.setEndValue(1.0)
                self._animation.valueChanged.connect(
                    lambda value: self._set_interpolated_counts(start, target, float(value))
                )
                self._animation.finished.connect(lambda: self._finish_animation(target))
                self._animation.start()
                return
            except Exception:
                self._animation = None

        self._display_counts = target
        self.update()

    def _set_interpolated_counts(
        self, start: Tuple[float, float, float], target: Tuple[float, float, float], fraction: float
    ) -> None:
        bounded = max(0.0, min(1.0, fraction))
        self._display_counts = tuple(start[index] + ((target[index] - start[index]) * bounded) for index in range(3))
        self.update()

    def _finish_animation(self, target: Tuple[float, float, float]) -> None:
        self._display_counts = target
        self.update()

    def _segment_details(self) -> List[Tuple[str, int, str]]:
        return [
            ("New", self._counts[0], self._palette["segment_new"]),
            ("Learning", self._counts[1], self._palette["segment_learning"]),
            ("Review", self._counts[2], self._palette["segment_review"]),
        ]

    def apply_theme(self, palette: Dict[str, str]) -> None:
        self._palette = palette
        self.update()

    def _segment_tooltip_at(self, x: float) -> str:
        total = sum(self._counts)
        if total <= 0:
            return "No cards due today"
        width = max(1, self.width())
        running = 0.0
        for label, count, _color in self._segment_details():
            if count <= 0:
                continue
            segment_width = width * (count / total)
            if x <= running + segment_width:
                percent = (count / total) * 100
                return f"{label}: {count} ({percent:.0f}%)"
            running += segment_width
        label, count, _color = self._segment_details()[-1]
        percent = (count / total) * 100
        return f"{label}: {count} ({percent:.0f}%)"

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        try:
            pos = event.position()
            x_value = pos.x()
        except Exception:
            try:
                pos = event.pos()
                x_value = pos.x()
            except Exception:
                x_value = 0
        tooltip_text = self._segment_tooltip_at(float(x_value))
        self.setToolTip(tooltip_text)
        try:
            global_pos = event.globalPosition().toPoint()
        except Exception:
            try:
                global_pos = event.globalPos()
            except Exception:
                global_pos = None
        if global_pos is not None:
            try:
                QToolTip.showText(global_pos, tooltip_text, self)
            except (AttributeError, RuntimeError, TypeError) as exc:
                _report_ui_failure("show workload tooltip", exc)

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        try:
            render_hint = getattr(getattr(QPainter, "RenderHint", QPainter), "Antialiasing", None)
            if render_hint is not None and hasattr(painter, "setRenderHint"):
                painter.setRenderHint(render_hint)
            rect = self.rect().adjusted(0, 3, 0, -3)
            if rect.width() <= 0 or rect.height() <= 0:
                return

            if hasattr(painter, "setPen"):
                no_pen = getattr(getattr(Qt, "PenStyle", Qt), "NoPen", None)
                if no_pen is not None:
                    painter.setPen(no_pen)
            if hasattr(painter, "setBrush") and hasattr(painter, "drawRoundedRect"):
                painter.setBrush(QColor(self._palette["segment_track"]))
                painter.drawRoundedRect(rect, 5, 5)
            else:
                painter.fillRect(rect, QColor(self._palette["segment_track"]))

            total = sum(self._display_counts)
            if total <= 0:
                painter.fillRect(rect, QColor(self._palette["segment_empty"]))
                return

            x_pos = rect.left()
            remaining_width = rect.width()
            details = [
                ("New", self._display_counts[0], self._palette["segment_new"]),
                ("Learning", self._display_counts[1], self._palette["segment_learning"]),
                ("Review", self._display_counts[2], self._palette["segment_review"]),
            ]
            visible = [(label, value, color) for label, value, color in details if value > 0]
            for index, (_label, value, color) in enumerate(visible):
                if index == len(visible) - 1:
                    segment_width = remaining_width
                else:
                    segment_width = int(round(rect.width() * (value / total)))
                    segment_width = max(1, min(segment_width, remaining_width))
                segment_rect = QRect(x_pos, rect.top(), segment_width, rect.height())
                painter.fillRect(segment_rect, QColor(color))
                x_pos += segment_width
                remaining_width = max(0, remaining_width - segment_width)
        except Exception:
            return


class _DashboardSummaryCard(QFrame):
    """Compact summary card for the deck breakdown dashboard."""

    def __init__(self, palette: Dict[str, str], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._palette = palette
        self._summary: Dict[str, Any] = _build_breakdown_summary([])
        self._chip_labels: Dict[str, QLabel] = {}
        self.setObjectName("dashboardSummaryCard")
        self._build_ui()

    def _build_ui(self) -> None:
        frame_shape = getattr(getattr(QFrame, "Shape", QFrame), "StyledPanel", None)
        if frame_shape is not None:
            self.setFrameShape(frame_shape)
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(5)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        self._title_label = QLabel("Today")
        self._title_label.setObjectName("dashboardTitle")
        self._title_label.setWordWrap(False)

        self._info_btn = QToolButton()
        self._info_btn.setText("i")
        self._info_btn.setAutoRaise(True)
        self._info_btn.setToolTip(BREAKDOWN_INFO_TEXT)
        self._info_btn.setAccessibleName("About counts")
        self._info_btn.setAccessibleDescription(BREAKDOWN_INFO_TEXT)

        self._copy_btn = QToolButton()
        self._copy_btn.setText("Copy")
        self._copy_btn.setToolTip("Copy workload summary")
        self._copy_btn.setAccessibleName("Copy workload summary")
        self._copy_btn.clicked.connect(self._copy_summary)

        header.addWidget(self._title_label)
        header.addStretch(1)
        header.addWidget(self._info_btn)
        header.addWidget(self._copy_btn)
        layout.addLayout(header)

        self._main_label = QLabel("")
        self._main_label.setObjectName("dashboardMain")
        self._main_label.setWordWrap(True)
        layout.addWidget(self._main_label)

        self._segment_bar = _WorkloadSegmentBar(self._palette)
        layout.addWidget(self._segment_bar)

        chip_row = QHBoxLayout()
        chip_row.setContentsMargins(0, 0, 0, 0)
        chip_row.setSpacing(6)
        for key in ("new", "learning", "review"):
            label = QLabel("")
            label.setStyleSheet(self._chip_style(key, active=False))
            self._chip_labels[key] = label
            chip_row.addWidget(label)
        chip_row.addStretch(1)
        layout.addLayout(chip_row)

        self.setLayout(layout)

    def _chip_style(self, key: str, active: bool) -> str:
        if active:
            bg = self._palette[f"chip_{key}_bg"]
            border = self._palette[f"chip_{key}_border"]
            color = self._palette[f"chip_{key}_text"]
        else:
            bg = self._palette["chip_muted_bg"]
            border = self._palette["chip_border"]
            color = self._palette["chip_muted_text"]
        return (
            f"background: {bg}; border: 1px solid {border}; border-radius: 6px; "
            f"color: {color}; padding: 2px 7px; font-size: 11px; font-weight: 600;"
        )

    def apply_theme(self, palette: Dict[str, str]) -> None:
        self._palette = palette
        self._segment_bar.apply_theme(palette)
        self.update_summary(self._summary)
        self.update()

    def update_summary(self, summary: Dict[str, Any]) -> None:
        self._summary = dict(summary)
        self._title_label.setText(str(summary.get("title", "Today")))
        self._main_label.setText(str(summary.get("main", _format_summary_main(summary))))

        new, lrn, rev = _normalize_counts(summary.get("actionable", (0, 0, 0)))
        chip_values = {
            "new": ("New", new),
            "learning": ("Learning", lrn),
            "review": ("Review", rev),
        }
        for key, (label, value) in chip_values.items():
            chip = self._chip_labels[key]
            chip.setText(f"{label} {value}")
            chip.setStyleSheet(self._chip_style(key, active=value > 0))
        self._segment_bar.set_counts((new, lrn, rev))
        self.setToolTip("")

    def _copy_summary(self) -> None:
        text = str(self._summary.get("clipboard") or _format_summary_clipboard(self._summary))
        copied = False
        app_cls = globals().get("QApplication")
        if app_cls is not None:
            try:
                clipboard = app_cls.clipboard()
                clipboard.setText(text)
                copied = True
            except Exception:
                copied = False
        if not copied:
            setattr(mw, "_last_clipboard_text", text)


try:
    _StyledItemDelegateBase = QStyledItemDelegate
except NameError:  # pragma: no cover - only used if Qt omits the delegate in tests
    class _StyledItemDelegateBase(QWidget):  # type: ignore[no-redef]
        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)

        def paint(self, *_args, **_kwargs) -> None:
            return None

        def sizeHint(self, *_args, **_kwargs):
            return QSize(170, 30)


_COUNT_CELL_MIN_WIDTH = 190
_COUNT_CELL_MIN_HEIGHT = 30
_BREAKDOWN_DIALOG_MIN_WIDTH = 850
_BREAKDOWN_DIALOG_MAX_WIDTH = 950
_BREAKDOWN_DIALOG_FRAME_WIDTH = 32
_BREAKDOWN_DIALOG_SCREEN_MARGIN = 80
_BREAKDOWN_DIALOG_DEFAULT_HEIGHT = 560
_BREAKDOWN_COLUMN_WIDTH_BOUNDS = {
    0: (250, 420),
    1: (190, 250),
    2: (190, 240),
    3: (100, 130),
}


def _count_cell_width_hint(counts: Any, metrics: Any = None) -> int:
    """Return the painted count-cell width using the active Qt font metrics."""

    new, lrn, rev = _normalize_counts(counts)
    total = new + lrn + rev
    total_width = horizontal_advance(metrics, total)
    chip_widths = [horizontal_advance(metrics, f"{label} {value}") + 14 for label, value in (
        ("N", new), ("L", lrn), ("R", rev),
    )]
    return max(_COUNT_CELL_MIN_WIDTH, 8 + total_width + 18 + sum(chip_widths) + 10)


class _CountBreakdownDelegate(_StyledItemDelegateBase):
    """Paint count cells as a total with compact N/L/R chips."""

    def __init__(self, palette: Dict[str, str], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._palette = palette

    def apply_theme(self, palette: Dict[str, str]) -> None:
        self._palette = palette
        parent = None
        if hasattr(self, "parent"):
            try:
                parent = self.parent()
            except Exception:
                parent = None
        if parent is None and hasattr(self, "parentWidget"):
            try:
                parent = self.parentWidget()
            except Exception:
                parent = None

        viewport = parent
        if parent is not None and hasattr(parent, "viewport"):
            try:
                viewport = parent.viewport()
            except Exception:
                viewport = parent
        if viewport is not None and hasattr(viewport, "update"):
            try:
                viewport.update()
            except (AttributeError, RuntimeError) as exc:
                _report_ui_failure("refresh count delegate viewport", exc)

    def sizeHint(self, option, index):  # type: ignore[override]
        try:
            base = super().sizeHint(option, index)
            base_width = base.width() if callable(getattr(base, "width", None)) else getattr(base, "width", 170)
            base_height = base.height() if callable(getattr(base, "height", None)) else getattr(base, "height", 30)
            metrics = getattr(option, "fontMetrics", None)
            width = max(_count_cell_width_hint(index.data(_BREAKDOWN_COUNTS_ROLE), metrics), base_width)
            height = max(_COUNT_CELL_MIN_HEIGHT, base_height)
            return QSize(width, height)
        except Exception:
            return QSize(_COUNT_CELL_MIN_WIDTH, _COUNT_CELL_MIN_HEIGHT)

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        counts = index.data(_BREAKDOWN_COUNTS_ROLE)
        if counts is None:
            try:
                super().paint(painter, option, index)
            except (AttributeError, RuntimeError, TypeError) as exc:
                _report_ui_failure("paint default count cell", exc)
            return

        try:
            option_cls = globals().get("QStyleOptionViewItem")
            if option_cls is not None:
                blank_option = option_cls(option)
                if hasattr(self, "initStyleOption"):
                    self.initStyleOption(blank_option, index)
                blank_option.text = ""
                super().paint(painter, blank_option, index)
            else:
                super().paint(painter, option, index)
        except (AttributeError, RuntimeError, TypeError) as exc:
            _report_ui_failure("paint count cell background", exc)

        try:
            new, lrn, rev = _normalize_counts(counts)
            total = new + lrn + rev
            muted = bool(index.data(_BREAKDOWN_MUTED_ROLE))
            child = bool(index.data(_BREAKDOWN_CHILD_ROLE))
            rect = option.rect.adjusted(8, 4, -8, -4)

            painter.save()
            base_font = painter.font()
            font_cls = globals().get("QFont")
            if font_cls is not None:
                total_font = font_cls(base_font)
                total_font.setBold(True)
                painter.setFont(total_font)
            total_metrics = painter.fontMetrics()
            text_color = self._palette["muted_row_text"] if muted else (
                self._palette["secondary_text"] if child else self._palette["primary_text"]
            )
            painter.setPen(_qcolor_from_css(text_color))
            total_text = str(total)
            flags = getattr(Qt.AlignmentFlag, "AlignVCenter", 0) | getattr(Qt.AlignmentFlag, "AlignLeft", 0)
            painter.drawText(rect, flags, total_text)

            total_width = total_metrics.horizontalAdvance(total_text) if hasattr(total_metrics, "horizontalAdvance") else total_metrics.width(total_text)
            x_pos = rect.left() + total_width + 18
            chip_height = min(20, max(16, rect.height() - 2))
            chip_top = rect.top() + max(0, (rect.height() - chip_height) // 2)

            if font_cls is not None:
                painter.setFont(base_font)
            chip_metrics = painter.fontMetrics()
            chip_data = (("N", "new", new), ("L", "learning", lrn), ("R", "review", rev))
            for label, semantic, value in chip_data:
                chip_text = f"{label} {value}"
                chip_width = (chip_metrics.horizontalAdvance(chip_text) if hasattr(chip_metrics, "horizontalAdvance") else chip_metrics.width(chip_text)) + 14
                chip_rect = QRect(x_pos, chip_top, chip_width, chip_height)
                active = value > 0 and not muted
                bg = self._palette[f"chip_{semantic}_bg"] if active else self._palette["chip_muted_bg"]
                text = self._palette[f"chip_{semantic}_text"] if active else self._palette["chip_muted_text"]
                if hasattr(painter, "setPen"):
                    no_pen = getattr(getattr(Qt, "PenStyle", Qt), "NoPen", None)
                    if no_pen is not None:
                        painter.setPen(no_pen)
                if hasattr(painter, "setBrush") and hasattr(painter, "drawRoundedRect"):
                    painter.setBrush(_qcolor_from_css(bg))
                    painter.drawRoundedRect(chip_rect, 5, 5)
                else:
                    painter.fillRect(chip_rect, _qcolor_from_css(bg))
                painter.setPen(_qcolor_from_css(text))
                painter.drawText(chip_rect, flags, chip_text)
                x_pos += chip_width + 5
            painter.restore()
        except (AttributeError, RuntimeError, TypeError) as exc:
            _report_ui_failure("paint count cell", exc)
            try:
                super().paint(painter, option, index)
            except (AttributeError, RuntimeError, TypeError) as fallback_exc:
                _report_ui_failure("paint count cell fallback", fallback_exc)


class DeckBreakdownDialog(QDialog):
    """Popover showing due-today and buried counts per deck with projected finish times."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Deck Breakdown")
        self.setModal(False)
        self.setMinimumWidth(_BREAKDOWN_DIALOG_MIN_WIDTH)
        self.resize(_BREAKDOWN_DIALOG_MIN_WIDTH, _BREAKDOWN_DIALOG_DEFAULT_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self._tree = None
        self._tree_widget_item_cls = None
        self._header_view_cls = None
        self._summary_card = None
        self._count_delegate = None
        self._toolbar = None
        self._hide_empty_cb = None
        self._sort_combo = None
        self._raw_rows: List[Dict[str, Any]] = []
        self._summary: Dict[str, Any] = _build_breakdown_summary([])
        self._hide_empty = True
        self._sort_mode = "deck"
        self._auto_fit_pending = True
        self._theme_tokens = _ui_tokens()
        self._palette = self._theme_tokens.as_palette()
        self._build_ui()

    def request_auto_fit(self) -> None:
        """Fit the dialog to its content the next time rows are rebuilt."""
        self._auto_fit_pending = True

    def _build_ui(self) -> None:
        try:
            from aqt.qt import QHeaderView, QTreeWidget, QTreeWidgetItem
        except Exception:
            QHeaderView = None
            QTreeWidget = None
            QTreeWidgetItem = None

        self._tree_widget_item_cls = QTreeWidgetItem
        self._header_view_cls = QHeaderView

        if QTreeWidget is None or QTreeWidgetItem is None:
            # If the Qt widgets are unavailable (e.g., during headless tests), skip UI setup.
            self._tree = None
            return

        palette = self._palette
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self._summary_card = _DashboardSummaryCard(palette)
        layout.addWidget(self._summary_card)

        self._toolbar = QFrame()
        self._toolbar.setObjectName("breakdownToolbar")
        controls = QHBoxLayout()
        controls.setContentsMargins(10, 6, 10, 6)
        controls.setSpacing(8)

        self._hide_empty_cb = QCheckBox("Hide empty")
        self._hide_empty_cb.setToolTip("Hide decks with no cards due today unless a child deck has work.")
        self._hide_empty_cb.setChecked(True)
        self._hide_empty_cb.toggled.connect(self._on_hide_empty_changed)

        sort_label = QLabel("Sort")
        self._sort_combo = QComboBox()
        self._sort_combo.addItem("Deck order", "deck")
        self._sort_combo.addItem("Most due today", "actionable")
        self._sort_combo.addItem("Soonest ETA", "eta")
        self._sort_combo.setToolTip("Sort visible sibling decks without changing deck data.")
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)

        controls.addWidget(self._hide_empty_cb)
        controls.addStretch(1)
        controls.addWidget(sort_label)
        controls.addWidget(self._sort_combo)
        self._toolbar.setLayout(controls)
        layout.addWidget(self._toolbar)

        self._tree = QTreeWidget()
        self._tree.setRootIsDecorated(True)
        self._tree.setUniformRowHeights(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setHeaderLabels(["Deck", "Due Today", "Buried", "ETA"])
        if hasattr(self._tree, "setAllColumnsShowFocus"):
            self._tree.setAllColumnsShowFocus(True)
        if hasattr(self._tree, "setIndentation"):
            self._tree.setIndentation(22)
        elide_mode = getattr(getattr(Qt, "TextElideMode", Qt), "ElideMiddle", None)
        if elide_mode is not None and hasattr(self._tree, "setTextElideMode"):
            self._tree.setTextElideMode(elide_mode)

        scroll_policies = getattr(Qt, "ScrollBarPolicy", Qt)
        as_needed = getattr(scroll_policies, "ScrollBarAsNeeded", None)
        if as_needed is not None:
            if hasattr(self._tree, "setHorizontalScrollBarPolicy"):
                self._tree.setHorizontalScrollBarPolicy(as_needed)
            if hasattr(self._tree, "setVerticalScrollBarPolicy"):
                self._tree.setVerticalScrollBarPolicy(as_needed)

        self._tree.header().setStretchLastSection(False)
        if hasattr(self._tree.header(), "setMinimumSectionSize"):
            self._tree.header().setMinimumSectionSize(72)
        self._set_header_resize_mode(0, "Stretch")
        for column in range(1, 4):
            self._set_header_resize_mode(column, "Interactive")

        if hasattr(self._tree, "setItemDelegateForColumn"):
            self._count_delegate = _CountBreakdownDelegate(palette, self._tree)
            self._tree.setItemDelegateForColumn(1, self._count_delegate)
            self._tree.setItemDelegateForColumn(2, self._count_delegate)

        layout.addWidget(self._tree)

        self.setLayout(layout)
        self.apply_theme()
        self._summary_card.update_summary(self._summary)

    def apply_theme(self) -> None:
        self._theme_tokens = _ui_tokens()
        self._palette = self._theme_tokens.as_palette()
        qss = deck_breakdown_qss(self._theme_tokens)
        self.setStyleSheet(qss)
        if self._tree is not None:
            self._tree.setStyleSheet(qss)
        if self._sort_combo is not None:
            self._sort_combo.setStyleSheet(combo_qss(self._theme_tokens))
        if self._summary_card is not None:
            self._summary_card.apply_theme(self._palette)
        if self._count_delegate is not None:
            self._count_delegate.apply_theme(self._palette)
        if self._tree is not None and self._raw_rows:
            self._rebuild_tree()
        self.update()

    def _format_counts(self, counts: Tuple[int, int, int]) -> str:
        return _format_counts_compact(counts)

    def _header_resize_mode(self, name: str):
        resize_container = getattr(self._header_view_cls, "ResizeMode", self._header_view_cls)
        return getattr(resize_container, name, None)

    def _set_header_resize_mode(self, column: int, mode_name: str) -> None:
        if self._tree is None:
            return
        mode = self._header_resize_mode(mode_name)
        header = self._tree.header()
        if mode is not None and hasattr(header, "setSectionResizeMode"):
            try:
                header.setSectionResizeMode(column, mode)
            except (AttributeError, RuntimeError, TypeError) as exc:
                _report_ui_failure("set deck header resize mode", exc)

    def _tree_viewport_width(self) -> int:
        if self._tree is None:
            return _BREAKDOWN_DIALOG_MIN_WIDTH
        try:
            viewport = self._tree.viewport()
            width = viewport.width()
        except Exception:
            try:
                width = self._tree.width()
            except Exception:
                width = _BREAKDOWN_DIALOG_MIN_WIDTH
        return int(width) if width and width > 500 else _BREAKDOWN_DIALOG_MIN_WIDTH

    def _column_width(self, column: int) -> int:
        if self._tree is None:
            return 0
        try:
            return int(self._tree.columnWidth(column))
        except Exception:
            return _BREAKDOWN_COLUMN_WIDTH_BOUNDS.get(column, (90, 180))[0]

    def _set_column_width(self, column: int, width: int) -> None:
        if self._tree is None or not hasattr(self._tree, "setColumnWidth"):
            return
        try:
            self._tree.setColumnWidth(column, int(width))
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            _report_ui_failure("set deck column width", exc)

    def _available_screen_width(self) -> Optional[int]:
        screen = None
        if hasattr(self, "screen"):
            try:
                screen = self.screen()
            except Exception:
                screen = None
        if screen is None:
            app_cls = globals().get("QApplication")
            if app_cls is not None and hasattr(app_cls, "primaryScreen"):
                try:
                    screen = app_cls.primaryScreen()
                except Exception:
                    screen = None
        if screen is None or not hasattr(screen, "availableGeometry"):
            return None
        try:
            width = screen.availableGeometry().width()
        except Exception:
            return None
        return int(width) if width else None

    def _resize_dialog_to_columns(self, column_widths: Dict[int, int]) -> None:
        if not column_widths:
            return
        target_width = sum(column_widths.values()) + _BREAKDOWN_DIALOG_FRAME_WIDTH
        target_width = max(_BREAKDOWN_DIALOG_MIN_WIDTH, min(target_width, _BREAKDOWN_DIALOG_MAX_WIDTH))
        screen_width = self._available_screen_width()
        if screen_width:
            target_width = min(
                target_width,
                max(_BREAKDOWN_DIALOG_MIN_WIDTH, screen_width - _BREAKDOWN_DIALOG_SCREEN_MARGIN),
            )
        if not hasattr(self, "resize"):
            return
        try:
            current_height = int(self.height()) if hasattr(self, "height") else 0
        except Exception:
            current_height = 0
        self.resize(target_width, current_height if current_height > 0 else _BREAKDOWN_DIALOG_DEFAULT_HEIGHT)
        self._auto_fit_pending = False

    def _text_width_hint(self, text: Any, padding: int = 28) -> int:
        return widget_text_width(self._tree or self, text, padding=padding, minimum=72)

    def _column_content_width_hints(self, rows: List[Dict[str, Any]]) -> Dict[int, int]:
        hints = {
            0: self._text_width_hint("Deck"),
            1: self._text_width_hint("Due Today"),
            2: self._text_width_hint("Buried"),
            3: self._text_width_hint("ETA", 36),
        }
        try:
            indentation = int(self._tree.indentation()) if hasattr(self._tree, "indentation") else 22
        except Exception:
            indentation = 22

        def visit(row: Dict[str, Any], depth: int = 0) -> None:
            hints[0] = max(hints[0], self._text_width_hint(row.get("name", ""), 44 + (depth * indentation)))
            metrics_getter = getattr(self._tree, "fontMetrics", None)
            metrics = metrics_getter() if callable(metrics_getter) else None
            hints[1] = max(hints[1], _count_cell_width_hint(row.get("actionable", (0, 0, 0)), metrics))
            hints[2] = max(hints[2], _count_cell_width_hint(row.get("buried", (0, 0, 0)), metrics))
            hints[3] = max(hints[3], self._text_width_hint(row.get("eta", "N/A"), 40))
            for child in row.get("children", []):
                visit(child, depth + 1)

        for row in rows:
            visit(row)
        return hints

    def _resize_columns_to_content(self, visible_rows: Optional[List[Dict[str, Any]]] = None) -> None:
        if self._tree is None:
            return

        content_hints = self._column_content_width_hints(visible_rows or [])
        measured_widths: Dict[int, int] = {}
        for column in range(4):
            self._set_header_resize_mode(column, "ResizeToContents")
            if hasattr(self._tree, "resizeColumnToContents"):
                try:
                    self._tree.resizeColumnToContents(column)
                except (AttributeError, RuntimeError, TypeError) as exc:
                    _report_ui_failure("measure deck column", exc)
            measured_widths[column] = max(self._column_width(column), content_hints.get(column, 0))

        applied_widths: Dict[int, int] = {}
        for column in range(1, 4):
            minimum, maximum = _BREAKDOWN_COLUMN_WIDTH_BOUNDS[column]
            applied_widths[column] = max(minimum, min(measured_widths.get(column, minimum), maximum))

        deck_minimum, deck_maximum = _BREAKDOWN_COLUMN_WIDTH_BOUNDS[0]
        desired_deck_width = max(deck_minimum, min(measured_widths.get(0, deck_minimum), deck_maximum))
        desired_dialog_width = desired_deck_width + sum(applied_widths.values()) + _BREAKDOWN_DIALOG_FRAME_WIDTH
        target_dialog_width = max(
            _BREAKDOWN_DIALOG_MIN_WIDTH,
            min(desired_dialog_width, _BREAKDOWN_DIALOG_MAX_WIDTH),
        )
        applied_widths[0] = max(
            deck_minimum,
            target_dialog_width - _BREAKDOWN_DIALOG_FRAME_WIDTH - sum(applied_widths.values()),
        )

        for column, width in applied_widths.items():
            self._set_column_width(column, width)

        self._set_header_resize_mode(0, "Stretch")
        for column in range(1, 4):
            self._set_header_resize_mode(column, "Interactive")
        if self._auto_fit_pending:
            self._resize_dialog_to_columns(applied_widths)

    def _set_count_data(self, item: QTreeWidgetItem, column: int, counts: Tuple[int, int, int], muted: bool) -> None:
        item.setText(column, "")
        item.setData(column, _BREAKDOWN_COUNTS_ROLE, counts)
        item.setData(column, _BREAKDOWN_MUTED_ROLE, muted)
        item.setData(column, _BREAKDOWN_TOTAL_ROLE, _count_total(counts))

    def _apply_row_style(self, item: QTreeWidgetItem, muted: bool, eta_muted: bool, is_child: bool) -> None:
        palette = self._palette
        brush_cls = globals().get("QBrush")
        color_cls = globals().get("QColor")
        if brush_cls is None or color_cls is None or not hasattr(item, "setForeground"):
            return

        for column in range(4):
            color = palette["muted_row_text"] if muted else (
                palette["secondary_text"] if is_child else palette["primary_text"]
            )
            if column == 3 and eta_muted:
                color = palette["eta_muted_text"]
            try:
                item.setForeground(column, brush_cls(color_cls(color)))
            except (AttributeError, RuntimeError, TypeError) as exc:
                _report_ui_failure("style deck row", exc)

    def _add_row(self, row: Dict[str, Any], parent_item: Optional[QTreeWidgetItem] = None) -> QTreeWidgetItem:
        if self._tree is None or self._tree_widget_item_cls is None:
            return None  # type: ignore[return-value]

        actionable = _normalize_counts(row.get("actionable", (0, 0, 0)))
        buried = _normalize_counts(row.get("buried", (0, 0, 0)))
        actionable_total = _count_total(actionable)
        muted = actionable_total == 0
        eta_text = str(row.get("eta", "N/A") or "N/A")
        eta_muted = eta_text == "N/A"
        name = str(row.get("name", ""))

        item = QTreeWidgetItem(parent_item or self._tree)
        item.setText(0, name)
        self._set_count_data(item, 1, actionable, muted)
        self._set_count_data(item, 2, buried, muted and _count_total(buried) == 0)
        item.setText(3, eta_text)
        item.setData(0, _BREAKDOWN_MUTED_ROLE, muted)
        item.setData(3, _BREAKDOWN_MUTED_ROLE, eta_muted)
        is_child = parent_item is not None
        for column in range(4):
            item.setData(column, _BREAKDOWN_CHILD_ROLE, is_child)
        if not is_child and hasattr(item, "font") and hasattr(item, "setFont"):
            try:
                parent_font = item.font(0)
                parent_font.setBold(True)
                item.setFont(0, parent_font)
            except (AttributeError, RuntimeError, TypeError) as exc:
                _report_ui_failure("style parent deck row", exc)
        if hasattr(item, "setToolTip"):
            item.setToolTip(0, name)
            item.setToolTip(1, _format_counts_accessible("Due today", actionable))
            item.setToolTip(2, _format_counts_accessible("Buried", buried))
            item.setToolTip(3, "No ETA yet" if eta_muted else f"Finish estimate: {eta_text}")
        item.setTextAlignment(1, int(Qt.AlignmentFlag.AlignVCenter))
        item.setTextAlignment(2, int(Qt.AlignmentFlag.AlignVCenter))
        item.setTextAlignment(3, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight))
        self._apply_row_style(item, muted, eta_muted, is_child)

        for child in row.get("children", []):
            self._add_row(child, item)
        return item

    def _visible_rows(self) -> List[Dict[str, Any]]:
        rows = _filter_breakdown_rows(self._raw_rows, self._hide_empty)
        return _sort_breakdown_rows(rows, self._sort_mode)

    def _rebuild_tree(self) -> None:
        if self._tree is None:
            return
        self._tree.clear()
        visible_rows = self._visible_rows()
        for row in visible_rows:
            self._add_row(row)
        self._tree.expandToDepth(1)
        self._resize_columns_to_content(visible_rows)

    def _on_hide_empty_changed(self, checked: bool) -> None:
        self._hide_empty = bool(checked)
        self._rebuild_tree()

    def _on_sort_changed(self, _index: int) -> None:
        try:
            mode = self._sort_combo.currentData()
        except Exception:
            mode = "deck"
        self._sort_mode = mode or "deck"
        self._rebuild_tree()

    def update_rows(self, rows: List[Dict[str, Any]], summary: Optional[Dict[str, Any]] = None) -> None:
        self._raw_rows = [dict(row) for row in rows]
        self._summary = summary or _build_breakdown_summary(self._raw_rows)
        if self._summary_card is not None:
            self._summary_card.update_summary(self._summary)
        self._rebuild_tree()


class ProgressBarConfigDialog(QDialog):
    """Small settings dialog for the supported configuration surface."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Progress Bar Settings")
        self.setMinimumSize(680, 560)
        self.resize(680, 620)
        self._config_snapshot = deepcopy(config)
        self._building_ui = True
        self._dirty = False
        self._compact_layout_active = False
        self._setting_rows: List[SettingRow] = []
        self._build_ui()
        self._populate_from_config(self._config_snapshot)
        self._building_ui = False
        self._update_dirty_state(False)

    def _build_ui(self) -> None:
        tokens = _ui_tokens()
        palette = tokens.as_palette()
        field_style = combo_qss(tokens)
        self.setStyleSheet(settings_dialog_qss(tokens))

        layout = QVBoxLayout()
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(8)

        self.progress_bar_enabled_cb = QCheckBox("Show progress bar")
        self.show_smtr_cb = QCheckBox("Show SMTR")

        self.display_location_combo = QComboBox()
        self.display_location_combo.addItem("Review Only", "review")
        self.display_location_combo.addItem("Review and Home", "review_and_home")
        self.display_location_combo.setStyleSheet(field_style)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Simple", "simple")
        self.mode_combo.addItem("Advanced", "stats")
        self.mode_combo.setStyleSheet(field_style)

        self.dock_area_combo = QComboBox()
        self.dock_area_combo.addItem("Top", "top")
        self.dock_area_combo.addItem("Bottom", "bottom")
        self.dock_area_combo.setStyleSheet(field_style)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Auto", "auto")
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.setStyleSheet(field_style)

        # In Qt on macOS, Ctrl corresponds to the Command key. Meta would
        # bind the physical Control key instead.
        default_shortcut = "Ctrl+G"
        self.shortcut_field = ShortcutField(default_shortcut, palette)

        for control in (
            self.display_location_combo,
            self.mode_combo,
            self.dock_area_combo,
            self.show_smtr_cb,
            self.theme_combo,
            self.shortcut_field,
        ):
            control.setFixedWidth(200)

        self._header = QFrame()
        self._header.setObjectName("settingsHeader")
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.addWidget(self.progress_bar_enabled_cb)
        header_layout.addStretch(1)
        self._header.setLayout(header_layout)
        layout.addWidget(self._header)

        self._setting_rows = [
            SettingRow("Show On", "Choose whether the progress bar appears on the deck browser and during reviews, or only during reviews.", self.display_location_combo, palette),
            SettingRow("Mode", "Simple shows counts. Advanced adds ETA, retention, speed, and review metrics.", self.mode_combo, palette),
            SettingRow("Position", "Place the progress bar above or below the reviewer.", self.dock_area_combo, palette),
            SettingRow("SMTR", "Show super-mature retention in the Advanced progress label.", self.show_smtr_cb, palette),
            SettingRow("Theme", "Auto follows Anki; Light and Dark force the built-in themes.", self.theme_combo, palette),
            SettingRow("Shortcut", "Record the key sequence used to show or hide the progress bar.", self.shortcut_field, palette),
        ]

        self._display_card = self._build_settings_card("Display", self._setting_rows[:4])
        self._appearance_card = self._build_settings_card("Appearance & Shortcut", self._setting_rows[4:])
        layout.addWidget(self._display_card)
        layout.addWidget(self._appearance_card)

        self._dirty_badge = QLabel("")
        self._dirty_badge.setObjectName("dirtyBadge")
        self._dirty_badge.setStyleSheet(f"color: {palette['muted_text']}; font-weight: 600;")

        self._footer = QFrame()
        self._footer.setObjectName("settingsFooter")
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 8, 0, 0)
        button_row.setSpacing(8)
        self._donate_btn = self._build_donate_button()
        button_row.addWidget(self._donate_btn)
        button_row.addWidget(self._dirty_badge)
        button_row.addStretch()
        self._apply_btn = QPushButton("Apply")
        self._apply_btn.clicked.connect(self._apply_without_closing)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("primaryButton")
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self._save_and_close)
        button_row.addWidget(self._apply_btn)
        button_row.addWidget(self._cancel_btn)
        button_row.addWidget(self._save_btn)
        self._footer.setLayout(button_row)
        layout.addWidget(self._footer)
        self.setLayout(layout)

        for control in (
            self.progress_bar_enabled_cb,
            self.show_smtr_cb,
            self.display_location_combo,
            self.mode_combo,
            self.dock_area_combo,
            self.theme_combo,
            self.shortcut_field,
        ):
            self._watch_control(control)

        self.apply_theme()

    def _build_settings_card(self, title: str, rows: List[SettingRow]) -> QFrame:
        card = QFrame()
        card.setObjectName("settingsCard")
        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(0, 8, 0, 0)
        card_layout.setSpacing(0)
        section_title = QLabel(title)
        section_title.setObjectName("settingsSectionTitle")
        card_layout.addWidget(section_title)
        for row in rows:
            card_layout.addWidget(row)
        card.setLayout(card_layout)
        return card

    def apply_theme(self) -> None:
        tokens = _ui_tokens()
        palette = tokens.as_palette()
        self.setStyleSheet(settings_dialog_qss(tokens))
        for combo in (
            self.display_location_combo,
            self.mode_combo,
            self.dock_area_combo,
            self.theme_combo,
        ):
            combo.setStyleSheet(combo_qss(tokens))
        self.shortcut_field.apply_theme(palette)
        for row in self._setting_rows:
            row.apply_theme(palette)
        self._dirty_badge.setStyleSheet(f"color: {palette['muted_text']}; font-weight: 600;")
        self._donate_btn.setStyleSheet(self._donate_button_style())
        self.update()

    def _donate_button_style(self) -> str:
        image_path = DONATE_IMAGE_PATH.as_posix()
        return f"""
            QToolButton#buyMeACoffeeButton {{
                border: none;
                border-image: url(\"{image_path}\") 0 0 0 0 stretch stretch;
                background: transparent;
                padding: 0px;
            }}
            QToolButton#buyMeACoffeeButton:hover {{
                border: none;
                border-image: url(\"{image_path}\") 0 0 0 0 stretch stretch;
                background: transparent;
            }}
        """

    def _build_donate_button(self) -> QToolButton:
        button = QToolButton()
        button.setObjectName("buyMeACoffeeButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(DONATE_TOOLTIP)
        button.setAccessibleName("Buy Me a Coffee")
        button.setAccessibleDescription(DONATE_TOOLTIP)
        button.clicked.connect(_open_donation_page)
        button.setFixedSize(98, 28)
        button.setStyleSheet(self._donate_button_style())

        if DONATE_IMAGE_PATH.exists():
            button.setIcon(QIcon())
        else:
            button.setText("Buy me a coffee")

        return button

    def _watch_control(self, control: QWidget) -> None:
        if isinstance(control, QCheckBox):
            control.toggled.connect(self._on_value_changed)
        elif isinstance(control, QComboBox):
            control.currentIndexChanged.connect(self._on_value_changed)
        elif isinstance(control, ShortcutField):
            control.shortcutChanged.connect(self._on_value_changed)

    def _populate_from_config(self, cfg: Dict[str, Any]) -> None:
        self.progress_bar_enabled_cb.setChecked(_coerce_bool(cfg.get("progress_bar_enabled"), True))
        self.show_smtr_cb.setChecked(_coerce_bool(cfg.get("show_super_mature_retention"), False))

        display_location = str(cfg.get("display_location", "review")).lower()
        if display_location not in {"review", "review_and_home"}:
            display_location = "review"
        self.display_location_combo.setCurrentIndex(max(0, self.display_location_combo.findData(display_location)))

        mode = str(cfg.get("mode", "stats")).lower()
        if mode not in {"simple", "time_left", "stats"}:
            mode = "stats"
        if mode == "time_left":
            mode = "stats"
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(mode)))

        dock = str(cfg.get("dock_area", "top")).lower()
        if dock not in {"top", "bottom"}:
            dock = "top"
        self.dock_area_combo.setCurrentIndex(max(0, self.dock_area_combo.findData(dock)))

        theme = str(cfg.get("theme", "auto")).lower()
        if theme not in {"auto", "light", "dark"}:
            theme = "auto"
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(theme)))

        shortcut = str(cfg.get("toggle_shortcut", self.shortcut_field.value()))
        if sys.platform == "darwin" and shortcut.lower() == "meta+g":
            shortcut = "Ctrl+G"
        self.shortcut_field.set_shortcut(shortcut)

    def _gather_config(self) -> Dict[str, Any]:
        updated_config = deepcopy(config)
        for key in addon_config.LEGACY_SETTING_KEYS:
            updated_config.pop(key, None)
        updated_config["progress_bar_enabled"] = self.progress_bar_enabled_cb.isChecked()
        updated_config["display_location"] = self.display_location_combo.currentData() or "review"
        updated_config["show_super_mature_retention"] = self.show_smtr_cb.isChecked()
        updated_config["mode"] = self.mode_combo.currentData() or "stats"
        updated_config["dock_area"] = self.dock_area_combo.currentData() or "top"
        updated_config["orientation"] = "horizontal"
        updated_config["theme"] = self.theme_combo.currentData() or "auto"
        updated_config["toggle_shortcut"] = self.shortcut_field.value().strip() or self.shortcut_field._default
        return updated_config

    def _update_dirty_state(self, dirty: bool) -> None:
        self._dirty = dirty
        self._dirty_badge.setText("Unsaved changes" if dirty else "All saved")
        self._save_btn.setEnabled(dirty and not self.shortcut_field.has_conflict())

    def _on_value_changed(self, *args) -> None:  # noqa: ARG002
        if self._building_ui:
            return
        self._update_dirty_state(True)

    def _apply_compact_mode(self, width: int) -> None:  # noqa: ARG002
        self._compact_layout_active = False

    def _write_config(self, *, show_toast: bool, close: bool) -> None:
        if self.shortcut_field.has_conflict():
            QMessageBox.warning(self, "Shortcut conflict", "Please resolve the shortcut conflict before saving.")
            return
        updated_config = self._gather_config()
        addon_config.apply_config(mw, updated_config)
        _apply_settings(show_messages=False)
        _refresh_open_theme_surfaces(self)
        self._config_snapshot = deepcopy(updated_config)
        self._update_dirty_state(False)
        if show_toast:
            tooltip("Progress Bar settings applied.", parent=mw, period=2000)
        if close:
            self.accept()

    def _apply_without_closing(self) -> None:
        self._write_config(show_toast=True, close=False)

    def _save_and_close(self) -> None:
        if not self._dirty and not self.shortcut_field.has_conflict():
            self.reject()
            return
        self._write_config(show_toast=False, close=True)


def _open_config_dialog() -> None:
    dialog = ProgressBarConfigDialog(mw)
    dialog.exec()


def _open_session_history_dialog() -> None:
    global _session_history_dialog
    dialog = SessionHistoryDialog(mw)
    _session_history_dialog = dialog
    try:
        dialog.exec()
    finally:
        _session_history_dialog = None


def _reload_configuration_action() -> None:
    _apply_settings(show_messages=True)
    tooltip("Progress Bar configuration reloaded.", parent=mw, period=2000)


# Define a function to toggle the visibility of the progress bar
def toggleProgressBar():
    global settings
    global config

    progress_bar_enabled = not settings.progress_bar_enabled
    config["progress_bar_enabled"] = progress_bar_enabled
    addon_config.apply_config(mw, config)
    settings = addon_config.settings
    config = settings.raw_config

    if progress_bar_enabled:
        if _should_show_progress_bar_for_state(_progress_state.main_window_state) and progress_ui.progressBar is None:
            initPB()
        if progress_ui.progressBar is not None:
            progress_ui.progressBar.show()
            _ensure_persisted_progress_loaded()
            updateCountsForAllDecks(True)
            updatePB()
        else:
            _remove_progress_bar()
    else:
        _remove_progress_bar()

progress_ui.update_toggle_shortcut(toggleProgressBar)
_install_settings_menu_action()
