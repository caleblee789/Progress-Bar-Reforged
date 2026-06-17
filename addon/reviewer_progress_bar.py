from __future__ import unicode_literals
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple
from copy import deepcopy
from .nightmode import isnightmode
from . import config as addon_config
from .config import (
    Settings,
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _normalize_dimension,
)
from . import history
from .pacing import SessionSample, StabilizedWarning, estimate_pace
from .history import SessionHistoryDialog
from .ui import progress_bar as progress_ui

from anki.hooks import addHook, wrap
from anki import version as anki_version

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

settings: Settings
config: Dict[str, Any] = {}
_validation_errors: List[str] = []

# Set up variables

remainCount: Dict[int, float] = {}
doneCount: Dict[int, float] = {}
totalCount: Dict[int, float] = {}
# Store raw (unweighted) counts alongside weighted counts to ensure accurate numbers in the UI.
rawRemainCount: Dict[int, int] = {}
rawDoneCount: Dict[int, int] = {}
rawTotalCount: Dict[int, int] = {}
# Track actionable (non-buried) and buried queue counts separately per deck so we can
# present an accurate breakdown in the tooltip and ensure "left" only sums actionable cards.
actionableRevCount: Dict[int, int] = {}
actionableLrnCount: Dict[int, int] = {}
actionableNewCount: Dict[int, int] = {}
buriedRevCount: Dict[int, int] = {}
buriedLrnCount: Dict[int, int] = {}
buriedNewCount: Dict[int, int] = {}
# NOTE: did stands for 'deck id'
# For old API of deckDueList(), these counts don't include cards in children decks. For new deck_due_tree(), they do.

currDID: Optional[int] = None  # current deck id (None means at the deck browser)
_warning_active = False
_deck_breakdown_dialog: Optional["DeckBreakdownDialog"] = None
_latest_breakdown_rows: List[Dict[str, Any]] = []
_last_cards_per_minute: Optional[float] = None
_pacing_samples: List[SessionSample] = []
_warning_stabilizer = StabilizedWarning()
_last_ui_update_ts = 0.0
_last_ui_state_signature: Optional[Tuple[int, int, int, int]] = None
_UPDATE_THROTTLE_SECONDS = 0.25
_revlog_cache: Dict[Tuple[Any, ...], Tuple[float, Optional[tuple]]] = {}
_last_animated_progress_value: Optional[int] = None
_completion_state_active = False

