from __future__ import unicode_literals
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
from .history import HISTORY_PROGRESS_KEY, SessionHistoryDialog
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

def __getattr__(name: str):
    if name in {"progressBar", "toggle_shortcut"}:
        return getattr(progress_ui, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

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
    if mw.col is not None:
        add_info()
    progress_ui.update_toggle_shortcut(toggleProgressBar)
    _reinitialize_progress_bar()


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


_reload_settings(show_messages=True)

PERSISTED_PROGRESS_KEY = "progress_bar_persistent_counts"
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

    deck_tree = mw.col.sched.deck_due_tree()
    deck_ids_for_query: List[int] = []
    for node in deck_tree.children:
        deck_ids_for_query.extend(_collect_deck_ids(node))
    deck_ids_for_query = list(dict.fromkeys(deck_ids_for_query))
    history.update_daily_history(profile, today, deck_ids_for_query, _revlog_stats_between)

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

    return mw.col.db.first(query, *params)


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

    if raw_done > 0:
        safe_time = max(thetime, 1)
        speed = (raw_done / safe_time) * 60
        secspeed_value = safe_time / raw_done
        secspeed_display = f"{secspeed_value:.02f}"
    else:
        speed = 0
        secspeed_value = 0
        secspeed_display = "N/A"

    if ycards > 0:
        safe_ytime = max(ythetime, 1)
        ysecspeed_value = safe_ytime / ycards
        ysecspeed_display = f"{ysecspeed_value:.02f}"
    else:
        ysecspeed_value = 0
        ysecspeed_display = "N/A"

    if speed > 0:
        seconds_remaining = int(round((var_diff / speed) * 60))
    else:
        seconds_remaining = 0

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
    eta_display = "N/A"
    if seconds_remaining > 0:
        tzinfo = datetime.now().astimezone().tzinfo if settings.use_system_timezone else timezone(timedelta(hours=settings.tz))
        tzinfo = tzinfo or timezone.utc
        now_tz = datetime.now(tz=tzinfo)
        eta_dt = now_tz + timedelta(seconds=seconds_remaining)
        eta_display = eta_dt.strftime("%I:%M %p")
        days_ahead = (eta_dt.date() - now_tz.date()).days
        if days_ahead > 0:
            eta_display = f"{eta_display}+{days_ahead}"

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
            goal_tooltip_lines.append(f"Projected total time at current pace: {projected_total_minutes:.0f} minutes.")

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
            tooltip_lines.append(
                "Projected time remaining based on your current pace."
            )
            tooltip_lines.append(
                f"Estimated finish time adjusted for your {'system' if settings.use_system_timezone else 'custom'} timezone: {eta_display}."
            )
            remaining_tooltip_lines.append(
                "Projected time remaining based on your current pace."
            )
            remaining_tooltip_lines.append(
                f"Estimated finish time adjusted for your {'system' if settings.use_system_timezone else 'custom'} timezone: {eta_display}."
            )
        else:
            output += "     |     --:-- more"
            output += "     |     ETA N/A"
            tooltip_lines.append(
                "Projected time remaining is unavailable until at least one card is answered."
            )
            tooltip_lines.append(
                "Estimated finish time unavailable until progress is made."
            )
            remaining_tooltip_lines.append(
                "Projected time remaining is unavailable until at least one card is answered."
            )
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
            tooltip_lines.append(
                "Projected time remaining based on your current pace."
            )
            remaining_tooltip_lines.append(
                "Projected time remaining based on your current pace."
            )
            output += f"     |     ETA {eta_display}"
            tooltip_lines.append(
                f"Estimated finish time adjusted for your {'system' if settings.use_system_timezone else 'custom'} timezone: {eta_display}."
            )
            remaining_tooltip_lines.append(
                f"Estimated finish time adjusted for your {'system' if settings.use_system_timezone else 'custom'} timezone: {eta_display}."
            )
        else:
            output += "     |     --:-- more"
            tooltip_lines.append(
                "Projected time remaining is unavailable until at least one card is answered."
            )
            output += "     |     ETA N/A"
            tooltip_lines.append(
                "Estimated finish time unavailable until progress is made."
            )
            remaining_tooltip_lines.append(
                "Projected time remaining is unavailable until at least one card is answered."
            )
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
    tooltip_lines.append("Left excludes buried cards (shown as +).")
    remaining_tooltip_lines.extend(breakdown_lines)
    remaining_tooltip_lines.append("Left excludes buried cards (shown as +).")

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
            tip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
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
        self._reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
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


class DeckBreakdownDialog(QDialog):
    """Popover showing actionable and buried counts per deck with projected finish times."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Deck Breakdown")
        self.setModal(False)
        self.setMinimumWidth(520)
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
        layout.addWidget(self._tree)

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

    def _add_row(self, row: Dict[str, Any], parent_item: Optional[QTreeWidgetItem] = None) -> QTreeWidgetItem:
        if self._tree is None or self._tree_widget_item_cls is None:
            return None  # type: ignore[return-value]

        item = QTreeWidgetItem(parent_item or self._tree)
        item.setText(0, row.get("name", ""))
        item.setText(1, self._format_counts(row.get("actionable", (0, 0, 0))))
        item.setText(2, self._format_counts(row.get("buried", (0, 0, 0))))
        item.setText(3, row.get("eta", "N/A"))
        item.setTextAlignment(1, int(Qt.AlignmentFlag.AlignVCenter))
        item.setTextAlignment(2, int(Qt.AlignmentFlag.AlignVCenter))
        item.setTextAlignment(3, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight))

        for child in row.get("children", []):
            self._add_row(child, item)
        return item

    def update_rows(self, rows: List[Dict[str, Any]]) -> None:
        if self._tree is None:
            return
        self._tree.clear()
        for row in rows:
            self._add_row(row)
        self._tree.expandToDepth(1)
        if rows:
            self._tree.resizeColumnToContents(0)


class ProgressBarConfigDialog(QDialog):
    """Small settings dialog for the supported configuration surface."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Progress Bar Settings")
        self.setMinimumWidth(420)
        self._config_snapshot = deepcopy(config)
        self._building_ui = True
        self._dirty = False
        self._compact_layout_active = False
        self._build_ui()
        self._populate_from_config(self._config_snapshot)
        self._building_ui = False
        self._update_dirty_state(False)

    def _build_ui(self) -> None:
        palette = _ui_palette()
        field_style = f"""
            QComboBox {{
                padding: 6px 8px;
                border: 1px solid {palette['field_border']};
                border-radius: 5px;
                background: {palette['field_bg']};
                color: {palette['primary_text']};
            }}
        """
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {palette['window_bg']};
                color: {palette['primary_text']};
            }}
            """
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.progress_bar_enabled_cb = QCheckBox("Show progress bar")

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Simple", "simple")
        self.mode_combo.addItem("Time Left", "time_left")
        self.mode_combo.addItem("Stats", "stats")
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

        default_shortcut = "Meta+G" if sys.platform == "darwin" else "Ctrl+G"
        self.shortcut_field = ShortcutField(default_shortcut, palette)

        layout.addWidget(self.progress_bar_enabled_cb)
        layout.addWidget(SettingRow("Mode", "Simple shows counts, Time Left adds ETA, Stats shows the full metric label.", self.mode_combo, palette))
        layout.addWidget(SettingRow("Position", "Place the progress bar above or below the reviewer.", self.dock_area_combo, palette))
        layout.addWidget(SettingRow("Theme", "Auto follows Anki; Light and Dark force the built-in themes.", self.theme_combo, palette))
        layout.addWidget(SettingRow("Shortcut", "Record the key sequence used to show or hide the progress bar.", self.shortcut_field, palette))

        self._dirty_badge = QLabel("")
        self._dirty_badge.setStyleSheet(f"color: {palette['muted_text']}; font-weight: 600;")
        layout.addWidget(self._dirty_badge)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self._apply_btn = QPushButton("Apply")
        self._apply_btn.clicked.connect(self._apply_without_closing)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        self._save_btn = QPushButton("Save")
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self._save_and_close)
        button_row.addWidget(self._apply_btn)
        button_row.addWidget(self._cancel_btn)
        button_row.addWidget(self._save_btn)
        layout.addLayout(button_row)
        self.setLayout(layout)

        for control in (
            self.progress_bar_enabled_cb,
            self.mode_combo,
            self.dock_area_combo,
            self.theme_combo,
            self.shortcut_field,
        ):
            self._watch_control(control)

    def _watch_control(self, control: QWidget) -> None:
        if isinstance(control, QCheckBox):
            control.toggled.connect(self._on_value_changed)
        elif isinstance(control, QComboBox):
            control.currentIndexChanged.connect(self._on_value_changed)
        elif isinstance(control, ShortcutField):
            control.shortcutChanged.connect(self._on_value_changed)

    def _populate_from_config(self, cfg: Dict[str, Any]) -> None:
        self.progress_bar_enabled_cb.setChecked(_coerce_bool(cfg.get("progress_bar_enabled"), True))

        mode = str(cfg.get("mode", "stats")).lower()
        if mode not in {"simple", "time_left", "stats"}:
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
        if sys.platform == "darwin" and shortcut.lower() == "ctrl+g":
            shortcut = "Meta+G"
        self.shortcut_field.set_shortcut(shortcut)

    def _gather_config(self) -> Dict[str, Any]:
        updated_config = deepcopy(config)
        for key in addon_config.LEGACY_WARNING_KEYS:
            updated_config.pop(key, None)
        updated_config["progress_bar_enabled"] = self.progress_bar_enabled_cb.isChecked()
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
        mw.addonManager.writeConfig(addon_config.CONFIG_KEY, updated_config)
        _apply_settings(show_messages=False)
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
    dialog = SessionHistoryDialog(mw)
    dialog.exec()


def _reload_configuration_action() -> None:
    _apply_settings(show_messages=True)
    tooltip("Progress Bar configuration reloaded.", parent=mw, period=2000)


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

settings_action = QAction("Progress Bar Settings", mw)
settings_action.triggered.connect(_open_config_dialog)

progress_ui.update_toggle_shortcut(toggleProgressBar)
tools_menu = getattr(getattr(mw, "form", None), "menuTools", None)
if tools_menu is not None and hasattr(tools_menu, "addAction"):
    tools_menu.addAction(settings_action)