def __getattr__(name: str):
    if name in {"progressBar", "toggle_shortcut"}:
        return getattr(progress_ui, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

lrn_weight = 1.0
new_weight = 1.0
rev_weight = 1.0


def _qt_enum(container: Any, scoped_name: str, value_name: str, default: Any = None) -> Any:
    scoped = getattr(container, scoped_name, None)
    if scoped is not None and hasattr(scoped, value_name):
        return getattr(scoped, value_name)
    return getattr(container, value_name, default)


def _dialog_accepted_value() -> Any:
    return _qt_enum(QDialog, "DialogCode", "Accepted", 1)


def _message_box_button(value_name: str) -> Any:
    return _qt_enum(QMessageBox, "StandardButton", value_name)


def _message_box_icon(value_name: str) -> Any:
    return _qt_enum(QMessageBox, "Icon", value_name)


def _pointing_hand_cursor() -> Any:
    return _qt_enum(Qt, "CursorShape", "PointingHandCursor")


def _alignment_flag(value_name: str) -> Any:
    return _qt_enum(Qt, "AlignmentFlag", value_name, 0)


def _arrow_type(value_name: str) -> Any:
    return _qt_enum(Qt, "ArrowType", value_name)


def _tool_button_style(value_name: str) -> Any:
    return _qt_enum(Qt, "ToolButtonStyle", value_name)


def _set_pointing_cursor(widget: Any) -> None:
    if widget is None or not hasattr(widget, "setCursor"):
        return
    cursor = _pointing_hand_cursor()
    if cursor is not None:
        widget.setCursor(cursor)


def _notify_validation_errors(errors: List[str]) -> None:
    if not errors:
        return
    message = "Progress Bar settings adjusted:\n" + "\n".join(errors)
    tooltip(message, parent=mw, period=4000)


def _friendly_action_for_warning(kind: str) -> str:
    actions = {
        "time": "Action: consider pausing new cards or ending this session earlier.",
        "again": "Action: check leeches or suspend difficult cards before continuing.",
        "retention": "Action: slow down and prioritize mature review accuracy.",
        "sm_retention": "Action: inspect mature-card lapses and recent leeches.",
        "pace_cards": "Action: reduce new-card intake or plan a longer review block.",
        "pace_minutes": "Action: increase session length or lower your minutes goal.",
        "pace_cutoff": "Action: review earlier in the day to avoid cutoff rollover.",
    }
    return actions.get(kind, "Action: review your thresholds in Progress Bar settings.")


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
    if mw.col is not None:
        add_info()
    progress_ui.update_toggle_shortcut(toggleProgressBar)
    _reinitialize_progress_bar()


def _pace_warning_effectively_enabled() -> bool:
    if not settings.pace_warnings_enabled:
        return False
    return settings.daily_target_cards > 0 or settings.target_review_minutes > 0


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


def should_run_quick_setup(cfg: Dict[str, Any]) -> bool:
    """Detect whether the onboarding wizard should be shown for this profile."""

    if not cfg:
        return True
    if not _coerce_bool(cfg.get("quick_setup_enabled"), True):
        return False
    return not _coerce_bool(cfg.get("onboarding_completed"), False)


def _save_quick_setup_config(overrides: Dict[str, Any]) -> None:
    updated = dict(config)
    updated.update(overrides)
    updated["onboarding_completed"] = True
    addon_config.apply_config(mw, updated)
    _reload_settings(show_messages=False)


def _open_quick_setup_wizard(force: bool = False) -> None:
    if not force and not should_run_quick_setup(config):
        return

    dialog = QuickSetupWizard(mw)
    if dialog.exec() != _dialog_accepted_value():
        return

    if dialog.skipped:
        _save_quick_setup_config({})
        return

    _save_quick_setup_config(dialog.selected_config())
    _apply_settings(show_messages=False)


_reload_settings(show_messages=True)

PERSISTED_PROGRESS_KEY = "progress_bar_persistent_counts"
HISTORY_PROGRESS_KEY = history.HISTORY_PROGRESS_KEY
_progress_restored = False
_last_persisted_snapshot: Optional[Dict[str, Any]] = None
_last_persisted_ts = 0.0
_PERSIST_INTERVAL_SECONDS = 15.0


def _current_day_stamp() -> int:
    if mw.col is None:
        return 0
    cutoff = getattr(mw.col.sched, "day_cutoff", None)
    if cutoff is None:
        return 0
    return cutoff // 86400


def _prepare_counts_for_new_profile() -> None:
    global _progress_restored
    global _last_persisted_snapshot
    global _last_persisted_ts
    global _last_ui_update_ts
    global _last_ui_state_signature
    remainCount.clear()
    doneCount.clear()
    totalCount.clear()
    rawRemainCount.clear()
    rawDoneCount.clear()
    rawTotalCount.clear()
    actionableRevCount.clear()
    actionableLrnCount.clear()
    actionableNewCount.clear()
    buriedRevCount.clear()
    buriedLrnCount.clear()
    buriedNewCount.clear()
    _progress_restored = False
    _last_persisted_snapshot = None
    _last_persisted_ts = 0.0
    _pacing_samples.clear()
    _revlog_cache.clear()
    _last_ui_update_ts = 0.0
    _last_ui_state_signature = None


def _ensure_persisted_progress_loaded() -> None:
    global _progress_restored

    if _progress_restored:
        return

    if mw.pm is None or mw.col is None:
        return

    profile = getattr(mw.pm, "profile", None)
    if not isinstance(profile, dict):
        _progress_restored = True
        return

    stored = profile.get(PERSISTED_PROGRESS_KEY)
    if not isinstance(stored, dict):
        _progress_restored = True
        return

    today = _current_day_stamp()
    stored_day = stored.get("day")
    if stored_day != today:
        profile.pop(PERSISTED_PROGRESS_KEY, None)
        mw.pm.save()
        _progress_restored = True
        return

    data = stored.get("data")
    if not isinstance(data, dict):
        _progress_restored = True
        return

    for did_key, counts in data.items():
        try:
            did = int(did_key)
        except (TypeError, ValueError):
            continue

        if not isinstance(counts, dict):
            continue

        done = float(counts.get("done", 0.0))
        total = float(counts.get("total", done))
        raw_done = int(counts.get("raw_done", 0))
        raw_total = int(counts.get("raw_total", raw_done))

        if total < done:
            total = done
        if raw_total < raw_done:
            raw_total = raw_done

        doneCount[did] = done
        totalCount[did] = total
        rawDoneCount[did] = raw_done
        rawTotalCount[did] = raw_total

    _progress_restored = True


def _persist_progress_snapshot() -> None:
    global _last_persisted_snapshot
    global _last_persisted_ts

    if mw.pm is None or mw.col is None:
        return

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
    persisted_changed = snapshot != _last_persisted_snapshot
    too_soon = (now - _last_persisted_ts) < _PERSIST_INTERVAL_SECONDS

    if not persisted_changed and too_soon:
        return

    if snapshot:
        profile[PERSISTED_PROGRESS_KEY] = {"day": today, "data": snapshot}
    else:
        profile.pop(PERSISTED_PROGRESS_KEY, None)

    deck_ids_for_query: List[int] = []
    try:
        deck_tree = mw.col.sched.deck_due_tree()
        for node in getattr(deck_tree, "children", []):
            deck_ids_for_query.extend(_collect_deck_ids(node))
        deck_ids_for_query = list(dict.fromkeys(deck_ids_for_query))
        history.update_daily_history(profile, today, deck_ids_for_query, _revlog_stats_between)
    except Exception:
        # Profile close can run while Anki is tearing down scheduler/deck state.
        # Persist counts if possible, but do not block profile shutdown on history.
        pass

    mw.pm.save()
    _last_persisted_snapshot = snapshot
    _last_persisted_ts = now


def add_info():
    # card types: 0=new, 1=lrn, 2=rev, 3=relrn
    # queue types: 0=new, 1=(re)lrn, 2=rev, 3=day (re)lrn,
    #   4=preview, -1=suspended, -2=sibling buried, -3=manually buried

    # revlog types: 0=lrn, 1=rev, 2=relrn, 3=early review
    # positive revlog intervals are in days (rev), negative in seconds (lrn)
    # odue/odid store original due/did when cards moved to filtered deck
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


gui_hooks.main_window_did_init.append(add_info)


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
    progress_ui.reinitialize_progress_bar()
    progress_ui.set_click_handler(_open_deck_breakdown_dialog)
    if settings.progress_bar_enabled and mw.col is not None:
        _ensure_persisted_progress_loaded()
        updateCountsForAllDecks(True)
        updatePB()


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
    """Return counts of completed cards by deck, grouped by card state.

    Deck IDs are resolved against the original deck for cards that were
    reviewed in a filtered deck so that progress attaches to the owning deck.
    """
    rows = mw.col.db.all(
        """
        select
            coalesce(nullif(c.odid, 0), c.did) as deck_id,
            sum(case when c.type = 2 then 1 else 0 end) as rev_done,
            sum(case when c.type in (1, 3) then 1 else 0 end) as lrn_done,
            sum(case when c.type = 0 then 1 else 0 end) as new_done
        from revlog r
        join cards c on c.id = r.cid
        where r.id > ?
        group by deck_id
        """,
        cutoff,
    )

    done_by_deck: Dict[int, Tuple[int, int, int]] = {}
    for deck_id, rev_done, lrn_done, new_done in rows:
        done_by_deck[int(deck_id)] = (
            int(rev_done or 0),
            int(lrn_done or 0),
            int(new_done or 0),
        )
    return done_by_deck


def _queue_counts_for_node(node) -> Tuple[int, int, int, int, int, int]:
    """Return the remaining queue counts for the provided deck tree node.

    The raw deck tree counts provided by the scheduler already factor in
    deck limits and due dates, but they can still include cards that are
    temporarily hidden from the reviewer (for example, buried siblings).
    To keep the progress bar aligned with what the reviewer will
    actually see, we combine both data sources: we cap the active card
    counts derived from the cards table to the scheduler's notion of how
    many cards are due today. This prevents cards that are merely
    unsuspended but not due from inflating the "left" number and excludes
    intraday buried cards from the remaining total."""

    deck_ids = list(dict.fromkeys(_collect_deck_ids(node)))

    # Scheduler-provided limits for the deck (already respects child decks).
    sched_rev = int(getattr(node, "review_count", 0) or 0)
    sched_lrn = int(getattr(node, "learn_count", 0) or 0)
    sched_new = int(getattr(node, "new_count", 0) or 0)

    if not deck_ids:
        return sched_rev, sched_lrn, sched_new, 0, 0, 0

    placeholders = ",".join(["?"] * len(deck_ids))
    visible_query = f"""
        select
            sum(case when queue = 2 then 1 else 0 end),
            sum(case when queue in (1, 3) then 1 else 0 end),
            sum(case when queue = 0 then 1 else 0 end),
            sum(case when queue in (-2, -3) and type = 2 then 1 else 0 end),
            sum(case when queue in (-2, -3) and type in (1, 3) then 1 else 0 end),
            sum(case when queue in (-2, -3) and type = 0 then 1 else 0 end)
        from cards
        where queue in (0, 1, 2, 3, -2, -3)
          and did in ({placeholders})
    """

    counts = mw.col.db.first(visible_query, *deck_ids) or (0, 0, 0, 0, 0, 0)
    raw_rev, raw_lrn, raw_new, buried_rev, buried_lrn, buried_new = (
        int(count or 0) for count in counts
    )

    # Cards with queue -2/-3 are hidden for now, but they'll still need to be
    # reviewed later in the day. The scheduler counts already reflect deck
    # limits, so we cap the visible cards to that limit. Buried cards are
    # intentionally excluded so that the remaining total only reflects cards
    # that can actually appear during the current session.
    rev_visible = min(raw_rev, sched_rev)
    lrn_visible = min(raw_lrn, sched_lrn)

    # When the scheduler includes buried new siblings in its deck limits, trim
    # them out so the remaining count only reflects cards that can actually
    # appear. Only subtract the portion that may be inflating the scheduler
    # total to avoid under-counting when the scheduler already excluded buried
    # cards (or the deck limit is lower than the actionable new supply).
    buried_overhang = max(0, sched_new - raw_new)
    buried_overlap = min(buried_new, buried_overhang)
    sched_new_visible = max(0, sched_new - buried_overlap)
    new_visible = min(raw_new, sched_new_visible)

    rev_count = rev_visible
    lrn_count = lrn_visible
    new_count = new_visible

    return rev_count, lrn_count, new_count, buried_rev, buried_lrn, buried_new


def _revlog_stats_since(cutoff: int, deck_ids: List[int]):
    cache_key = ("since", cutoff, *deck_ids)
    cached = _revlog_cache.get(cache_key)
    if cached and (time.monotonic() - cached[0]) < 1.5:
        return cached[1]

    base_query = """
        select
        sum(case when r.ease >= 1 then 1 else 0 end),
        sum(case when r.ease = 1 then 1 else 0 end),
        sum(case when r.ease = 1 and r.type = 1 then 1 else 0 end),
        sum(case when r.ease > 1 and r.type = 1 then 1 else 0 end),
        sum(case when r.ease > 1 and r.type = 1 and r.lastIvl >= 100 then 1 else 0 end),
        sum(case when r.ease = 1 and r.type = 1 and r.lastIvl >= 100 then 1 else 0 end),
        sum(r.time)/1000
        from revlog r
    """

    if not deck_ids:
        query = base_query + """
        where r.id > ?
    """
        params: List[int] = [cutoff]
    else:
        placeholders = ",".join(["?"] * len(deck_ids))
        # Include original deck id for cards coming from filtered decks.
        query = base_query + f"""
        join cards c on c.id = r.cid
        where r.id > ?
          and (c.did in ({placeholders}) or (c.odid != 0 and c.odid in ({placeholders})))
    """
        params = [cutoff] + deck_ids + deck_ids

    result = mw.col.db.first(query, *params)
    _revlog_cache[cache_key] = (time.monotonic(), result)
    return result


def _revlog_stats_between(start: int, end: int, deck_ids: List[int]):
    """Aggregate revlog metrics between two cutoffs (inclusive).

    Mirrors the columns returned by _revlog_stats_since.
    """
    base_query = """
        select
        sum(case when r.ease >= 1 then 1 else 0 end),
        sum(case when r.ease = 1 then 1 else 0 end),
        sum(case when r.ease = 1 and r.type = 1 then 1 else 0 end),
        sum(case when r.ease > 1 and r.type = 1 then 1 else 0 end),
        sum(case when r.ease > 1 and r.type = 1 and r.lastIvl >= 100 then 1 else 0 end),
        sum(case when r.ease = 1 and r.type = 1 and r.lastIvl >= 100 then 1 else 0 end),
        sum(r.time)/1000
        from revlog r
    """

    if not deck_ids:
        query = base_query + """
        where r.id between ? and ?
    """
        params: List[int] = [start, end]
    else:
        placeholders = ",".join(["?"] * len(deck_ids))
        query = base_query + f"""
        join cards c on c.id = r.cid
        where r.id between ? and ?
          and (c.did in ({placeholders}) or (c.odid != 0 and c.odid in ({placeholders})))
    """
        params = [start, end] + deck_ids + deck_ids

    return mw.col.db.first(query, *params)


def _current_tzinfo():
    tzinfo = (
        datetime.now().astimezone().tzinfo
        if settings.use_system_timezone
        else timezone(timedelta(hours=settings.tz))
    )
    return tzinfo or timezone.utc


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


def _resolve_deck_profile(deck_id: int) -> Dict[str, float]:
    raw_profiles = settings.deck_profiles if isinstance(settings.deck_profiles, dict) else {}
    profile = raw_profiles.get(str(deck_id), {}) if raw_profiles else {}
    if not isinstance(profile, dict):
        profile = {}
    return {
        "new_weight": float(profile.get("new_weight", new_weight)),
        "lrn_weight": float(profile.get("lrn_weight", lrn_weight)),
        "rev_weight": float(profile.get("rev_weight", rev_weight)),
        "expected_seconds": float(profile.get("expected_seconds", 0.0)),
    }


def _calc_weighted_with_profile(deck_id: int, rev: int, lrn: int, new: int) -> float:
    profile = _resolve_deck_profile(deck_id)
    ret = 0.0
    if settings.include_rev:
        ret += rev * profile["rev_weight"]
    if settings.include_lrn:
        ret += lrn * profile["lrn_weight"]
    if settings.include_new or (settings.include_new_after_revs and rev == 0):
        ret += new * profile["new_weight"]
    return ret


def _collect_segmented_samples(deck_ids: List[int]) -> List[float]:
    deck_set = set(deck_ids)
    return [sample.seconds_per_card for sample in _pacing_samples if any(d in deck_set for d in sample.deck_key)]


def _target_nodes_for_progress(deck_tree) -> List[Any]:
    if settings.count_scope == "global" or currDID is None:
        return list(getattr(deck_tree, "children", []))

    node = _find_node_by_id(deck_tree, currDID)
    if node is None:
        return list(getattr(deck_tree, "children", []))
    return [node]


def _expected_seconds_for_decks(deck_ids: List[int]) -> float:
    expected = 0.0
    for deck_id in deck_ids:
        profile = _resolve_deck_profile(deck_id)
        seconds_per_card = max(0.0, profile.get("expected_seconds", 0.0))
        if seconds_per_card <= 0:
            continue
        expected += rawRemainCount.get(deck_id, 0) * seconds_per_card
    return expected


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
    global _latest_breakdown_rows
    tzinfo = _current_tzinfo()
    _latest_breakdown_rows = [
        _deck_breakdown_for_node(node, cards_per_minute, tzinfo) for node in target_nodes
    ]
    _refresh_breakdown_dialog()


def _refresh_breakdown_dialog() -> None:
    if _deck_breakdown_dialog is not None:
        _deck_breakdown_dialog.update_rows(_latest_breakdown_rows)


def _open_deck_breakdown_dialog() -> None:
    global _deck_breakdown_dialog

    if _deck_breakdown_dialog is None:
        _deck_breakdown_dialog = DeckBreakdownDialog(mw)

    _deck_breakdown_dialog.update_rows(_latest_breakdown_rows)
    _deck_breakdown_dialog.show()
    _deck_breakdown_dialog.raise_()
    _deck_breakdown_dialog.activateWindow()


def _is_compact_layout(width: int, responsive_breakpoints: bool) -> bool:
    return bool(responsive_breakpoints and width < 760)


def _join_metric_parts(parts: List[str], compact: bool) -> str:
    separator = " · " if compact else "     |     "
    return separator.join(part for part in parts if part)


def _format_hierarchical_progress_text(
    primary_parts: List[str],
    secondary_parts: List[str],
    *,
    hierarchy_style: str,
    compact_separators: bool,
    vertical: bool,
    vertical_line_break: bool,
) -> str:
    primary_text = _join_metric_parts(primary_parts, compact_separators)
    secondary_text = _join_metric_parts(secondary_parts, compact_separators)

    if hierarchy_style == "two_line" and secondary_text:
        return f"{primary_text}\n{secondary_text}" if primary_text else secondary_text
    if vertical and vertical_line_break and primary_text and secondary_text:
        return f"{primary_text}\n{secondary_text}"
    if primary_text and secondary_text:
        return _join_metric_parts([primary_text, secondary_text], compact_separators)
    return primary_text or secondary_text


def _format_bar_label_compact(percent: float, raw_done: int, raw_total: int, eta_text: str) -> str:
    return f"{percent:.0f}% • {raw_done}/{raw_total} • {eta_text}"


def _format_bar_label_detailed(
    percent: float,
    raw_done: int,
    raw_total: int,
    again: Optional[str],
    retention: Optional[str],
    eta_text: str,
) -> str:
    parts = [f"{percent:.0f}%", f"{raw_done}/{raw_total}"]
    if again:
        parts.append(f"Again {again}")
    if retention:
        parts.append(f"Ret {retention}")
    parts.append(eta_text)
    return " • ".join(parts)


def _build_structured_tooltip(
    tooltip_lines: List[str],
    warning_messages: List[Tuple[str, str]],
    pace_warning_messages: List[Tuple[str, str]],
    show_debug: bool,
) -> str:
    sections = ["Today"]
    sections.extend(line for line in tooltip_lines if line)
    if warning_messages or pace_warning_messages:
        sections.append("\nWarnings")
        for _, line in warning_messages + pace_warning_messages:
            sections.append(f"• {line}")
    if show_debug:
        debug_lines = [line for line in tooltip_lines if "Weight applied" in line or "Pacing model" in line]
        if debug_lines:
            sections.append("\n── Debug ──")
            sections.extend(debug_lines)
    return "\n".join(sections)


def _interpolate_progress_value(previous: Optional[int], target: int, enabled: bool) -> int:
    if not enabled or previous is None:
        return target
    delta = target - previous
    next_value = previous + int(round(delta * 0.35))
    if delta > 0:
        return min(next_value, target)
    if delta < 0:
        return max(next_value, target)
    return target


def updatePB():
    # Get studied cards  and true retention stats. TODAY'S VALUES

    # If the progress bar isn't initialized yet, there's nothing to update.
    if progress_ui.progressBar is None:
        return

    global _last_ui_update_ts
    global _last_ui_state_signature

    now = time.monotonic()
    state_signature = (
        int(sum(rawDoneCount.values())),
        int(sum(rawRemainCount.values())),
        int(currDID or 0),
        int(bool(_deck_breakdown_dialog)),
    )
    if _last_ui_state_signature == state_signature and (now - _last_ui_update_ts) < _UPDATE_THROTTLE_SECONDS:
        return
    _last_ui_state_signature = state_signature
    _last_ui_update_ts = now

    a = (mw.col.sched.day_cutoff - 86400) * 1000

    deck_tree = mw.col.sched.deck_due_tree()
    target_nodes = _target_nodes_for_progress(deck_tree)

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

    if raw_done > 0:
        safe_time = max(thetime, 1)
        secspeed_value = safe_time / raw_done
        secspeed_display = f"{secspeed_value:.02f}"
        sample = SessionSample(seconds_per_card=secspeed_value, deck_key=tuple(deck_ids_for_query))
        if not _pacing_samples or abs(_pacing_samples[-1].seconds_per_card - sample.seconds_per_card) > 1e-6:
            _pacing_samples.append(sample)
            if len(_pacing_samples) > 240:
                del _pacing_samples[: len(_pacing_samples) - 240]
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

    segmented_samples = _collect_segmented_samples(deck_ids_for_query)
    pace_estimate = estimate_pace(
        settings.pacing_strategy,
        [s.seconds_per_card for s in _pacing_samples],
        segmented_samples=segmented_samples,
    )
    if pace_estimate is None and raw_done > 0:
        pace_estimate = estimate_pace("average", [secspeed_value])

    if pace_estimate is not None:
        speed = pace_estimate.cards_per_minute
        seconds_remaining = int(round((var_diff / max(speed, 1e-6)) * 60))
    else:
        speed = 0.0
        seconds_remaining = int(round(_expected_seconds_for_decks(deck_ids_for_query)))

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
    pace_warning_messages: List[Tuple[str, str]] = []

    # Time spent today (hours:minutes)
    x = math.floor(thetime / 3600)
    y = math.floor((thetime - (x * 3600)) / 60)

    # Break down remaining into hours/minutes for display
    hrhr = seconds_remaining // 3600
    hrmin = (seconds_remaining % 3600) // 60

    # ETA display using system timezone by default, or the configured offset when overridden
    eta_display = "N/A"
    if seconds_remaining > 0:
        tzinfo = datetime.now().astimezone().tzinfo if settings.use_system_timezone else timezone(timedelta(hours=settings.tz))
        tzinfo = tzinfo or timezone.utc
        eta_display = _format_eta_time(seconds_remaining, tzinfo)
    has_remaining_time_estimate = seconds_remaining > 0

    cutoff_seconds = 0
    if mw.col is not None and getattr(mw.col, "sched", None) is not None:
        try:
            cutoff_seconds = max(0, int(round(mw.col.sched.day_cutoff - time.time())))
        except Exception:
            cutoff_seconds = 0

    progress_scale = 1000
    progress_max = int(round(weighted_total * progress_scale))
    progress_value = int(round(weighted_done * progress_scale))

    global _last_animated_progress_value
    if progress_max <= 0:
        progress_ui.progressBar.setRange(0, 1)
        progress_ui.progressBar.setValue(1)
        _last_animated_progress_value = 1
    else:
        progress_ui.progressBar.setRange(0, progress_max)
        target_value = min(progress_value, progress_max)
        use_animation = settings.animated_updates and not settings.reduced_motion
        animated_value = _interpolate_progress_value(_last_animated_progress_value, target_value, use_animation)
        progress_ui.progressBar.setValue(animated_value)
        _last_animated_progress_value = animated_value

    warning_messages: List[Tuple[str, str]] = []
    warning_summary_parts: List[str] = []
    warning_active = False
    hysteresis = settings.warning_hysteresis_percent
    cooldown = settings.warning_cooldown_seconds
    if settings.warnings_enabled:
        if settings.time_warning_minutes > 0:
            if _warning_stabilizer.evaluate(
                "time", seconds_remaining / 60.0, float(settings.time_warning_minutes), higher_is_worse=True, hysteresis=hysteresis, cooldown_s=cooldown
            ):
                warning_active = True
                warning_messages.append(("time", f"Time warning: projected remaining time {seconds_remaining / 60.0:.0f}m exceeds threshold {settings.time_warning_minutes}m."))
                warning_summary_parts.append(f"T>{settings.time_warning_minutes}m")
        if settings.again_warning_percent > 0 and again_value is not None:
            if _warning_stabilizer.evaluate(
                "again", again_value, float(settings.again_warning_percent), higher_is_worse=True, hysteresis=hysteresis, cooldown_s=cooldown
            ):
                warning_active = True
                warning_messages.append(("again", f"Again warning: current {again_value:.1f}% vs threshold {settings.again_warning_percent:.0f}% (higher is worse)."))
                warning_summary_parts.append(f"AG≥{settings.again_warning_percent:.0f}%")
        if settings.retention_warning_percent > 0:
            if temp_value is not None and _warning_stabilizer.evaluate(
                "retention", temp_value, float(settings.retention_warning_percent), higher_is_worse=False, hysteresis=hysteresis, cooldown_s=cooldown
            ):
                warning_active = True
                warning_messages.append(("retention", f"Retention warning: current {temp_value:.1f}% vs threshold {settings.retention_warning_percent:.0f}% (lower is worse)."))
                warning_summary_parts.append(f"TR<{settings.retention_warning_percent:.0f}%")
            if temp_supermature_value is not None and _warning_stabilizer.evaluate(
                "sm_retention", temp_supermature_value, float(settings.retention_warning_percent), higher_is_worse=False, hysteresis=hysteresis, cooldown_s=cooldown
            ):
                warning_active = True
                warning_messages.append(("sm_retention", f"Super-mature retention warning: current {temp_supermature_value:.1f}% vs threshold {settings.retention_warning_percent:.0f}%."))
                warning_summary_parts.append(f"SM<{settings.retention_warning_percent:.0f}%")

    projected_finish_after_cutoff: Optional[int] = None
    if seconds_remaining > 0 and cutoff_seconds > 0:
        projected_finish_after_cutoff = seconds_remaining - cutoff_seconds

    if _pace_warning_effectively_enabled():
        if cards_vs_goal is not None:
            done_cards, goal_cards = cards_vs_goal
            if goal_cards > 0 and done_cards < goal_cards and speed > 0 and raw_total > 0:
                projected_cards = done_cards + (seconds_remaining * speed / 60)
                if projected_cards + 1e-6 < goal_cards:
                    warning_active = True
                    pace_warning_messages.append(("pace_cards", f"Pace warning: projected cards {projected_cards:.0f} below goal {goal_cards}."))
                    warning_summary_parts.append("Cards<goal")
        if time_vs_goal is not None and projected_minutes is not None and minute_goal > 0:
            if elapsed_minutes + projected_minutes < minute_goal - 1e-6:
                warning_active = True
                pace_warning_messages.append(("pace_minutes", f"Pace warning: projected reviewed minutes {elapsed_minutes + projected_minutes:.0f} below goal {minute_goal}."))
                warning_summary_parts.append("Time<goal")
        if projected_finish_after_cutoff is not None and projected_finish_after_cutoff > 0:
            warning_active = True
            minutes_past = projected_finish_after_cutoff / 60.0
            pace_warning_messages.append(("pace_cutoff", f"Pace warning: projected finish {minutes_past:.0f}m after today's cutoff."))
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
            goal_tooltip_lines.append(f"Projected total time at current pace: {projected_total_minutes:.0f} minutes.")


    goal_status = "On track"
    if cards_vs_goal is not None and remaining_cards_goal is not None and raw_remain > remaining_cards_goal:
        goal_status = "Behind"
    elif cards_vs_goal is not None and remaining_cards_goal == 0:
        goal_status = "Ahead"
    goal_tooltip_lines.append(f"Goal status: {goal_status}.")
    if projected_finish_after_cutoff is not None and cutoff_seconds > 0:
        cutoff_delta_minutes = projected_finish_after_cutoff / 60.0
        if projected_finish_after_cutoff > 0:
            goal_tooltip_lines.append(f"Projected to finish {cutoff_delta_minutes:.0f} minutes after today's cutoff.")
        else:
            goal_tooltip_lines.append(f"Projected to finish {abs(cutoff_delta_minutes):.0f} minutes before today's cutoff.")

    output = ""
    primary_parts: List[str] = []
    secondary_parts: List[str] = []

    if settings.show_number:
        if settings.show_percent:
            done_total_text = f"{raw_done}/{raw_total} ({percent:.02f}%)"
            queue_left_text = f"Left {var_diff:.0f} ({percentdiff:.02f}%)"
            tooltip_lines.append(
                f"Cards completed: {raw_done} ({percent:.02f}% of today's total)."
            )
            completed_tooltip_lines.append(
                f"Cards completed: {raw_done} ({percent:.02f}% of today's total)."
            )
            tooltip_lines.append(
                f"Cards remaining: {var_diff:.0f} ({percentdiff:.02f}% of today's session)."
            )
            remaining_tooltip_lines.append(
                f"Cards remaining: {var_diff:.0f} ({percentdiff:.02f}% of today's session)."
            )
        else:
            done_total_text = f"{raw_done}/{raw_total}"
            queue_left_text = f"Left {var_diff:.0f}"
            tooltip_lines.append(f"Cards completed so far today: {raw_done}.")
            tooltip_lines.append(f"Cards remaining in the active queues: {var_diff:.0f}.")
            completed_tooltip_lines.append(f"Cards completed so far today: {raw_done}.")
            remaining_tooltip_lines.append(
                f"Cards remaining in the active queues: {var_diff:.0f}."
            )

        if has_remaining_time_estimate:
            eta_text = f"ETA {eta_display}"
            if settings.show_eta_confidence and pace_estimate is not None:
                eta_text += f" ({pace_estimate.confidence})"
            tooltip_lines.append(
                f"Estimated finish time adjusted for your {'system' if settings.use_system_timezone else 'custom'} timezone: {eta_display}."
            )
            eta_basis = (
                "recent cards/minute pace and becomes more reliable as more cards are reviewed"
                if pace_estimate is not None
                else "configured deck expected seconds until today's pace data is available"
            )
            tooltip_lines.append(f"ETA uses {eta_basis}.")
            if pace_estimate is not None:
                if settings.show_debug:
                    tooltip_lines.append(f"Pacing model: {settings.pacing_strategy} ({pace_estimate.samples} samples, variance {pace_estimate.variance:.2f}, confidence {pace_estimate.confidence}).")
            remaining_tooltip_lines.append(
                f"Estimated finish time adjusted for your {'system' if settings.use_system_timezone else 'custom'} timezone: {eta_display}."
            )
            remaining_tooltip_lines.append(f"ETA uses {eta_basis}.")
        else:
            eta_text = "ETA N/A"
            tooltip_lines.append(
                "Projected time remaining is unavailable until at least one card is answered."
            )
            tooltip_lines.append(
                "Estimated finish time unavailable until progress is made."
            )
            remaining_tooltip_lines.append(
                "Projected time remaining is unavailable until at least one card is answered."
            )

        primary_parts.extend([done_total_text, eta_text])
        secondary_parts.append(queue_left_text)

        if settings.show_yesterday:
            secondary_parts.append(f"{secspeed_display} ({ysecspeed_display}) s/card")
            tooltip_lines.append(
                "Seconds per card today (yesterday in parentheses)."
            )
            completed_tooltip_lines.append(
                "Seconds per card today (yesterday in parentheses)."
            )
        else:
            secondary_parts.append(f"{secspeed_display} s/card")
            tooltip_lines.append(
                "Average seconds spent per card for the current session."
            )
            completed_tooltip_lines.append(
                "Average seconds spent per card for the current session."
            )

        if settings.show_again:
            tooltip_lines.append("Again % = the share of answers marked Again today (lower is better).")
            completed_tooltip_lines.append("Again % = the share of answers marked Again today (lower is better).")
            if settings.show_yesterday:
                secondary_parts.append(f"{again} ({y_again}) Again")
                tooltip_lines.append(
                    "Again answers today (yesterday in parentheses)."
                )
                completed_tooltip_lines.append(
                    "Again answers today (yesterday in parentheses)."
                )
            else:
                secondary_parts.append(f"{again} Again")
                tooltip_lines.append("Again answers given during today's reviews.")
                completed_tooltip_lines.append(
                    "Again answers given during today's reviews."
                )
        if settings.show_retention:
            tooltip_lines.append("True retention = passed / (passed + failed mature reviews).")
            completed_tooltip_lines.append("True retention = passed / (passed + failed mature reviews).")
            if settings.show_yesterday:
                secondary_parts.append(f"{temp} ({ytemp}) TR")
                tooltip_lines.append(
                    "Today's true retention percentage (yesterday in parentheses)."
                )
                completed_tooltip_lines.append(
                    "Today's true retention percentage (yesterday in parentheses)."
                )
            else:
                secondary_parts.append(f"{temp} TR")
                tooltip_lines.append("Today's true retention percentage.")
                completed_tooltip_lines.append("Today's true retention percentage.")
        if settings.show_super_mature_retention:
            tooltip_lines.append("Super-mature retention is retention on very mature cards only.")
            completed_tooltip_lines.append("Super-mature retention is retention on very mature cards only.")
            if settings.show_yesterday:
                secondary_parts.append(f"{temp_supermature} ({ytemp_supermature}) SMTR")
                tooltip_lines.append(
                    "Super-mature retention rate today (yesterday in parentheses)."
                )
                completed_tooltip_lines.append(
                    "Super-mature retention rate today (yesterday in parentheses)."
                )
            else:
                secondary_parts.append(f"{temp_supermature} SMTR")
                tooltip_lines.append("Super-mature retention rate for today's reviews.")
                completed_tooltip_lines.append(
                    "Super-mature retention rate for today's reviews."
                )

        secondary_parts.append(f"{x:02d}:{y:02d} spent")
        tooltip_lines.append(
            f"Time spent reviewing so far today: {x:02d}:{y:02d}."
        )
        completed_tooltip_lines.append(
            f"Time spent reviewing so far today: {x:02d}:{y:02d}."
        )

        if goal_text_parts:
            secondary_parts.append("Goal " + " · ".join(goal_text_parts) + f" [{goal_status}]")

        if has_remaining_time_estimate:
            secondary_parts.append(f"{hrhr:02d}:{hrmin:02d} more")
            tooltip_lines.append(
                "Projected time remaining based on your current pace." if pace_estimate is not None else "Projected time remaining based on configured deck expected seconds."
            )
            remaining_tooltip_lines.append(
                "Projected time remaining based on your current pace." if pace_estimate is not None else "Projected time remaining based on configured deck expected seconds."
            )

        if settings.show_debug:
            secondary_parts.extend([
                f"{new_weight:.02f} New Weight",
                f"{lrn_weight:.02f} Lrn Weight",
                f"{rev_weight:.02f} Rev Weight",
            ])
            tooltip_lines.append(
                f"Weight applied to new cards when calculating progress: {new_weight:.02f}."
            )
            completed_tooltip_lines.append(
                f"Weight applied to new cards when calculating progress: {new_weight:.02f}."
            )
            tooltip_lines.append(
                f"Weight applied to learning cards in the progress formula: {lrn_weight:.02f}."
            )
            completed_tooltip_lines.append(
                f"Weight applied to learning cards in the progress formula: {lrn_weight:.02f}."
            )
            tooltip_lines.append(
                f"Weight applied to review cards in the progress formula: {rev_weight:.02f}."
            )
            completed_tooltip_lines.append(
                f"Weight applied to review cards in the progress formula: {rev_weight:.02f}."
            )

        output = _format_hierarchical_progress_text(
            primary_parts,
            secondary_parts,
            hierarchy_style=settings.text_hierarchy_style,
            compact_separators=settings.compact_separators,
            vertical=settings.orientation == Qt.Orientation.Vertical,
            vertical_line_break=settings.vertical_text_line_break,
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
    tooltip_lines.append("Left excludes buried cards (shown as +).")
    remaining_tooltip_lines.extend(breakdown_lines)
    remaining_tooltip_lines.append("Left excludes buried cards (shown as +).")

    warning_summary_text: Optional[str] = None
    if settings.warnings_enabled or settings.pace_warnings_enabled:
        if warning_summary_parts:
            metric_parts = [part for part in warning_summary_parts if part.startswith(("T>", "AG", "TR", "SM"))]
            pace_parts = [part for part in warning_summary_parts if part not in metric_parts]
            labels: List[str] = []
            if metric_parts:
                labels.append("Metrics:" + ", ".join(metric_parts))
            if pace_parts:
                labels.append("Pace:" + ", ".join(pace_parts))
            warning_summary_text = "Warnings " + " | ".join(labels)
        else:
            warning_summary_text = "Warnings: None active"
        tooltip_lines.append(warning_summary_text + ".")
        completed_tooltip_lines.append(warning_summary_text + ".")
        remaining_tooltip_lines.append(warning_summary_text + ".")

    if settings.pace_warnings_enabled and not _pace_warning_effectively_enabled():
        hidden_msg = "Pace warnings are hidden because both daily_target_cards and target_review_minutes are 0."
        tooltip_lines.append(hidden_msg)
        completed_tooltip_lines.append(hidden_msg)
        remaining_tooltip_lines.append(hidden_msg)

    all_warning_messages: List[Tuple[str, str]] = warning_messages + pace_warning_messages
    if all_warning_messages:
        tooltip_lines.append("")
        completed_tooltip_lines.append("")
        remaining_tooltip_lines.append("")
        for warning_kind, warning_text in all_warning_messages:
            action_text = _friendly_action_for_warning(warning_kind)
            tooltip_lines.extend([warning_text, action_text])
            completed_tooltip_lines.extend([warning_text, action_text])
            remaining_tooltip_lines.extend([warning_text, action_text])

    if tooltip_lines:
        default_tooltip = _build_structured_tooltip(tooltip_lines, warning_messages, pace_warning_messages, settings.show_debug)
    else:
        default_tooltip = (
            "Progress metrics are hidden. Enable numbers in the add-on settings to view details."
        )

    completed_tooltip = default_tooltip
    remaining_tooltip = default_tooltip
    progress_fraction = 0.0
    if progress_max > 0:
        progress_fraction = min(1.0, max(0.0, progress_value / progress_max))

    if settings.stacked_segments and isinstance(progress_ui.progressBar, progress_ui.SegmentedProgressBar):
        progress_ui.progressBar.setSegmentData(
            actionable_new_total,
            actionable_lrn_total,
            actionable_rev_total,
            progress_fraction,
            show_inline_labels=settings.show_segment_inline_labels,
            focus_mode=settings.focus_mode,
        )
    progress_ui.update_progress_legend(
        actionable_new_total,
        actionable_lrn_total,
        actionable_rev_total,
    )

    compact_layout = _is_compact_layout(progress_ui.progressBar.width(), settings.responsive_breakpoints)
    focus_mode = settings.focus_mode

    eta_label = eta_text if eta_text else "ETA N/A"
    if focus_mode:
        format_output = f"{percent:.0f}% complete"
    elif settings.label_style == "compact":
        format_output = _format_bar_label_compact(percent, raw_done, raw_total, eta_label)
    elif compact_layout and output and settings.text_hierarchy_style != "two_line":
        format_output = f"{raw_done}/{raw_total} ({percent:.0f}%)"
    else:
        format_output = _format_bar_label_detailed(
            percent,
            raw_done,
            raw_total,
            again if settings.show_again else None,
            temp if settings.show_retention else None,
            eta_label,
        )

    if settings.show_warning_badge and warning_summary_text:
        if format_output:
            format_output = _join_metric_parts([format_output, warning_summary_text], settings.compact_separators)
        else:
            format_output = warning_summary_text
    if warning_active:
        if settings.show_warning_badge:
            format_output = ("⚠ " + format_output).strip() if format_output else "⚠"
        else:
            format_output = (format_output + " ⚠").strip() if format_output else "⚠"

    is_complete = raw_total > 0 and raw_done >= raw_total
    if is_complete and settings.completion_celebration and not focus_mode:
        format_output = (format_output + "  ✓ Queue complete").strip()

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

    global _last_cards_per_minute
    _last_cards_per_minute = speed if speed > 0 else None
    _update_breakdown_rows(target_nodes, _last_cards_per_minute)

    _persist_progress_snapshot()

    progress_ui.nmApplyStyle()


def setScrollingPB() -> None:
    """Make progress bar in waiting style if the state is resetRequired (happened after editing cards.)"""
    if progress_ui.progressBar is None:
        return
    progress_ui.set_scrolling_bar_state()


def nmApplyStyle() -> None:
    """Checks whether Night_Mode is disabled:
        if so, we remove the separator here."""
    global nmStyleApplied
    if not nmUnavailable:
        try:
            nmStyleApplied = Night_Mode.nm_state_on
        except Exception:
            nmStyleApplied = 0
    if not nmStyleApplied:
        mw.setStyleSheet(
            '''
        QMainWindow::separator
    {
        width: 0px;
        height: 0px;
    }
    ''')

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

    remain = _calc_weighted_with_profile(did, rev_count, lrn_count, new_count)
    raw_remain = calcRawCounts(rev_count, lrn_count, new_count)

    weighted_done = _calc_weighted_with_profile(did, rev_done, lrn_done, new_done)
    updateCountsForDeck(did, remain, raw_remain, rev_done, lrn_done, new_done, weighted_done, updateTotal)

    for child in node.children:
        updateCountsForTree(child, updateTotal, done_by_deck)


def updateCountsForDeck(
    did: int,
    remain: float,
    raw_remain: int,
    rev_done: int,
    lrn_done: int,
    new_done: int,
    weighted_done: float,
    updateTotal: bool,
) -> None:
    previous_total = totalCount.get(did, 0.0)
    previous_raw_total = rawTotalCount.get(did, 0)

    remainCount[did] = remain
    rawRemainCount[did] = raw_remain

    raw_done_total = rev_done + lrn_done + new_done
    if settings.counting_basis == "seen" and not updateTotal:
        weighted_done = max(weighted_done, previous_total - remain)
        raw_done_total = max(raw_done_total, previous_raw_total - raw_remain)

    rawDoneCount[did] = max(0, raw_done_total)
    doneCount[did] = max(0.0, weighted_done)

    if updateTotal and settings.force_forward:
        totalCount[did] = max(totalCount.get(did, 0.0), doneCount[did] + remainCount[did])
        rawTotalCount[did] = max(rawTotalCount.get(did, 0), rawDoneCount[did] + rawRemainCount[did])
    else:
        totalCount[did] = doneCount[did] + remainCount[did]
        rawTotalCount[did] = rawDoneCount[did] + rawRemainCount[did]


def afterStateChangeCallBack(state: str, _old_state: str) -> None:
    global currDID

    if not settings.progress_bar_enabled:
        _remove_progress_bar()
        return

    if state == "resetRequired":
        if settings.scrolling_bar_when_editing:
            setScrollingPB()
        return
    elif state == "deckBrowser":
        # initPB() has to be here, since objects are not prepared yet when the add-on is loaded.
        if not progress_ui.progressBar and settings.progress_bar_enabled:
            initPB()
        currDID = None
    elif state == "profileManager":
        # fixes the issue with multiple profiles
        return
    else:  # "overview" or "review"
        # showInfo("mw.col.decks.current()['id'])= %d" % mw.col.decks.current()['id'])
        currDID = mw.col.decks.current()['id']

    # showInfo("updateCountsForAllDecks(True), currDID = %d" % (currDID if currDID else 0))
    _ensure_persisted_progress_loaded()
    updateCountsForAllDecks(True)  # see comments at updateCountsForAllDecks()
    updatePB()


def showQuestionCallBack() -> None:
    # showInfo("updateCountsForAllDecks(False), currDID = %d" % (currDID if currDID else 0))
    if not settings.progress_bar_enabled:
        return
    updateCountsForAllDecks(False)  # see comments at updateCountsForAllDecks()
    updatePB()


addHook("afterStateChange", afterStateChangeCallBack)
addHook("showQuestion", showQuestionCallBack)


def _on_profile_did_open() -> None:
    _prepare_counts_for_new_profile()


def _on_profile_will_close() -> None:
    _persist_progress_snapshot()


gui_hooks.profile_did_open.append(_on_profile_did_open)
gui_hooks.profile_will_close.append(_on_profile_will_close)


def _ui_palette() -> Dict[str, str]:
    if isnightmode():
        return {
            "window_bg": "#0b1220",
            "primary_text": "#e5e7eb",
            "secondary_text": "#cbd5e1",
            "muted_text": "#9ca3af",
            "helper_text": "#a5b2c5",
            "section_header_text": "#e5e7eb",
            "tab_border": "#1f2937",
            "tab_selected_bg": "#111827",
            "tab_selected_text": "#e5e7eb",
            "tab_selected_border": "#334155",
            "tab_selected_bottom": "#60a5fa",
            "tab_unselected_text": "#94a3b8",
            "tab_hover_bg": "#1f2937",
            "card_bg": "#111827",
            "card_border": "rgba(255, 255, 255, 0.08)",
            "advanced_bg": "#0f172a",
            "advanced_border": "rgba(255, 255, 255, 0.12)",
            "field_bg": "#0f172a",
            "field_border": "#334155",
            "focus_border": "#60a5fa",
            "focus_shadow": "0 0 0 2px rgba(96, 165, 250, 0.28)",
            "badge_text": "#9ca3af",
        }

    return {
        "window_bg": "#ffffff",
        "primary_text": "#2d2f36",
        "secondary_text": "#4d4f55",
        "muted_text": "#5b6470",
        "helper_text": "#606a78",
        "section_header_text": "#1f2937",
        "tab_border": "#e5e7eb",
        "tab_selected_bg": "#f5f7fb",
        "tab_selected_text": "#1f2937",
        "tab_selected_border": "#d5ddf1",
        "tab_selected_bottom": "#6b8dde",
        "tab_unselected_text": "#4b5563",
        "tab_hover_bg": "#f8fafc",
        "card_bg": "#fcfcfd",
        "card_border": "#e6e8ec",
        "advanced_bg": "#f7f9fb",
        "advanced_border": "#d5dae3",
        "field_bg": "#ffffff",
        "field_border": "#d0d5dd",
        "focus_border": "#5b8def",
        "focus_shadow": "0 0 0 2px rgba(91, 141, 239, 0.18)",
        "badge_text": "#6b7280",
    }


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

        layout = QHBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(16)

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
            tip_btn.setText("ⓘ")
            _set_pointing_cursor(tip_btn)
            tip_btn.setToolTip(tooltip_text)
            tip_btn.setStyleSheet(
                f"QToolButton {{ border: none; font-weight: 700; color: {palette['muted_text']}; font-size: 14px; padding: 4px; }}"
                f"QToolButton:hover {{ color: {palette['focus_border']}; }}"
            )
            control_layout.addWidget(tip_btn)

        control_layout.addStretch()
        layout.addLayout(control_layout, 0)


        self.setLayout(layout)
        self._base_style = self.styleSheet() or ""
        self.control = control

    def matches(self, query: str) -> bool:
        if not query:
            return True
        haystack = f"{self._title_text} {self._description_text}".lower()
        return query.lower() in haystack

    def set_highlighted(self, on: bool) -> None:
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
        _set_pointing_cursor(self._color_btn)
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
        _set_pointing_cursor(self._clear_btn)
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


class ShortcutField(QWidget):
    """Cross-platform shortcut editor with conflict detection and reset."""

    shortcutChanged = pyqtSignal(str)

    def __init__(self, default_shortcut: str, palette: Dict[str, str], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._palette = palette
        self._default = default_shortcut
        self._last_conflict: Optional[str] = None

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        field_row = QHBoxLayout()
        field_row.setContentsMargins(0, 0, 0, 0)
        field_row.setSpacing(6)

        self._editor = QKeySequenceEdit()
        self._editor.setClearButtonEnabled(True)
        self._editor.keySequenceChanged.connect(self._on_changed)
        self._editor.setStyleSheet(
            f"""
            QKeySequenceEdit {{
                padding: 6px 8px;
                border: 1px solid {palette['field_border']};
                border-radius: 5px;
                background: {palette['field_bg']};
                color: {palette['primary_text']};
            }}
            QKeySequenceEdit:focus {{
                border-color: {palette['focus_border']};
                box-shadow: {palette['focus_shadow']};
            }}
            """
        )

        record_hint = QLabel("Click then press the keys to record.")
        record_hint.setStyleSheet(f"color: {palette['muted_text']};")

        self._reset_btn = QToolButton()
        self._reset_btn.setText("Reset to default")
        _set_pointing_cursor(self._reset_btn)
        self._reset_btn.clicked.connect(self.reset_to_default)

        field_row.addWidget(self._editor, 1)
        field_row.addWidget(self._reset_btn)

        layout.addLayout(field_row)
        layout.addWidget(record_hint)

        self._warning_label = QLabel("")
        self._warning_label.setStyleSheet("color: #dc2626; font-weight: 600;")
        layout.addWidget(self._warning_label)

        self.setLayout(layout)
        self.reset_to_default()

    def value(self) -> str:
        text = self._editor.keySequence().toString()
        return text or self._default

    def reset_to_default(self) -> None:
        self._editor.setKeySequence(QKeySequence(self._default))
        self._update_warning(None)
        self.shortcutChanged.emit(self.value())

    def set_shortcut(self, shortcut: str) -> None:
        target = shortcut or self._default
        self._editor.setKeySequence(QKeySequence(target))
        self._update_warning(self._detect_conflict(QKeySequence(target)))
        self.shortcutChanged.emit(self.value())

    def _on_changed(self, sequence: QKeySequence) -> None:
        conflict = self._detect_conflict(sequence)
        self._update_warning(conflict)
        self.shortcutChanged.emit(self.value())

    def _detect_conflict(self, sequence: QKeySequence) -> Optional[str]:
        if sequence.isEmpty():
            return "Click to record a shortcut."

        for action in mw.findChildren(QAction):
            try:
                other = action.shortcut()
            except Exception:
                continue
            if not other or other.isEmpty():
                continue
            if other.matches(sequence) == QKeySequence.SequenceMatch.ExactMatch:
                text = action.text() or "another action"
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


class QuickSetupWizard(QDialog):
    """Small first-run wizard for optional progress bar preferences."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Progress Bar Quick Setup")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.skipped = False

        layout = QVBoxLayout()
        title = QLabel("Welcome! Choose a few defaults for your progress bar.")
        title.setWordWrap(True)
        layout.addWidget(title)

        self._show_numbers = QCheckBox("Show counts and percentage")
        self._show_numbers.setChecked(True)
        self._warnings_enabled = QCheckBox("Enable warning badges")
        self._warnings_enabled.setChecked(False)
        self._stacked_segments = QCheckBox("Use segmented queue visualization")
        self._reduced_motion = QCheckBox("Reduce motion / disable animations")

        for widget in [self._show_numbers, self._warnings_enabled, self._stacked_segments, self._reduced_motion]:
            layout.addWidget(widget)

        button_row = QHBoxLayout()
        skip_btn = QPushButton("Skip")
        skip_btn.clicked.connect(self._skip)
        save_btn = QPushButton("Save setup")
        save_btn.clicked.connect(self.accept)
        button_row.addWidget(skip_btn)
        button_row.addStretch()
        button_row.addWidget(save_btn)
        layout.addLayout(button_row)

        self.setLayout(layout)

    def _skip(self) -> None:
        self.skipped = True
        self.accept()

    def selected_config(self) -> Dict[str, Any]:
        show_numbers = self._show_numbers.isChecked()
        reduced_motion = self._reduced_motion.isChecked()
        return {
            "show_number": show_numbers,
            "show_percent": show_numbers,
            "warnings_enabled": self._warnings_enabled.isChecked(),
            "show_warning_badge": self._warnings_enabled.isChecked(),
            "stacked_segments": self._stacked_segments.isChecked(),
            "show_progress_legend": self._stacked_segments.isChecked(),
            "reduced_motion": reduced_motion,
            "animated_updates": not reduced_motion,
        }


class DeckBreakdownDialog(QDialog):
    """Popover showing actionable and buried counts per deck with projected finish times."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Deck Breakdown")
        self.setModal(False)
        self.setMinimumWidth(460)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self._build_ui()

    def _build_ui(self) -> None:
        try:
            from aqt.qt import QHeaderView, QTreeWidget, QTreeWidgetItem
        except Exception:
            QHeaderView = None
            QTreeWidget = None
            QTreeWidgetItem = None

        self._tree_widget_item_cls = QTreeWidgetItem

        if QTreeWidget is None or QTreeWidgetItem is None:
            # If the Qt widgets are unavailable (e.g., during headless tests), skip UI setup.
            self._tree = None
            return

        palette = _ui_palette()
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        helper = QLabel(
            "Actionable counts exclude buried siblings; buried cards are listed separately. "
            "ETAs appear once at least one card has been reviewed."
        )
        helper.setWordWrap(True)
        helper.setStyleSheet(f"color: {palette['muted_text']};")

        controls_container = QWidget()
        controls = QVBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        top_controls = QHBoxLayout()
        top_controls.setContentsMargins(0, 0, 0, 0)
        top_controls.setSpacing(6)
        action_controls = QHBoxLayout()
        action_controls.setContentsMargins(0, 0, 0, 0)
        action_controls.setSpacing(6)
        self._sort_combo = QComboBox()
        self._sort_combo.addItem("Sort: Remaining", "remaining")
        self._sort_combo.addItem("Sort: Name", "name")
        self._sort_combo.addItem("Sort: Due soon", "eta")
        self._sort_combo.addItem("Sort: Review-heavy", "review")
        self._filter_combo = QComboBox()
        self._filter_combo.addItem("Filter: All", "all")
        self._filter_combo.addItem("Filter: New", "new")
        self._filter_combo.addItem("Filter: Learning", "learning")
        self._filter_combo.addItem("Filter: Review", "review")
        self._filter_combo.addItem("Filter: Pinned", "pinned")
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search decks…")
        if hasattr(self._sort_combo, "setAccessibleName"):
            self._sort_combo.setAccessibleName("Sort deck rows")
        if hasattr(self._filter_combo, "setAccessibleName"):
            self._filter_combo.setAccessibleName("Filter deck rows")
        if hasattr(self._search_edit, "setAccessibleName"):
            self._search_edit.setAccessibleName("Search decks")
        self._pin_btn = QPushButton("&Pin selected")
        self._pin_btn.clicked.connect(self._pin_selected_deck)
        if hasattr(self._pin_btn, "setToolTip"):
            self._pin_btn.setToolTip("Pin or unpin the selected deck from filtered views.")
        self._focus_btn = QPushButton("&Focus selected deck")
        self._focus_btn.clicked.connect(self._focus_selected_deck)
        if hasattr(self._focus_btn, "setToolTip"):
            self._focus_btn.setToolTip("Switch the reviewer to only the selected deck.")
        top_controls.addWidget(self._sort_combo)
        top_controls.addWidget(self._filter_combo)
        top_controls.addWidget(self._search_edit, 1)
        action_controls.addStretch()
        action_controls.addWidget(self._pin_btn)
        action_controls.addWidget(self._focus_btn)
        controls.addLayout(top_controls)
        controls.addLayout(action_controls)
        controls_container.setLayout(controls)
        self._controls_layout_mode = "two_row"

        self._tree = QTreeWidget()
        self._tree.setRootIsDecorated(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.setHeaderLabels(["Deck", "Actionable (N/L/R)", "Buried (+)", "ETA"])
        self._tree.header().setStretchLastSection(False)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(helper)
        layout.addWidget(controls_container)
        layout.addWidget(self._tree)

        self._rows_cache = []
        self._sort_combo.currentIndexChanged.connect(self._rerender)
        self._filter_combo.currentIndexChanged.connect(self._rerender)
        self._search_edit.textChanged.connect(self._rerender)

        self.setLayout(layout)
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {palette["window_bg"]};
                color: {palette["primary_text"]};
            }}
            QTreeWidget {{
                background: {palette["card_bg"]};
                color: {palette["primary_text"]};
                border: 1px solid {palette["card_border"]};
            }}
            QTreeWidget::item {{
                border: none;
                padding: 4px 6px;
            }}
            QHeaderView::section {{
                background: {palette["tab_selected_bg"]};
                color: {palette["tab_selected_text"]};
                border: 1px solid {palette["tab_border"]};
                padding: 4px 6px;
            }}
            """
        )

    def _format_counts(self, counts: Tuple[int, int, int]) -> str:
        new, lrn, rev = counts
        total = new + lrn + rev
        return f"{total} (N {new} · L {lrn} · R {rev})"

    def _eta_sort_key(self, eta_text: str) -> Tuple[int, int, str]:
        """Sort ETAs by clock time while pushing unavailable values to the end."""
        cleaned = str(eta_text or "").strip()
        if not cleaned or cleaned.upper() == "N/A":
            return (1, 24 * 60, cleaned)

        day_offset = 0
        base_text = cleaned
        if "+" in base_text:
            base_text, day_text = base_text.rsplit("+", 1)
            try:
                day_offset = max(0, int(day_text))
            except ValueError:
                return (1, 24 * 60, cleaned)

        suffix = ""
        upper_base = base_text.upper()
        if upper_base.endswith("AM") or upper_base.endswith("PM"):
            suffix = upper_base[-2:]
            base = base_text[:-2].strip()
        else:
            base = base_text.strip()
        parts = base.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            return (1, 24 * 60, cleaned)

        hour = int(parts[0])
        minute = int(parts[1])

        if suffix in {"AM", "PM"}:
            if hour == 12:
                hour = 0
            if suffix == "PM":
                hour += 12

        return (0, day_offset * 24 * 60 + hour * 60 + minute, cleaned)

    def _add_row(self, row: Dict[str, Any], parent_item: Optional[QTreeWidgetItem] = None) -> QTreeWidgetItem:
        if self._tree is None or self._tree_widget_item_cls is None:
            return None  # type: ignore[return-value]

        item = QTreeWidgetItem(parent_item or self._tree)
        item.setText(0, row.get("name", ""))
        role = int(getattr(getattr(Qt, "ItemDataRole", Qt), "UserRole", 32))
        item.setData(0, role, str(row.get("deck_id", "")))
        item.setText(1, self._format_counts(row.get("actionable", (0, 0, 0))))
        item.setText(2, self._format_counts(row.get("buried", (0, 0, 0))))
        item.setText(3, row.get("eta", "N/A"))
        item.setTextAlignment(1, int(_alignment_flag("AlignVCenter")))
        item.setTextAlignment(2, int(_alignment_flag("AlignVCenter")))
        item.setTextAlignment(3, int(_alignment_flag("AlignVCenter") | _alignment_flag("AlignRight")))

        for child in row.get("children", []):
            self._add_row(child, item)
        return item

    def _flatten_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for row in rows:
            out.append(row)
            out.extend(self._flatten_rows(row.get("children", [])))
        return out

    def _match_filter(self, row: Dict[str, Any], mode: str, pinned_ids: Optional[set] = None) -> bool:
        n, learning_count, r = row.get("actionable", (0, 0, 0))
        if mode == "new":
            return n > 0
        if mode == "learning":
            return learning_count > 0
        if mode == "review":
            return r > 0
        if mode == "pinned":
            ids = pinned_ids if pinned_ids is not None else set(settings.pinned_deck_views)
            return str(row.get("deck_id")) in ids
        return True

    def _match_search(self, row: Dict[str, Any], query: str) -> bool:
        if not query:
            return True
        return query.lower() in str(row.get("name", "")).lower()

    def _sort_key(self, row: Dict[str, Any], mode: str):
        n, learning_count, r = row.get("actionable", (0, 0, 0))
        if mode == "review":
            return -(r)
        if mode == "name":
            return str(row.get("name", "")).lower()
        if mode == "eta":
            return self._eta_sort_key(str(row.get("eta", "")))
        return -(n + learning_count + r)

    def _filter_and_sort_rows(
        self,
        rows: List[Dict[str, Any]],
        mode_filter: str,
        mode_sort: str,
        query: str,
        pinned_ids: Optional[set] = None,
    ) -> List[Dict[str, Any]]:
        """Apply search/filter rules while preserving parent-child hierarchy."""
        if pinned_ids is None:
            pinned_ids = set(settings.pinned_deck_views)

        filtered: List[Dict[str, Any]] = []
        for row in rows:
            children = self._filter_and_sort_rows(
                list(row.get("children", [])),
                mode_filter,
                mode_sort,
                query,
                pinned_ids,
            )
            is_match = self._match_filter(row, mode_filter, pinned_ids) and self._match_search(row, query)
            if is_match or children:
                row_copy = dict(row)
                row_copy["children"] = children
                filtered.append(row_copy)

        filtered.sort(key=lambda row: self._sort_key(row, mode_sort))
        return filtered

    def _pin_selected_deck(self) -> None:
        if self._tree is None:
            return
        item = self._tree.currentItem()
        if item is None:
            return
        deck_name = item.text(0)
        role = int(getattr(getattr(Qt, "ItemDataRole", Qt), "UserRole", 32))
        selected_did = str(item.data(0, role))
        selected = next((row for row in self._flatten_rows(self._rows_cache) if str(row.get("deck_id")) == selected_did), None)
        if not selected:
            return
        did = str(selected.get("deck_id"))
        current = set(settings.pinned_deck_views)
        if did in current:
            current.remove(did)
            label = "Unpinned"
        else:
            current.add(did)
            label = "Pinned"
        updated = dict(config)
        updated["pinned_deck_views"] = sorted(current)
        addon_config.apply_config(mw, updated)
        _reload_settings(show_messages=False)
        tooltip(f"{label} deck: {deck_name}", parent=self, period=1500)
        self._rerender()

    def _focus_selected_deck(self) -> None:
        if self._tree is None:
            return
        item = self._tree.currentItem()
        if item is None:
            return
        role = int(getattr(getattr(Qt, "ItemDataRole", Qt), "UserRole", 32))
        selected_did = item.data(0, role)
        try:
            did = int(selected_did)
        except (TypeError, ValueError):
            return
        deck_name = item.text(0)
        try:
            if mw.col is not None and hasattr(mw.col, "decks"):
                mw.col.decks.select(did)
            if hasattr(mw, "moveToState"):
                mw.moveToState("overview")
            tooltip(f"Focused deck: {deck_name}", parent=self, period=1500)
        except Exception:
            tooltip(f"Could not focus deck: {deck_name}", parent=self, period=2000)

    def _rerender(self) -> None:
        if self._tree is None:
            return
        mode_sort = self._sort_combo.currentData() if hasattr(self, "_sort_combo") else "remaining"
        mode_filter = self._filter_combo.currentData() if hasattr(self, "_filter_combo") else "all"
        query = self._search_edit.text().strip() if hasattr(self, "_search_edit") else ""
        rows = self._filter_and_sort_rows(
            self._rows_cache,
            str(mode_filter),
            str(mode_sort),
            query,
        )
        self._tree.clear()
        for row in rows:
            self._add_row(row)
        self._tree.expandToDepth(1)

    def update_rows(self, rows: List[Dict[str, Any]]) -> None:
        if self._tree is None:
            return
        self._rows_cache = list(rows)
        self._rerender()


class ProgressBarConfigDialog(QDialog):
    """Guided configuration window with live search and clearer hierarchy."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Progress Bar Settings")
        self.setMinimumWidth(560)
        self._config_snapshot = deepcopy(config)
        self._defaults = self._load_defaults()
        self._palette_cache = self._palette()
        self._rows: List[Dict[str, Any]] = []
        self._section_meta: Dict[str, Dict[str, Any]] = {}
        self._nav_items: Dict[str, QListWidgetItem] = {}
        self._building_ui = True
        self._dirty = False
        self._selected_display_preset = str(self._config_snapshot.get("display_preset", "compact")).lower()
        self._compact_layout_active = False

        self._build_ui()
        self._populate_from_config(self._config_snapshot)
        self._update_preview()
        self._refresh_preset_changes()
        self._building_ui = False
        self._update_dirty_state(False)
        self._apply_section_filter("")
        self._apply_compact_mode(840)

    def _palette(self) -> Dict[str, str]:
        return _ui_palette()

    def _load_defaults(self) -> Dict[str, Any]:
        defaults: Dict[str, Any] = {}
        try:
            defaults = mw.addonManager.addonConfigDefaults(__name__) or {}
        except Exception:
            defaults = {}
        if not isinstance(defaults, dict):
            defaults = {}

        if not defaults:
            try:
                config_path = os.path.join(os.path.dirname(__file__), "config.json")
                with open(config_path, "r", encoding="utf-8") as fh:
                    defaults = json.load(fh) or {}
            except Exception:
                defaults = {}
        return defaults

    def _build_ui(self) -> None:
        palette = self._palette_cache
        field_style = f"""
            QLineEdit, QComboBox, QSpinBox {{
                padding: 6px 8px;
                border: 1px solid {palette['field_border']};
                border-radius: 5px;
                background: {palette['field_bg']};
                color: {palette['primary_text']};
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
                border-color: {palette['focus_border']};
                box-shadow: {palette['focus_shadow']};
            }}
            QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button {{
                border: 0;
            }}
        """

        self.setStyleSheet(
            f"""
            QDialog {{
                background: {palette["window_bg"]};
                color: {palette["primary_text"]};
            }}
            """
        )

        main_layout = QVBoxLayout()
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # Header section with improved styling
        header_frame = QFrame()
        header_frame.setStyleSheet(f"background: {palette['card_bg']}; border-radius: 8px; padding: 12px;")
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(12, 12, 12, 12)
        header_layout.setSpacing(6)

        title_label = QLabel("Progress Bar Settings")
        title_label.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {palette['section_header_text']};")
        header_layout.addWidget(title_label)

        intro = QLabel(
            "Tune the progress bar to match your workflow. Use search to jump to a setting, or browse by section. Enable autosave to apply changes instantly."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"font-weight: 500; color: {palette['secondary_text']}; margin-top: 4px;")
        header_layout.addWidget(intro)

        header_frame.setLayout(header_layout)
        main_layout.addWidget(header_frame)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(8)

        self._search_field = QLineEdit()
        self._search_field.setPlaceholderText("Search settings... (e.g., 'color', 'warning', 'shortcut')")
        self._search_field.setStyleSheet(field_style)
        # Add search icon hint
        search_icon_style = """
            QLineEdit {{
                padding-left: 32px;
            }}
        """
        self._search_field.setStyleSheet(field_style + search_icon_style)

        self._clear_filter_btn = QToolButton()
        self._clear_filter_btn.setText("✕")
        self._clear_filter_btn.setToolTip("Clear search")
        _set_pointing_cursor(self._clear_filter_btn)
        self._clear_filter_btn.clicked.connect(self._clear_filter)
        self._clear_filter_btn.setVisible(False)

        self._dirty_badge = QLabel("")
        self._dirty_badge.setStyleSheet(
            "QLabel { padding: 6px 12px; border-radius: 12px; font-weight: 700; font-size: 11px; }"
        )

        search_row.addWidget(self._search_field, 1)
        search_row.addWidget(self._clear_filter_btn)
        search_row.addStretch()
        search_row.addWidget(self._dirty_badge)
        main_layout.addLayout(search_row)

        self._section_selector = QComboBox()
        self._section_selector.setStyleSheet(field_style)
        if hasattr(self._section_selector, "setAccessibleName"):
            self._section_selector.setAccessibleName("Settings section")
        self._section_selector.currentIndexChanged.connect(self._section_selector_navigate)
        self._section_selector.setVisible(False)
        main_layout.addWidget(self._section_selector)

        body_layout = QHBoxLayout()
        body_layout.setSpacing(10)

        nav_frame = QFrame()
        self._nav_frame = nav_frame
        nav_frame.setFixedWidth(230)
        nav_layout = QVBoxLayout()
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(6)

        self._collapse_btn = QToolButton()
        self._collapse_btn.setText("Hide navigation")
        _set_pointing_cursor(self._collapse_btn)
        self._collapse_btn.clicked.connect(self._toggle_nav)

        self._nav_list = QListWidget()
        self._nav_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._nav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._nav_list.setSpacing(4)
        self._nav_list.setStyleSheet(
            f"""
            QListWidget {{
                background: {palette['card_bg']};
                border: 1px solid {palette['card_border']};
                border-radius: 6px;
            }}
            QListWidget::item {{
                padding: 12px 10px;
                margin: 3px 4px;
                border-radius: 6px;
                font-weight: 500;
            }}
            QListWidget::item:selected {{
                background: {palette['tab_selected_bg']};
                color: {palette['tab_selected_text']};
                border: 2px solid {palette['focus_border']};
                font-weight: 700;
            }}
            QListWidget::item:hover:!selected {{
                background: {palette['tab_hover_bg']};
            }}
            """
        )
        self._nav_list.currentRowChanged.connect(self._stack_navigate)

        nav_layout.addWidget(self._collapse_btn)
        nav_layout.addWidget(self._nav_list, 1)
        nav_frame.setLayout(nav_layout)

        content_frame = QFrame()
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        self._no_results_label = QLabel("No settings match your search.")
        self._no_results_label.setStyleSheet(f"color: {palette['muted_text']}; font-weight: 600;")
        self._no_results_label.setVisible(False)
        content_layout.addWidget(self._no_results_label)

        self._stack = QStackedWidget()
        content_layout.addWidget(self._stack, 1)
        content_frame.setLayout(content_layout)

        body_layout.addWidget(nav_frame, 0)
        body_layout.addWidget(content_frame, 1)
        main_layout.addLayout(body_layout, 1)

        # Controls
        self.progress_bar_enabled_cb = QCheckBox("Show the progress bar while reviewing")
        self.scrolling_edit_cb = QCheckBox("Keep the bar animated while editing cards")
        self.invert_progress_cb = QCheckBox("Fill right-to-left (RTL)")
        self.include_new_cb = QCheckBox("Include new cards in progress")
        self.include_rev_cb = QCheckBox("Include review cards in progress")
        self.include_lrn_cb = QCheckBox("Include learning cards in progress")
        self.include_new_after_revs_cb = QCheckBox("Defer new cards until reviews are done")
        self.force_forward_cb = QCheckBox("Prevent progress from decreasing")
        self.show_percent_cb = QCheckBox("Show percent complete")
        self.show_number_cb = QCheckBox("Show raw card counts")
        self.show_yesterday_cb = QCheckBox("Compare against yesterday")
        self.text_hierarchy_style_combo = QComboBox()
        self.text_hierarchy_style_combo.addItem("Single-line compact", "compact")
        self.text_hierarchy_style_combo.addItem("Two-line hierarchy", "two_line")
        self.text_hierarchy_style_combo.setStyleSheet(field_style)
        self.label_style_combo = QComboBox()
        self.label_style_combo.addItem("Compact", "compact")
        self.label_style_combo.addItem("Detailed", "detailed")
        self.label_style_combo.setStyleSheet(field_style)
        self.compact_separators_cb = QCheckBox("Use compact separators")
        self.vertical_text_line_break_cb = QCheckBox("Split tiers on vertical bars")
        self.show_again_cb = QCheckBox("Show Again rate")
        self.show_retention_cb = QCheckBox("Show true retention (TR)")
        self.show_sm_retention_cb = QCheckBox("Show super-mature retention (SMTR)")
        self.show_debug_cb = QCheckBox("Show debug weights + raw counts")
        self.show_progress_legend_cb = QCheckBox("Show queue legend (New/Learning/Review)")
        self.show_progress_legend_cb.setToolTip("Show a color-coded legend for remaining New, Learning, and Review cards.")
        self.warnings_enabled_cb = QCheckBox("Enable warning colours and alerts")
        self.pace_warnings_enabled_cb = QCheckBox("Warn when you're behind daily goals")
        self.show_eta_confidence_cb = QCheckBox("Show ETA confidence indicator")
        self.auto_adjust_contrast_cb = QCheckBox("Auto-adjust colors to meet contrast")
        self.onboarding_completed_cb = QCheckBox("Skip onboarding on startup")
        self.quick_setup_enabled_cb = QCheckBox("Enable first-run Quick Setup wizard")
        self.focus_mode_cb = QCheckBox("Focus Mode (reduce visual noise)")
        self.reduced_motion_cb = QCheckBox("Reduce motion")
        self.animated_updates_cb = QCheckBox("Animate progress value changes")
        self.show_segment_inline_labels_cb = QCheckBox("Show inline labels in segmented mode")
        self.show_warning_badge_cb = QCheckBox("Show compact warning badge with codes")
        self.completion_celebration_cb = QCheckBox("Show completion state at 100%")
        self.responsive_breakpoints_cb = QCheckBox("Enable responsive layout at small widths")

        self.pacing_strategy_combo = QComboBox()
        self.pacing_strategy_combo.addItem("Simple average", "average")
        self.pacing_strategy_combo.addItem("EWMA (recommended)", "ewma")
        self.pacing_strategy_combo.addItem("Trimmed mean", "trimmed")
        self.pacing_strategy_combo.addItem("Median", "median")
        self.pacing_strategy_combo.addItem("Segmented by deck", "segmented")
        self.pacing_strategy_combo.setStyleSheet(field_style)

        self.time_warning_sb = QSpinBox()
        self.time_warning_sb.setRange(0, 600)
        self.time_warning_sb.setSuffix(" minutes")
        self.time_warning_sb.setStyleSheet(field_style)

        self.again_warning_sb = QSpinBox()
        self.again_warning_sb.setRange(0, 100)
        self.again_warning_sb.setSuffix(" %")
        self.again_warning_sb.setStyleSheet(field_style)

        self.retention_warning_sb = QSpinBox()
        self.retention_warning_sb.setRange(0, 100)
        self.retention_warning_sb.setSuffix(" %")
        self.retention_warning_sb.setStyleSheet(field_style)

        self.warning_hysteresis_sb = QDoubleSpinBox()
        self.warning_hysteresis_sb.setRange(0.0, 20.0)
        self.warning_hysteresis_sb.setSingleStep(0.5)
        self.warning_hysteresis_sb.setSuffix(" %")
        self.warning_hysteresis_sb.setStyleSheet(field_style)

        self.warning_cooldown_sb = QSpinBox()
        self.warning_cooldown_sb.setRange(0, 600)
        self.warning_cooldown_sb.setSuffix(" s")
        self.warning_cooldown_sb.setStyleSheet(field_style)

        self.warning_text_color_edit = ColorPickerField("", palette)
        self.warning_text_color_edit.colorChanged.connect(self._on_value_changed)

        self.warning_bg_color_edit = ColorPickerField("", palette)
        self.warning_bg_color_edit.colorChanged.connect(self._on_value_changed)

        self.warning_fg_color_edit = ColorPickerField("", palette)
        self.warning_fg_color_edit.colorChanged.connect(self._on_value_changed)

        self.daily_target_cards_sb = QSpinBox()
        self.daily_target_cards_sb.setRange(0, 100000)
        self.daily_target_cards_sb.setSuffix(" cards")
        self.daily_target_cards_sb.setStyleSheet(field_style)

        self.target_review_minutes_sb = QSpinBox()
        self.target_review_minutes_sb.setRange(0, 1440)
        self.target_review_minutes_sb.setSuffix(" minutes")
        self.target_review_minutes_sb.setStyleSheet(field_style)

        self.lrn_steps_sb = QSpinBox()
        self.lrn_steps_sb.setRange(1, 30)
        self.lrn_steps_sb.setSuffix("× weight")
        self.lrn_steps_sb.setStyleSheet(field_style)

        self.no_days_sb = QSpinBox()
        self.no_days_sb.setRange(1, 31)
        self.no_days_sb.setSuffix(" days")
        self.no_days_sb.setStyleSheet(field_style)

        self.use_system_tz_cb = QCheckBox("Use computer time zone")
        self.tz_sb = QSpinBox()
        self.tz_sb.setRange(-12, 14)
        self.tz_sb.setPrefix("UTC ")
        self.tz_sb.setStyleSheet(field_style)
        self.use_system_tz_cb.toggled.connect(lambda checked: self.tz_sb.setEnabled(not checked))

        self.history_days_sb = QSpinBox()
        self.history_days_sb.setRange(0, 3650)
        self.history_days_sb.setSuffix(" days")
        self.history_days_sb.setToolTip("How many daily history entries to keep. 0 keeps unlimited history.")
        self.history_days_sb.setStyleSheet(field_style)

        self.orientation_combo = QComboBox()
        self.orientation_combo.addItem("Horizontal", "horizontal")
        self.orientation_combo.addItem("Vertical", "vertical")
        self.orientation_combo.setStyleSheet(field_style)

        self.dock_area_combo = QComboBox()
        for label, data in [("Top", "top"), ("Bottom", "bottom"), ("Left", "left"), ("Right", "right")]:
            self.dock_area_combo.addItem(label, data)
        self.dock_area_combo.setStyleSheet(field_style)

        self.max_width_edit = QLineEdit()
        self.max_width_edit.setPlaceholderText("5px, 10px, 100% …")
        self.max_width_edit.setStyleSheet(field_style)

        self.pb_style_edit = QLineEdit()
        self.pb_style_edit.setPlaceholderText("fusion, windows, plastique…")
        self.pb_style_edit.setStyleSheet(field_style)

        self.counting_basis_combo = QComboBox()
        self.counting_basis_combo.addItem("Cards answered", "answered")
        self.counting_basis_combo.addItem("Cards seen (preview + answered)", "seen")
        self.counting_basis_combo.setStyleSheet(field_style)

        self.count_scope_combo = QComboBox()
        self.count_scope_combo.addItem("Per-deck progress", "per_deck")
        self.count_scope_combo.addItem("Global session progress", "global")
        self.count_scope_combo.setStyleSheet(field_style)

        self.legend_position_combo = QComboBox()
        self.legend_position_combo.addItem("Above the bar", "above")
        self.legend_position_combo.addItem("Below the bar", "below")
        self.legend_position_combo.addItem("Left of the bar", "left")
        self.legend_position_combo.addItem("Right of the bar", "right")
        self.legend_position_combo.setStyleSheet(field_style)

        default_shortcut = "Meta+G" if sys.platform == "darwin" else "Ctrl+G"
        self.shortcut_field = ShortcutField(default_shortcut, palette)
        self.shortcut_field.shortcutChanged.connect(self._on_value_changed)

        self._preset_definitions = self._build_preset_definitions()
        self._preset_combo = QComboBox()
        self._preset_combo.setStyleSheet(field_style)
        self._preset_combo.addItem("Choose a preset...", None)
        for preset in self._preset_definitions:
            self._preset_combo.addItem(preset["name"], preset["id"])
        self._preset_combo.currentIndexChanged.connect(self._apply_preset_selection)

        self._preset_description = QLabel("Select a curated preset to quickly apply a layout and label mix.")
        self._preset_description.setWordWrap(True)
        self._preset_description.setStyleSheet(f"color: {palette['secondary_text']}; font-weight: 500;")

        self._preset_changes_toggle = QToolButton()
        self._preset_changes_toggle.setCheckable(True)
        self._preset_changes_toggle.setChecked(False)
        self._preset_changes_toggle.setArrowType(_arrow_type("RightArrow"))
        self._preset_changes_toggle.setToolButtonStyle(_tool_button_style("ToolButtonTextBesideIcon"))
        self._preset_changes_toggle.setText("Show changes")
        self._preset_changes_toggle.toggled.connect(self._toggle_preset_changes)

        self._preset_changes_label = QLabel("Select a preset to see the changes it will apply.")
        self._preset_changes_label.setWordWrap(True)
        self._preset_changes_label.setStyleSheet(f"color: {palette['secondary_text']};")

        self._preset_changes_container = QWidget()
        preset_changes_layout = QVBoxLayout()
        preset_changes_layout.setContentsMargins(8, 0, 0, 0)
        preset_changes_layout.addWidget(self._preset_changes_label)
        self._preset_changes_container.setLayout(preset_changes_layout)
        self._preset_changes_container.setVisible(False)

        preset_control = QWidget()
        preset_layout = QVBoxLayout()
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.setSpacing(6)
        preset_layout.addWidget(self._preset_combo)
        preset_layout.addWidget(self._preset_description)
        preset_layout.addWidget(self._preset_changes_toggle)
        preset_layout.addWidget(self._preset_changes_container)
        preset_control.setLayout(preset_layout)

        segment_colors = settings.segment_colors if settings is not None else {}
        if settings is not None and settings.stacked_segments:
            self._preview_bar = progress_ui.SegmentedProgressBar(segment_colors)
        else:
            self._preview_bar = QProgressBar()
        self._preview_bar.setRange(0, 100)
        self._preview_bar.setValue(45)
        self._preview_bar.setMinimumHeight(26)

        self._preview_caption = QLabel("Mock progress snapshot using your current display options.")
        self._preview_caption.setWordWrap(True)
        self._preview_caption.setStyleSheet(f"color: {palette['secondary_text']}; font-weight: 500;")

        preview_control = QWidget()
        preview_layout = QVBoxLayout()
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(6)
        preview_layout.addWidget(self._preview_bar)
        preview_layout.addWidget(self._preview_caption)
        preview_control.setLayout(preview_layout)

        # Sections - improved organization
        preset_rows = [
            SettingRow(
                "Preset selector",
                "Apply a curated set of settings for quick layouts and label combinations.",
                preset_control,
                palette,
            ),
            SettingRow(
                "Preview",
                "A static preview that mirrors your current progress bar settings.",
                preview_control,
                palette,
            ),
        ]
        self._add_section_page("Presets & Preview", "Quickly apply curated presets and preview the result.", preset_rows)

        visibility_rows = [
            SettingRow(
                "Progress bar visibility",
                "Turn the bar on or off for the reviewer. Disabling hides all other options.",
                self.progress_bar_enabled_cb,
                palette,
            ),
            SettingRow(
                "Completion labels",
                "Choose which completion stats appear next to the bar.",
                self._wrap_controls([self.show_percent_cb, self.show_number_cb, self.show_yesterday_cb]),
                palette,
            ),
            SettingRow(
                "Text hierarchy",
                "Emphasize done/total + ETA as primary stats and keep auxiliary rates secondary.",
                self._wrap_controls([self.label_style_combo, self.text_hierarchy_style_combo, self.compact_separators_cb, self.vertical_text_line_break_cb]),
                palette,
            ),
        ]
        self._add_section_page("Visibility", "Control when and how the progress bar appears.", visibility_rows)

        counting_rows = [
            SettingRow(
                "What counts toward progress",
                "Pick the queues that count toward completion so the bar matches your study mix.",
                self._wrap_controls([self.include_new_cb, self.include_lrn_cb, self.include_rev_cb]),
                palette,
            ),
            SettingRow(
                "Counting basis",
                "Decide whether progress reflects answered cards only or every card you open.",
                self.counting_basis_combo,
                palette,
            ),
            SettingRow(
                "Scope",
                "Track progress per deck or treat the entire session as one pool.",
                self.count_scope_combo,
                palette,
            ),
            SettingRow(
                "Hold new cards",
                "Delay new cards until reviews finish (applies when new cards are included).",
                self.include_new_after_revs_cb,
                palette,
            ),
            SettingRow(
                "Prevent backsliding",
                "Stop the bar from shrinking if counts change mid-session (useful when burying).",
                self.force_forward_cb,
                palette,
            ),
        ]
        self._add_section_page("Counting", "Define exactly what the bar measures.", counting_rows)

        behavior_rows = [
            SettingRow(
                "Animate during editing",
                "Keeps subtle motion while you edit; disable if you want a fully static bar.",
                self.scrolling_edit_cb,
                palette,
            ),
            SettingRow(
                "Fill direction",
                "Flip left/right fill to match RTL layouts or personal preference.",
                self.invert_progress_cb,
                palette,
            ),
            SettingRow(
                "Pacing strategy",
                "Choose how ETA pace is estimated (average, EWMA, median, trimmed, segmented).",
                self._wrap_controls([self.pacing_strategy_combo, self.show_eta_confidence_cb]),
                palette,
            ),
            SettingRow(
                "Pace warnings",
                "Surface alerts when your projected finish falls behind your goals (uses daily targets).",
                self.pace_warnings_enabled_cb,
                palette,
            ),
        ]
        self._add_section_page("Warnings", "Warning behavior and pacing alerts.", behavior_rows)

        appearance_rows = [
            SettingRow(
                "Orientation & dock",
                "Place the bar where it remains legible beside your study layout.",
                self._wrap_controls([self.orientation_combo, self.dock_area_combo]),
                palette,
            ),
            SettingRow(
                "Legend placement",
                "Show a color-coded legend for remaining queues and choose where it sits.",
                self._wrap_controls([self.show_progress_legend_cb, self.legend_position_combo]),
                palette,
                tooltip_text="Legend shows New/Learning/Review counts beside the bar.",
            ),
            SettingRow(
                "Bar size",
                "Constrain the bar so it doesn't crowd the reviewer (leave blank for automatic sizing).",
                self.max_width_edit,
                palette,
            ),
            SettingRow(
                "Qt style override",
                "Force a specific Qt style if your platform theme looks off.",
                self.pb_style_edit,
                palette,
                tooltip_text="Examples: fusion, windows. Leave blank to follow Anki's theme.",
            ),
            SettingRow(
                "Metrics inside the bar",
                "Decide which stats sit inside the progress text (retention, Again rate, debugging).",
                self._wrap_controls([self.show_again_cb, self.show_retention_cb, self.show_sm_retention_cb, self.show_debug_cb]),
                palette,
            ),
        ]
        self._add_section_page("Appearance", "Customize the look, position, and styling of the progress bar.", appearance_rows)

        shortcut_rows = [
            SettingRow(
                "Shortcut to show/hide",
                "Record a platform-appropriate shortcut. We'll catch conflicts and let you reset.",
                self.shortcut_field,
                palette,
            ),
        ]
        self._add_section_page("Shortcuts", "Control the bar without hunting for menus.", shortcut_rows)

        history_rows = [
            SettingRow(
                "Retention window",
                "Keep daily history entries for this many days (0 keeps all).",
                self.history_days_sb,
                palette,
            ),
        ]
        self._add_section_page("History", "Session-history retention and data-management settings.", history_rows)

        advanced_rows = [
            SettingRow(
                "Warning thresholds",
                "Set when the bar flips to warning colours (time remaining, Again %, retention). 0 disables a threshold.",
                self._wrap_controls([self.time_warning_sb, self.again_warning_sb, self.retention_warning_sb]),
                palette,
            ),
            SettingRow(
                "Warning stabilization",
                "Use hysteresis and cooldown to prevent flickering around thresholds.",
                self._wrap_controls([self.warning_hysteresis_sb, self.warning_cooldown_sb]),
                palette,
            ),
            SettingRow(
                "Warning colours",
                "Override colours used while warnings are active. Leave blank to inherit the theme.",
                self._wrap_controls([self.warning_text_color_edit, self.warning_bg_color_edit, self.warning_fg_color_edit]),
                palette,
            ),
            SettingRow(
                "Accessibility",
                "Auto-adjust low-contrast text/background pairs and show onboarding once configured.",
                self._wrap_controls([self.auto_adjust_contrast_cb, self.onboarding_completed_cb, self.quick_setup_enabled_cb]),
                palette,
            ),
            SettingRow(
                "Motion and focus",
                "Optional animation and simplified Focus Mode for distraction-free reviewing.",
                self._wrap_controls([self.focus_mode_cb, self.reduced_motion_cb, self.animated_updates_cb]),
                palette,
            ),
            SettingRow(
                "Segment and warning overlays",
                "Toggle inline segment labels, warning badge text, completion state, and responsive breakpoints.",
                self._wrap_controls([self.show_segment_inline_labels_cb, self.show_warning_badge_cb, self.completion_celebration_cb, self.responsive_breakpoints_cb]),
                palette,
            ),
            SettingRow(
                "Daily targets",
                "Card/time goals used for projected finish and pace warnings (0 disables a target).",
                self._wrap_controls([self.daily_target_cards_sb, self.target_review_minutes_sb]),
                palette,
            ),
            SettingRow(
                "Weighting & retention windows",
                "Tune how learning steps and retention windows influence the weighting math.",
                self._wrap_controls([self.lrn_steps_sb, self.no_days_sb]),
                palette,
            ),
            SettingRow(
                "Time zone",
                "Use your system zone or pin a UTC offset for day-cutoff and ETA calculations.",
                self._wrap_controls([self.use_system_tz_cb, self.tz_sb]),
                palette,
            ),
        ]
        self._add_section_page("Advanced", "Fine-tune warning thresholds, goals, timezone, and advanced pacing calculations.", advanced_rows)

        controls_container = QWidget()
        controls_container_layout = QVBoxLayout()
        controls_container_layout.setContentsMargins(0, 0, 0, 0)
        controls_container_layout.setSpacing(8)

        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(10)

        self._autosave_cb = QCheckBox("Autosave while editing")
        self._autosave_cb.setToolTip("Immediately save and apply changes as you make them. Disable to batch changes and save manually.")
        self._autosave_cb.setStyleSheet(
            f"""
            QCheckBox {{
                color: {palette['primary_text']};
                font-weight: 500;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 2px solid {palette['field_border']};
                border-radius: 4px;
                background: {palette['field_bg']};
            }}
            QCheckBox::indicator:checked {{
                background: {palette['focus_border']};
                border-color: {palette['focus_border']};
            }}
            QCheckBox::indicator:hover {{
                border-color: {palette['focus_border']};
            }}
            """
        )
        controls_layout.addWidget(self._autosave_cb)
        controls_layout.addStretch()

        secondary_controls_layout = QHBoxLayout()
        secondary_controls_layout.setContentsMargins(0, 0, 0, 0)
        secondary_controls_layout.setSpacing(8)

        # Import/Export buttons
        self._import_btn = QPushButton("Import...")
        self._import_btn.setToolTip("Import settings from a JSON file")
        self._import_btn.clicked.connect(self._import_settings)
        secondary_controls_layout.addWidget(self._import_btn)

        self._export_btn = QPushButton("Export...")
        self._export_btn.setToolTip("Export current settings to a JSON file")
        self._export_btn.clicked.connect(self._export_settings)
        secondary_controls_layout.addWidget(self._export_btn)

        secondary_controls_layout.addStretch()

        self._reset_section_btn = QPushButton("Reset section")
        self._reset_section_btn.setToolTip("Reset only the currently selected section to default values")
        self._reset_section_btn.clicked.connect(self._reset_current_section_to_defaults)
        secondary_controls_layout.addWidget(self._reset_section_btn)

        self._reset_btn = QPushButton("Reset all to defaults")
        self._reset_btn.setToolTip("Reset all settings to their default values")
        self._reset_btn.clicked.connect(self._reset_to_defaults)
        secondary_controls_layout.addWidget(self._reset_btn)

        primary_actions_layout = QHBoxLayout()
        primary_actions_layout.setContentsMargins(0, 0, 0, 0)
        primary_actions_layout.setSpacing(8)
        primary_actions_layout.addStretch()

        self._apply_btn = QPushButton("Apply / Reload")
        self._apply_btn.setToolTip("Apply settings immediately without closing this dialog")
        self._apply_btn.clicked.connect(self._apply_without_closing)
        primary_actions_layout.addWidget(self._apply_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        primary_actions_layout.addWidget(self._cancel_btn)

        self._save_btn = QPushButton("Save")
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self._save_and_close)
        primary_actions_layout.addWidget(self._save_btn)

        # Style buttons
        button_style = f"""
            QPushButton {{
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: 600;
                min-width: 80px;
            }}
            QPushButton:default {{
                background: {palette['focus_border']};
                color: white;
                border: none;
            }}
            QPushButton:default:hover {{
                background: {palette['focus_border']};
                opacity: 0.9;
            }}
            QPushButton:default:pressed {{
                background: {palette['focus_border']};
                opacity: 0.8;
            }}
            QPushButton:!default {{
                background: {palette['card_bg']};
                color: {palette['primary_text']};
                border: 1px solid {palette['field_border']};
            }}
            QPushButton:!default:hover {{
                background: {palette['tab_hover_bg']};
                border-color: {palette['focus_border']};
            }}
            QPushButton:!default:pressed {{
                background: {palette['tab_selected_bg']};
            }}
        """
        self._save_btn.setStyleSheet(button_style)
        self._cancel_btn.setStyleSheet(button_style)
        self._apply_btn.setStyleSheet(button_style)
        self._reset_section_btn.setStyleSheet(button_style)
        self._reset_btn.setStyleSheet(button_style)
        self._import_btn.setStyleSheet(button_style)
        self._export_btn.setStyleSheet(button_style)

        controls_container_layout.addLayout(controls_layout)
        controls_container_layout.addLayout(secondary_controls_layout)
        controls_container_layout.addLayout(primary_actions_layout)
        controls_container.setLayout(controls_container_layout)
        main_layout.addWidget(controls_container)
        self.setLayout(main_layout)

        self._dependent_widgets = [
            self.scrolling_edit_cb,
            self.invert_progress_cb,
            self.include_new_cb,
            self.include_rev_cb,
            self.include_lrn_cb,
            self.include_new_after_revs_cb,
            self.force_forward_cb,
            self.show_percent_cb,
            self.show_number_cb,
            self.show_yesterday_cb,
            self.label_style_combo,
            self.text_hierarchy_style_combo,
            self.compact_separators_cb,
            self.vertical_text_line_break_cb,
            self.show_again_cb,
            self.show_retention_cb,
            self.show_sm_retention_cb,
            self.show_debug_cb,
            self.show_progress_legend_cb,
            self.warnings_enabled_cb,
            self.time_warning_sb,
            self.again_warning_sb,
            self.retention_warning_sb,
            self.warning_hysteresis_sb,
            self.warning_cooldown_sb,
            self.warning_text_color_edit,
            self.warning_bg_color_edit,
            self.warning_fg_color_edit,
            self.daily_target_cards_sb,
            self.target_review_minutes_sb,
            self.pace_warnings_enabled_cb,
            self.pacing_strategy_combo,
            self.show_eta_confidence_cb,
            self.warning_hysteresis_sb,
            self.warning_cooldown_sb,
            self.auto_adjust_contrast_cb,
            self.onboarding_completed_cb,
            self.quick_setup_enabled_cb,
            self.focus_mode_cb,
            self.reduced_motion_cb,
            self.animated_updates_cb,
            self.show_segment_inline_labels_cb,
            self.show_warning_badge_cb,
            self.completion_celebration_cb,
            self.responsive_breakpoints_cb,
            self.lrn_steps_sb,
            self.no_days_sb,
            self.use_system_tz_cb,
            self.tz_sb,
            self.history_days_sb,
            self.orientation_combo,
            self.dock_area_combo,
            self.max_width_edit,
            self.pb_style_edit,
            self.counting_basis_combo,
            self.count_scope_combo,
            self.legend_position_combo,
            self.pacing_strategy_combo,
            self.shortcut_field,
        ]

        for checkbox in [
            self.progress_bar_enabled_cb,
            self.warnings_enabled_cb,
            self.use_system_tz_cb,
            self.pace_warnings_enabled_cb,
            self.include_new_cb,
            self.include_lrn_cb,
            self.include_rev_cb,
            self.include_new_after_revs_cb,
            self.force_forward_cb,
            self.scrolling_edit_cb,
            self.invert_progress_cb,
            self.show_percent_cb,
            self.show_number_cb,
            self.show_yesterday_cb,
            self.label_style_combo,
            self.text_hierarchy_style_combo,
            self.compact_separators_cb,
            self.vertical_text_line_break_cb,
            self.show_again_cb,
            self.show_retention_cb,
            self.show_sm_retention_cb,
            self.show_debug_cb,
            self.show_progress_legend_cb,
            self.show_eta_confidence_cb,
            self.auto_adjust_contrast_cb,
            self.onboarding_completed_cb,
            self.quick_setup_enabled_cb,
            self.focus_mode_cb,
            self.reduced_motion_cb,
            self.animated_updates_cb,
            self.show_segment_inline_labels_cb,
            self.show_warning_badge_cb,
            self.completion_celebration_cb,
            self.responsive_breakpoints_cb,
        ]:
            if hasattr(checkbox, "toggled"):
                checkbox.toggled.connect(self._on_value_changed)
            elif hasattr(checkbox, "currentIndexChanged"):
                checkbox.currentIndexChanged.connect(self._on_value_changed)

        for widget in [
            self.time_warning_sb,
            self.again_warning_sb,
            self.retention_warning_sb,
            self.warning_hysteresis_sb,
            self.warning_cooldown_sb,
            self.warning_text_color_edit,
            self.warning_bg_color_edit,
            self.warning_fg_color_edit,
            self.daily_target_cards_sb,
            self.target_review_minutes_sb,
            self.lrn_steps_sb,
            self.no_days_sb,
            self.tz_sb,
            self.history_days_sb,
            self.orientation_combo,
            self.dock_area_combo,
            self.max_width_edit,
            self.pb_style_edit,
            self.counting_basis_combo,
            self.count_scope_combo,
            self.legend_position_combo,
            self.pacing_strategy_combo,
        ]:
            self._watch_control(widget)

        self._search_field.textChanged.connect(self._apply_section_filter)
        self._sync_dependents_enabled()

    def _wrap_controls(self, controls: List[QWidget]) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for control in controls:
            layout.addWidget(control)
        wrapper.setLayout(layout)
        return wrapper

    def _stack_navigate(self, row: int) -> None:
        if 0 <= row < self._stack.count():
            self._stack.setCurrentIndex(row)
            if hasattr(self, "_section_selector") and self._section_selector.currentIndex() != row:
                self._section_selector.setCurrentIndex(row)

    def _section_selector_navigate(self, row: int) -> None:
        if 0 <= row < self._stack.count():
            self._stack.setCurrentIndex(row)
            if row < self._nav_list.count():
                item = self._nav_list.item(row)
                if self._nav_list.currentItem() is not item:
                    self._nav_list.setCurrentItem(item)

    def _apply_compact_mode(self, width: int) -> None:
        compact = bool(
            getattr(settings, "responsive_breakpoints", True)
            and width < 720
            and hasattr(self, "_section_selector")
            and hasattr(self, "_nav_frame")
        )
        self._compact_layout_active = compact
        self._section_selector.setVisible(compact)
        self._nav_frame.setVisible(not compact)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        try:
            width = self.width()
        except Exception:
            width = 840
        self._apply_compact_mode(width)
        try:
            super().resizeEvent(event)
        except Exception:
            return

    def _watch_control(self, control: QWidget) -> None:
        if isinstance(control, QCheckBox):
            control.toggled.connect(self._on_value_changed)
        elif isinstance(control, QLineEdit):
            control.textChanged.connect(self._on_value_changed)
        elif isinstance(control, QComboBox):
            control.currentIndexChanged.connect(self._on_value_changed)
        elif isinstance(control, (QSpinBox, QDoubleSpinBox)):
            control.valueChanged.connect(self._on_value_changed)
        elif isinstance(control, ColorPickerField):
            control.colorChanged.connect(self._on_value_changed)

    def _add_section_page(self, name: str, description: str, rows: List[SettingRow]) -> None:
        page = QWidget()
        page_layout = QVBoxLayout()
        page_layout.setContentsMargins(10, 10, 10, 10)
        page_layout.setSpacing(10)

        if description:
            desc_label = QLabel(description)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet(
                f"color: {self._palette_cache['secondary_text']}; font-weight: 500; font-size: 12px; "
                f"padding: 8px 12px; background: {self._palette_cache['card_bg']}; "
                f"border-radius: 6px; border-left: 3px solid {self._palette_cache['focus_border']}; margin-bottom: 4px;"
            )
            page_layout.addWidget(desc_label)

        for idx, row in enumerate(rows):
            page_layout.addWidget(row)
            self._register_row(name, row)
            # Add subtle separator between rows (except last)
            if idx < len(rows) - 1:
                separator = QFrame()
                separator.setFrameShape(QFrame.Shape.HLine)
                separator.setFrameShadow(QFrame.Shadow.Sunken)
                separator.setStyleSheet(f"color: {self._palette_cache['card_border']}; max-height: 1px;")
                page_layout.addWidget(separator)
        page_layout.addStretch()
        page.setLayout(page_layout)

        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)

        self._stack.addWidget(scroll)
        item = QListWidgetItem(name)
        self._nav_list.addItem(item)
        self._section_selector.addItem(name, name)
        self._nav_items[name] = item
        self._section_meta[name] = {"rows": rows, "scroll": scroll}
        if self._nav_list.count() == 1:
            self._nav_list.setCurrentItem(item)

    def _register_row(self, section: str, row: SettingRow) -> None:
        self._rows.append({"section": section, "row": row})
        self._watch_control(row.control)

    def _clear_filter(self) -> None:
        self._search_field.clear()

    def _apply_section_filter(self, text: str) -> None:
        query = (text or "").strip().lower()
        has_query = bool(query)
        self._clear_filter_btn.setVisible(has_query)

        matched_sections: Dict[str, bool] = {name: False for name in self._section_meta}
        first_match_section: Optional[str] = None

        for entry in self._rows:
            row: SettingRow = entry["row"]
            section = entry["section"]
            is_match = row.matches(query)
            row.setVisible(is_match or not has_query)
            row.set_highlighted(has_query and is_match)
            if has_query and is_match:
                matched_sections[section] = True
                if first_match_section is None:
                    first_match_section = section
            elif not has_query:
                matched_sections[section] = True

        any_match = any(matched_sections.values())
        self._no_results_label.setVisible(has_query and not any_match)

        for idx in range(self._nav_list.count()):
            item = self._nav_list.item(idx)
            section_name = item.text()
            hide = has_query and not matched_sections.get(section_name, False)
            self._nav_list.setRowHidden(idx, hide)

        if has_query and first_match_section:
            item = self._nav_items.get(first_match_section)
            if item:
                self._nav_list.setCurrentItem(item)

        for name, meta in self._section_meta.items():
            has_visible = matched_sections.get(name, False)
            meta["scroll"].setVisible(has_visible or not has_query)

    def _toggle_nav(self) -> None:
        hidden = self._nav_list.isVisible()
        self._nav_list.setVisible(not hidden)
        self._collapse_btn.setText("Show navigation" if hidden else "Hide navigation")

    def _build_preset_definitions(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": "minimal",
                "name": "Minimal focus",
                "description": "Keep the bar lightweight with a single percent label and no warnings.",
                "values": {
                    "show_percent": True,
                    "show_number": False,
                    "show_again": False,
                    "show_retention": False,
                    "show_super_mature_retention": False,
                    "warnings_enabled": False,
                    "dock_area": "top",
                    "orientation": "horizontal",
                    "display_preset": "minimal",
                    "pacing_strategy": "median",
                },
            },
            {
                "id": "compact",
                "name": "Compact",
                "description": "Show counts plus key rates with warnings enabled at the bottom.",
                "values": {
                    "show_percent": True,
                    "show_number": True,
                    "show_again": True,
                    "show_retention": True,
                    "warnings_enabled": True,
                    "dock_area": "bottom",
                    "orientation": "horizontal",
                    "display_preset": "compact",
                    "pacing_strategy": "ewma",
                },
            },
            {
                "id": "vertical_compact",
                "name": "Vertical compact",
                "description": "Dock a vertical bar with just percent and warnings for side layouts.",
                "values": {
                    "show_percent": True,
                    "show_number": False,
                    "show_again": False,
                    "show_retention": False,
                    "warnings_enabled": True,
                    "dock_area": "right",
                    "orientation": "vertical",
                },
            },
            {
                "id": "expanded",
                "name": "Expanded",
                "description": "Surface most metrics, including retention variants and warning colors.",
                "values": {
                    "show_percent": True,
                    "show_number": True,
                    "show_again": True,
                    "show_retention": True,
                    "show_super_mature_retention": True,
                    "warnings_enabled": True,
                    "dock_area": "bottom",
                    "orientation": "horizontal",
                    "display_preset": "expanded",
                    "pacing_strategy": "segmented",
                },
            },
        ]

    def _toggle_preset_changes(self, expanded: bool) -> None:
        self._preset_changes_container.setVisible(expanded)
        self._preset_changes_toggle.setArrowType(
            _arrow_type("DownArrow") if expanded else _arrow_type("RightArrow")
        )
        self._preset_changes_toggle.setText("Hide changes" if expanded else "Show changes")

    def _apply_preset_selection(self) -> None:
        preset_id = self._preset_combo.currentData()
        preset = next((item for item in self._preset_definitions if item["id"] == preset_id), None)
        if preset is None:
            self._preset_description.setText("Select a curated preset to quickly apply a layout and label mix.")
            self._refresh_preset_changes()
            return
        self._preset_description.setText(preset["description"])
        self._apply_preset_values(preset["values"])

    def _apply_preset_values(self, values: Dict[str, Any]) -> None:
        if self._building_ui:
            return
        updated_config = self._gather_config()
        for key, value in values.items():
            updated_config[key] = value
        if "display_preset" in values:
            self._selected_display_preset = str(values["display_preset"]).lower()
        self._building_ui = True
        self._populate_from_config(updated_config)
        self._building_ui = False
        self._update_dirty_state(True)
        self._update_preview()
        self._refresh_preset_changes()
        self._apply_autosave_if_enabled()

    def _refresh_preset_changes(self) -> None:
        preset_id = self._preset_combo.currentData()
        preset = next((item for item in self._preset_definitions if item["id"] == preset_id), None)
        if preset is None:
            self._preset_changes_label.setText("Select a preset to see the changes it will apply.")
            return
        changed_keys = [
            key
            for key, value in preset["values"].items()
            if self._config_snapshot.get(key) != value
        ]
        if not changed_keys:
            self._preset_changes_label.setText("This preset matches your current saved configuration.")
            return
        formatted_items = "\n".join(f"<li><code>{key}</code></li>" for key in sorted(changed_keys))
        self._preset_changes_label.setText(
            "Preset will update:<br><ul style='margin-left: 16px;'>" + formatted_items + "</ul>"
        )

    def _preview_format_text(self) -> str:
        show_percent = self.show_percent_cb.isChecked()
        show_number = self.show_number_cb.isChecked()
        show_again = self.show_again_cb.isChecked()
        show_retention = self.show_retention_cb.isChecked()
        show_sm_retention = self.show_sm_retention_cb.isChecked()

        done = 45
        total = 100
        left = total - done
        percent = int(round((done / total) * 100))

        primary_parts: List[str] = []
        secondary_parts: List[str] = []

        if show_number and show_percent:
            primary_parts.append(f"{done}/{total} ({percent}%)")
        elif show_number:
            primary_parts.append(f"{done}/{total}")
        elif show_percent:
            primary_parts.append(f"{percent}% done")

        primary_parts.append("ETA 7:30 PM")
        secondary_parts.append(f"Left {left}")
        if show_again:
            secondary_parts.append("12 Again")
        if show_retention:
            secondary_parts.append("92% TR")
        if show_sm_retention:
            secondary_parts.append("88% SMTR")

        orientation_vertical = self.orientation_combo.currentData() == "vertical"
        return _format_hierarchical_progress_text(
            primary_parts,
            secondary_parts,
            hierarchy_style=self.text_hierarchy_style_combo.currentData(),
            compact_separators=self.compact_separators_cb.isChecked(),
            vertical=orientation_vertical,
            vertical_line_break=self.vertical_text_line_break_cb.isChecked(),
        )

    def _preview_style_parts(self) -> Tuple[QPalette, str, Optional[QStyle]]:
        active_theme = settings.active_theme if settings is not None else None
        if active_theme is None:
            return QPalette(), "", None

        warning_text = self.warning_text_color_edit.value().strip() or active_theme.text
        warning_bg = self.warning_bg_color_edit.value().strip() or active_theme.background
        warning_fg = self.warning_fg_color_edit.value().strip() or active_theme.foreground

        use_warning = self.warnings_enabled_cb.isChecked()
        text_color = warning_text if use_warning else active_theme.text
        background_color = warning_bg if use_warning else active_theme.background
        foreground_color = warning_fg if use_warning else active_theme.foreground

        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Base, QColor(background_color))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(foreground_color))
        palette.setColor(QPalette.ColorRole.Button, QColor(background_color))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(text_color))
        palette.setColor(QPalette.ColorRole.Window, QColor(background_color))

        max_width = _normalize_dimension(self.max_width_edit.text().strip())
        orientation = self.orientation_combo.currentData()
        restrict_size = ""
        if max_width:
            restrict_size = (
                f"max-width: {max_width};"
                if orientation == "horizontal"
                else f"max-height: {max_width};"
            )
        stylesheet = (
            '''
                QProgressBar
                {
                    text-align:center;
                    color:%s;
                    background-color: %s;
                    border-radius: %dpx;
                    %s
                }
                QProgressBar::chunk
                {
                    background-color: %s;
                    margin: 0px;
                    border-radius: %dpx;
                }
                ''' % (
                text_color,
                background_color,
                active_theme.border_radius,
                restrict_size,
                foreground_color,
                active_theme.border_radius,
            )
        )

        qstyle = None
        style_name = self.pb_style_edit.text().strip()
        if style_name:
            qstyle = addon_config._resolve_qstyle(style_name)
        return palette, stylesheet, qstyle

    def _update_preview(self) -> None:
        if not hasattr(self, "_preview_bar"):
            return
        show_text = self.show_percent_cb.isChecked() or self.show_number_cb.isChecked()
        self._preview_bar.setTextVisible(show_text)
        preview_text = self._preview_format_text()
        if show_text and preview_text:
            self._preview_bar.setFormat(preview_text)
        else:
            self._preview_bar.setFormat("")
        orientation = self.orientation_combo.currentData()
        if orientation == "vertical":
            self._preview_bar.setOrientation(Qt.Orientation.Vertical)
            self._preview_bar.setMinimumWidth(28)
        else:
            self._preview_bar.setOrientation(Qt.Orientation.Horizontal)
            self._preview_bar.setMinimumWidth(180 if self._compact_layout_active else 260)
        self._preview_bar.setInvertedAppearance(self.invert_progress_cb.isChecked())
        palette, stylesheet, qstyle = self._preview_style_parts()
        progress_ui.apply_bar_style_to(self._preview_bar, palette, stylesheet, qstyle)

        if isinstance(self._preview_bar, progress_ui.SegmentedProgressBar):
            self._preview_bar.setSegmentData(18, 12, 25, 0.45)

    def _populate_from_config(self, cfg: Dict[str, Any]) -> None:
        preset = str(cfg.get("display_preset", self._selected_display_preset or "compact")).lower()
        self._selected_display_preset = preset if preset in {"minimal", "compact", "expanded"} else "compact"
        self.progress_bar_enabled_cb.setChecked(_coerce_bool(cfg.get("progress_bar_enabled"), True))
        self.include_new_cb.setChecked(_coerce_bool(cfg.get("include_new"), True))
        self.include_rev_cb.setChecked(_coerce_bool(cfg.get("include_rev"), True))
        self.include_lrn_cb.setChecked(_coerce_bool(cfg.get("include_lrn"), True))
        self.include_new_after_revs_cb.setChecked(_coerce_bool(cfg.get("include_new_after_revs"), False))
        self.force_forward_cb.setChecked(_coerce_bool(cfg.get("force_forward"), False))
        self.scrolling_edit_cb.setChecked(_coerce_bool(cfg.get("scrolling_bar_when_editing"), True))
        self.invert_progress_cb.setChecked(_coerce_bool(cfg.get("invert_progress"), False))
        self.show_percent_cb.setChecked(_coerce_bool(cfg.get("show_percent"), True))
        self.show_number_cb.setChecked(_coerce_bool(cfg.get("show_number"), True))
        self.show_yesterday_cb.setChecked(_coerce_bool(cfg.get("show_yesterday"), True))
        hierarchy_style = str(cfg.get("text_hierarchy_style", "compact")).lower()
        self.text_hierarchy_style_combo.setCurrentIndex(max(0, self.text_hierarchy_style_combo.findData(hierarchy_style)))
        label_style = str(cfg.get("label_style", "detailed")).lower()
        self.label_style_combo.setCurrentIndex(max(0, self.label_style_combo.findData(label_style)))
        self.compact_separators_cb.setChecked(_coerce_bool(cfg.get("compact_separators"), True))
        self.vertical_text_line_break_cb.setChecked(_coerce_bool(cfg.get("vertical_text_line_break"), True))
        self.show_again_cb.setChecked(_coerce_bool(cfg.get("show_again"), True))
        self.show_retention_cb.setChecked(_coerce_bool(cfg.get("show_retention"), True))
        self.show_sm_retention_cb.setChecked(_coerce_bool(cfg.get("show_super_mature_retention"), True))
        self.show_debug_cb.setChecked(_coerce_bool(cfg.get("show_debug"), False))
        self.show_progress_legend_cb.setChecked(_coerce_bool(cfg.get("show_progress_legend"), False))
        self.warnings_enabled_cb.setChecked(_coerce_bool(cfg.get("warnings_enabled"), False))
        self.pace_warnings_enabled_cb.setChecked(_coerce_bool(cfg.get("pace_warnings_enabled"), True))
        self.show_eta_confidence_cb.setChecked(_coerce_bool(cfg.get("show_eta_confidence"), True))
        self.auto_adjust_contrast_cb.setChecked(_coerce_bool(cfg.get("auto_adjust_contrast"), True))
        self.onboarding_completed_cb.setChecked(_coerce_bool(cfg.get("onboarding_completed"), False))
        self.quick_setup_enabled_cb.setChecked(_coerce_bool(cfg.get("quick_setup_enabled"), True))
        self.focus_mode_cb.setChecked(_coerce_bool(cfg.get("focus_mode"), False))
        self.reduced_motion_cb.setChecked(_coerce_bool(cfg.get("reduced_motion"), False))
        self.animated_updates_cb.setChecked(_coerce_bool(cfg.get("animated_updates"), True))
        self.show_segment_inline_labels_cb.setChecked(_coerce_bool(cfg.get("show_segment_inline_labels"), False))
        self.show_warning_badge_cb.setChecked(_coerce_bool(cfg.get("show_warning_badge"), True))
        self.completion_celebration_cb.setChecked(_coerce_bool(cfg.get("completion_celebration"), True))
        self.responsive_breakpoints_cb.setChecked(_coerce_bool(cfg.get("responsive_breakpoints"), True))

        self.time_warning_sb.setValue(_coerce_int(cfg.get("time_warning_minutes"), 45))
        self.again_warning_sb.setValue(int(round(_coerce_float(cfg.get("again_warning_percent"), 15.0))))
        self.retention_warning_sb.setValue(int(round(_coerce_float(cfg.get("retention_warning_percent"), 80.0))))
        self.warning_hysteresis_sb.setValue(_coerce_float(cfg.get("warning_hysteresis_percent"), 2.0))
        self.warning_cooldown_sb.setValue(_coerce_int(cfg.get("warning_cooldown_seconds"), 15))

        warning_colors = cfg.get("warning_colors", {}) if isinstance(cfg.get("warning_colors"), dict) else {}
        self.warning_text_color_edit.set_color(str(warning_colors.get("text", "")))
        self.warning_bg_color_edit.set_color(str(warning_colors.get("background", "")))
        self.warning_fg_color_edit.set_color(str(warning_colors.get("foreground", "")))

        self.daily_target_cards_sb.setValue(_coerce_int(cfg.get("daily_target_cards"), 0))
        self.target_review_minutes_sb.setValue(_coerce_int(cfg.get("target_review_minutes"), 0))

        self.lrn_steps_sb.setValue(_coerce_int(cfg.get("lrn_steps"), 2))
        self.no_days_sb.setValue(_coerce_int(cfg.get("no_days"), 7))

        use_system_timezone = _coerce_bool(cfg.get("use_system_timezone"), True)
        self.use_system_tz_cb.setChecked(use_system_timezone)
        self.tz_sb.setValue(_coerce_int(cfg.get("tz"), 0))
        self.tz_sb.setEnabled(not use_system_timezone)
        self.history_days_sb.setValue(_coerce_int(cfg.get("history_days"), 30))

        current_orientation = str(cfg.get("orientation", "horizontal")).lower()
        self.orientation_combo.setCurrentIndex(max(0, self.orientation_combo.findData(current_orientation)))

        current_dock = str(cfg.get("dock_area", "top")).lower()
        self.dock_area_combo.setCurrentIndex(max(0, self.dock_area_combo.findData(current_dock)))

        legend_position = str(cfg.get("legend_position", "below")).lower()
        self.legend_position_combo.setCurrentIndex(max(0, self.legend_position_combo.findData(legend_position)))

        self.max_width_edit.setText(str(cfg.get("max_width", "")))
        self.pb_style_edit.setText(str(cfg.get("progress_bar_style", "")))

        basis = str(cfg.get("counting_basis", "answered")).lower()
        scope = str(cfg.get("count_scope", "per_deck")).lower()
        self.counting_basis_combo.setCurrentIndex(max(0, self.counting_basis_combo.findData(basis)))
        self.count_scope_combo.setCurrentIndex(max(0, self.count_scope_combo.findData(scope)))
        pace_strategy = str(cfg.get("pacing_strategy", "ewma")).lower()
        self.pacing_strategy_combo.setCurrentIndex(max(0, self.pacing_strategy_combo.findData(pace_strategy)))

        shortcut = str(cfg.get("toggle_shortcut", self.shortcut_field.value()))
        if sys.platform == "darwin" and shortcut.lower() == "ctrl+g":
            shortcut = "Meta+G"
        self.shortcut_field.set_shortcut(shortcut)

        self._sync_dependents_enabled()
        self._update_preview()

    def _gather_config(self) -> Dict[str, Any]:
        updated_config = deepcopy(config)
        updated_config["progress_bar_enabled"] = self.progress_bar_enabled_cb.isChecked()
        updated_config["include_new"] = self.include_new_cb.isChecked()
        updated_config["include_rev"] = self.include_rev_cb.isChecked()
        updated_config["include_lrn"] = self.include_lrn_cb.isChecked()
        updated_config["include_new_after_revs"] = self.include_new_after_revs_cb.isChecked()
        updated_config["force_forward"] = self.force_forward_cb.isChecked()
        updated_config["show_percent"] = self.show_percent_cb.isChecked()
        updated_config["show_number"] = self.show_number_cb.isChecked()
        updated_config["show_retention"] = self.show_retention_cb.isChecked()
        updated_config["show_super_mature_retention"] = self.show_sm_retention_cb.isChecked()
        updated_config["show_again"] = self.show_again_cb.isChecked()
        updated_config["show_yesterday"] = self.show_yesterday_cb.isChecked()
        updated_config["text_hierarchy_style"] = self.text_hierarchy_style_combo.currentData()
        updated_config["label_style"] = self.label_style_combo.currentData()
        updated_config["compact_separators"] = self.compact_separators_cb.isChecked()
        updated_config["vertical_text_line_break"] = self.vertical_text_line_break_cb.isChecked()
        updated_config["show_debug"] = self.show_debug_cb.isChecked()
        updated_config["show_progress_legend"] = self.show_progress_legend_cb.isChecked()
        updated_config["scrolling_bar_when_editing"] = self.scrolling_edit_cb.isChecked()
        updated_config["invert_progress"] = self.invert_progress_cb.isChecked()
        updated_config["lrn_steps"] = self.lrn_steps_sb.value()
        updated_config["no_days"] = self.no_days_sb.value()
        updated_config["use_system_timezone"] = self.use_system_tz_cb.isChecked()
        updated_config["tz"] = self.tz_sb.value()
        updated_config["history_days"] = self.history_days_sb.value()
        updated_config["orientation"] = self.orientation_combo.currentData()
        updated_config["dock_area"] = self.dock_area_combo.currentData()
        updated_config["legend_position"] = self.legend_position_combo.currentData()
        updated_config["max_width"] = self.max_width_edit.text().strip()
        updated_config["progress_bar_style"] = self.pb_style_edit.text().strip()
        updated_config["warnings_enabled"] = self.warnings_enabled_cb.isChecked()
        updated_config["time_warning_minutes"] = self.time_warning_sb.value()
        updated_config["again_warning_percent"] = self.again_warning_sb.value()
        updated_config["retention_warning_percent"] = self.retention_warning_sb.value()
        updated_config["warning_hysteresis_percent"] = self.warning_hysteresis_sb.value()
        updated_config["warning_cooldown_seconds"] = self.warning_cooldown_sb.value()
        updated_config["warning_colors"] = {
            "text": self.warning_text_color_edit.value().strip(),
            "background": self.warning_bg_color_edit.value().strip(),
            "foreground": self.warning_fg_color_edit.value().strip(),
        }
        updated_config["daily_target_cards"] = self.daily_target_cards_sb.value()
        updated_config["target_review_minutes"] = self.target_review_minutes_sb.value()
        updated_config["pace_warnings_enabled"] = self.pace_warnings_enabled_cb.isChecked()
        updated_config["pacing_strategy"] = self.pacing_strategy_combo.currentData()
        updated_config["show_eta_confidence"] = self.show_eta_confidence_cb.isChecked()
        updated_config["auto_adjust_contrast"] = self.auto_adjust_contrast_cb.isChecked()
        updated_config["onboarding_completed"] = self.onboarding_completed_cb.isChecked()
        updated_config["quick_setup_enabled"] = self.quick_setup_enabled_cb.isChecked()
        updated_config["focus_mode"] = self.focus_mode_cb.isChecked()
        updated_config["reduced_motion"] = self.reduced_motion_cb.isChecked()
        updated_config["animated_updates"] = self.animated_updates_cb.isChecked()
        updated_config["show_segment_inline_labels"] = self.show_segment_inline_labels_cb.isChecked()
        updated_config["show_warning_badge"] = self.show_warning_badge_cb.isChecked()
        updated_config["completion_celebration"] = self.completion_celebration_cb.isChecked()
        updated_config["responsive_breakpoints"] = self.responsive_breakpoints_cb.isChecked()
        updated_config["counting_basis"] = self.counting_basis_combo.currentData()
        updated_config["count_scope"] = self.count_scope_combo.currentData()
        updated_config["display_preset"] = self._selected_display_preset

        shortcut = self.shortcut_field.value().strip() or self.shortcut_field._default
        updated_config["toggle_shortcut"] = shortcut
        return updated_config

    def _sync_dependents_enabled(self) -> None:
        enabled = self.progress_bar_enabled_cb.isChecked()
        for widget in getattr(self, "_dependent_widgets", []):
            widget.setEnabled(enabled)
        self._sync_warning_controls()

    def _sync_warning_controls(self) -> None:
        warnings_enabled = self.warnings_enabled_cb.isChecked() and self.progress_bar_enabled_cb.isChecked()
        self.animated_updates_cb.setEnabled(not self.reduced_motion_cb.isChecked())
        for widget in (
            self.time_warning_sb,
            self.again_warning_sb,
            self.retention_warning_sb,
            self.warning_hysteresis_sb,
            self.warning_cooldown_sb,
            self.warning_text_color_edit,
            self.warning_bg_color_edit,
            self.warning_fg_color_edit,
            self.warning_hysteresis_sb,
            self.warning_cooldown_sb,
        ):
            widget.setEnabled(warnings_enabled)

    def _update_dirty_state(self, dirty: bool) -> None:
        self._dirty = dirty
        if dirty:
            self._dirty_badge.setText("● Unsaved changes")
            self._dirty_badge.setStyleSheet(
                "QLabel { padding: 6px 12px; border-radius: 12px; font-weight: 700; font-size: 11px; background: #f97316; color: white; }"
            )
        else:
            self._dirty_badge.setText("✓ All saved")
            self._dirty_badge.setStyleSheet(
                "QLabel { padding: 6px 12px; border-radius: 12px; font-weight: 700; font-size: 11px; background: #10b981; color: white; }"
            )
        self._save_btn.setEnabled(dirty and not self.shortcut_field.has_conflict())

    def _on_value_changed(self, *args) -> None:  # noqa: ARG002
        if self._building_ui:
            return
        self._sync_dependents_enabled()
        self._update_dirty_state(True)
        self._update_preview()
        self._apply_autosave_if_enabled()

    def _apply_autosave_if_enabled(self) -> None:
        if not self._autosave_cb.isChecked():
            return
        self._write_config(show_toast=True, close=False)


    def _apply_without_closing(self) -> None:
        if self.shortcut_field.has_conflict():
            QMessageBox.warning(self, "Shortcut conflict", "Please resolve the shortcut conflict before applying.")
            return
        self._write_config(show_toast=True, close=False)

    def _reset_current_section_to_defaults(self) -> None:
        if not self._defaults:
            QMessageBox.warning(self, "Progress Bar", "No defaults found to reset to.")
            return
        item = self._nav_list.currentItem()
        if item is None:
            self._reset_to_defaults()
            return
        section = item.text()
        scoped = dict(self._config_snapshot)
        reset_keys = self._section_keys_map().get(section, [])
        for key in reset_keys:
            if key in self._defaults:
                scoped[key] = deepcopy(self._defaults[key])
            else:
                scoped.pop(key, None)
        self._populate_from_config(scoped)
        self._update_dirty_state(True)

    def _section_keys_map(self) -> Dict[str, List[str]]:
        return {
            "Visibility": ["progress_bar_enabled", "show_percent", "show_number", "show_yesterday", "text_hierarchy_style", "label_style", "compact_separators", "vertical_text_line_break"],
            "Queues": ["include_new", "include_rev", "include_lrn", "include_new_after_revs", "counting_basis", "count_scope", "force_forward"],
            "Goals & Pace": ["daily_target_cards", "target_review_minutes", "pace_warnings_enabled", "pacing_strategy", "show_eta_confidence"],
            "Warnings": ["warnings_enabled", "time_warning_minutes", "again_warning_percent", "retention_warning_percent", "warning_hysteresis_percent", "warning_cooldown_seconds", "warning_colors", "show_warning_badge"],
            "Appearance": ["orientation", "dock_area", "max_width", "progress_bar_style", "show_again", "show_retention", "show_super_mature_retention", "show_debug", "show_progress_legend", "legend_position", "stacked_segments", "segment_colors"],
            "History": ["history_days"],
            "Advanced": ["lrn_steps", "no_days", "use_system_timezone", "tz", "auto_adjust_contrast", "focus_mode", "reduced_motion", "animated_updates", "show_segment_inline_labels", "completion_celebration", "responsive_breakpoints", "onboarding_completed", "quick_setup_enabled"],
            "Shortcuts": ["toggle_shortcut"],
            "Behavior": ["scrolling_bar_when_editing", "invert_progress"],
        }

    def _reset_to_defaults(self) -> None:
        if not self._defaults:
            QMessageBox.warning(self, "Progress Bar", "No defaults found to reset to.")
            return
        confirm = QMessageBox.question(
            self,
            "Reset to defaults",
            "Reset all settings to their defaults? This cannot be undone.",
            _message_box_button("Yes") | _message_box_button("No"),
        )
        if confirm != _message_box_button("Yes"):
            return
        self._populate_from_config(self._defaults)
        self._update_dirty_state(True)

    def _validate_before_write(self, updated_config: Dict[str, Any]) -> Optional[str]:
        max_width_value = str(updated_config.get("max_width", "")).strip()
        if max_width_value:
            normalized = _normalize_dimension(max_width_value)
            if normalized != max_width_value and not max_width_value.isdigit():
                return "max_width should be a CSS size (e.g. 320px, 60%, 12em)."
        for key in ("again_warning_percent", "retention_warning_percent"):
            try:
                value = float(updated_config.get(key, 0))
            except Exception:
                return f"{key} must be numeric."
            if value < 0 or value > 100:
                return f"{key} must be between 0 and 100."
        return None

    def _write_config(self, *, show_toast: bool, close: bool) -> None:
        updated_config = self._gather_config()
        validation_message = self._validate_before_write(updated_config)
        if validation_message:
            QMessageBox.warning(self, "Progress Bar", validation_message)
            return
        mw.addonManager.writeConfig(addon_config.CONFIG_KEY, updated_config)
        _apply_settings(show_messages=False)
        self._config_snapshot = deepcopy(updated_config)
        self._update_dirty_state(False)
        self._refresh_preset_changes()
        if show_toast:
            tooltip("Autosaved Progress Bar settings.", parent=mw, period=2000)
        elif close:
            QMessageBox.information(
                self,
                "Progress Bar",
                "Settings saved. The progress bar will refresh with your new choices.",
            )
        if close:
            self.accept()

    def _save_and_close(self) -> None:
        if not self._dirty and not self.shortcut_field.has_conflict():
            self.reject()
            return
        if self.shortcut_field.has_conflict():
            QMessageBox.warning(self, "Shortcut conflict", "Please resolve the shortcut conflict before saving.")
            return
        self._write_config(show_toast=False, close=True)

    def _import_settings(self) -> None:
        """Import settings from a JSON file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Progress Bar Settings",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                imported_config = json.load(f)
            
            if not isinstance(imported_config, dict):
                QMessageBox.warning(self, "Import Error", "The file does not contain valid settings.")
                return

            confirm = QMessageBox.question(
                self,
                "Import Settings",
                "This will replace your current settings. Continue?",
                _message_box_button("Yes") | _message_box_button("No"),
            )
            if confirm != _message_box_button("Yes"):
                return

            self._populate_from_config(imported_config)
            self._update_dirty_state(True)
            QMessageBox.information(
                self,
                "Import Successful",
                "Settings imported successfully. Click Save to apply them.",
            )
        except json.JSONDecodeError:
            QMessageBox.warning(self, "Import Error", "The file is not valid JSON.")
        except Exception as e:
            QMessageBox.warning(self, "Import Error", f"Failed to import settings: {str(e)}")

    def _export_settings(self) -> None:
        """Export current settings to a JSON file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Progress Bar Settings",
            "progress_bar_settings.json",
            "JSON Files (*.json);;All Files (*)",
        )
        if not file_path:
            return

        try:
            # Ensure .json extension
            if not file_path.lower().endswith(".json"):
                file_path += ".json"

            current_config = self._gather_config()
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(current_config, f, indent=2, ensure_ascii=False)

            QMessageBox.information(
                self,
                "Export Successful",
                f"Settings exported successfully to:\n{file_path}",
            )
        except Exception as e:
            QMessageBox.warning(self, "Export Error", f"Failed to export settings: {str(e)}")


def _open_config_dialog() -> None:
    dialog = ProgressBarConfigDialog(mw)
    dialog.exec()


def _open_session_history_dialog() -> None:
    dialog = SessionHistoryDialog(mw)
    dialog.exec()


def _reload_configuration_action() -> None:
    _apply_settings(show_messages=True)
    tooltip("Progress Bar configuration reloaded.", parent=mw, period=2000)


def _open_troubleshooting_dialog() -> None:
    version = "unknown"
    try:
        meta = mw.addonManager.addonMeta(__name__) or {}
        version = str(meta.get("mod", "unknown"))
    except Exception:
        pass
    lines = [
        "Progress Bar Time Left",
        f"Version: {version}",
        f"Config source: {addon_config.CONFIG_KEY}",
        f"Last reload: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "Quick links:",
        "• Tools → Progress Bar → Settings…",
        "• Tools → Progress Bar → Reload Configuration",
        "• Tools → Add-ons → Progress Bar Time Left → Config",
    ]
    QMessageBox.information(mw, "Progress Bar Troubleshooting / About", "\n".join(lines))


def _open_json_config_in_addon_manager() -> None:
    try:
        mw.onAddons()
    except Exception:
        QMessageBox.information(mw, "Progress Bar", "Open Tools → Add-ons and edit Progress Bar Time Left config JSON.")


def _validate_current_config_action() -> None:
    errors = addon_config.validate_config_payload(mw, config)
    if errors:
        QMessageBox.warning(
            mw,
            "Progress Bar config validation",
            "Found issues (defaults will be used where needed):\n\n" + "\n".join(errors),
        )
    else:
        tooltip("Progress Bar config is valid.", parent=mw, period=2000)


def _rerun_quick_setup_action() -> None:
    _open_quick_setup_wizard(force=True)


def _show_first_run_hint() -> None:
    if settings.onboarding_completed:
        return
    msg = QMessageBox(mw)
    msg.setWindowTitle("Progress Bar Time Left")
    msg.setText("Tip: Hover the bar for explanations and click it for deck breakdown. Open Tools → Progress Bar → Settings… to customize.")
    if hasattr(msg, "setIcon"):
        msg.setIcon(_message_box_icon("Information"))
    dont_show = QCheckBox("Do not show again")
    if hasattr(msg, "setCheckBox"):
        msg.setCheckBox(dont_show)
    msg.exec()
    if dont_show.isChecked():
        updated = dict(config)
        updated["onboarding_completed"] = True
        addon_config.apply_config(mw, updated)
        _reload_settings(show_messages=False)


def _startup_quick_setup() -> None:
    _open_quick_setup_wizard(force=False)
    _show_first_run_hint()


def _is_anki_20() -> bool:
    try:
        parts = [int(p) for p in anki_version.split(".")[:2]]
        major = parts[0] if len(parts) > 0 else 0
        minor = parts[1] if len(parts) > 1 else 0
        return (major, minor) < (2, 1)
    except Exception:
        return False

if _is_anki_20():
    """Workaround for QSS issue in EditCurrent,
    only necessary on Anki 2.0.x"""

    from aqt.editcurrent import EditCurrent


    def changeStylesheet(*args):
        mw.setStyleSheet('''
            QMainWindow::separator
        {
            width: 0px;
            height: 0px;
        }
        ''')


    def restoreStylesheet(*args):
        mw.setStyleSheet("")


    EditCurrent.__init__ = wrap(
        EditCurrent.__init__, restoreStylesheet, "after")
    EditCurrent.onReset = wrap(
        EditCurrent.onReset, changeStylesheet, "after")
    EditCurrent.onSave = wrap(
        EditCurrent.onSave, changeStylesheet, "afterwards")
    
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
        if progress_ui.progressBar is None:
            initPB()
        if progress_ui.progressBar is not None:
            progress_ui.progressBar.show()
            _ensure_persisted_progress_loaded()
            updateCountsForAllDecks(True)
            updatePB()
    else:
        _remove_progress_bar()

settings_action = QAction("Settings…", mw)
settings_action.triggered.connect(_open_config_dialog)

reload_action = QAction("Reload Configuration", mw)
reload_action.triggered.connect(_reload_configuration_action)
open_config_action = QAction("Open Config JSON", mw)
open_config_action.triggered.connect(_open_json_config_in_addon_manager)
validate_config_action = QAction("Validate Config", mw)
validate_config_action.triggered.connect(_validate_current_config_action)
troubleshooting_action = QAction("Troubleshooting / About", mw)
troubleshooting_action.triggered.connect(_open_troubleshooting_dialog)
quick_setup_action = QAction("Re-run Quick Setup", mw)
quick_setup_action.triggered.connect(_rerun_quick_setup_action)

progress_ui.update_toggle_shortcut(toggleProgressBar)
_tools_progress_menu: Optional[Any] = None


def _get_tools_progress_menu() -> Any:
    global _tools_progress_menu
    if _tools_progress_menu is None:
        tools_menu = getattr(getattr(mw, "form", None), "menuTools", None)
        add_menu = getattr(tools_menu, "addMenu", None)
        if callable(add_menu):
            _tools_progress_menu = add_menu("Progress Bar")
        else:
            _tools_progress_menu = tools_menu
    return _tools_progress_menu

def _add_history_menu_action() -> None:
    history_action = QAction("Progress Bar Time Left → Session History", mw)
    history_action.triggered.connect(_open_session_history_dialog)
    _get_tools_progress_menu().addAction(history_action)


# Add settings/reload actions to the Tools menu (toggling lives inside the dialog)
progress_menu = _get_tools_progress_menu()
progress_menu.addAction(settings_action)
progress_menu.addAction(reload_action)
progress_menu.addAction(open_config_action)
progress_menu.addAction(validate_config_action)
progress_menu.addAction(troubleshooting_action)
progress_menu.addAction(quick_setup_action)
gui_hooks.main_window_did_init.append(_add_history_menu_action)
gui_hooks.main_window_did_init.append(_startup_quick_setup)
