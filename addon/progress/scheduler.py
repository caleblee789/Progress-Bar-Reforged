"""Scheduler and collection queries used by the progress controller."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple


QueueCounts = Tuple[int, int, int]
ANSWER_FILTER = "r.ease between 1 and 4 and r.type in (0, 1, 2, 3)"


def day_boundary_ms(day_cutoff: int, days_ago: int = 0) -> int:
    """Move between local scheduler cutoffs, including 23/25-hour days."""

    cutoff = datetime.fromtimestamp(day_cutoff)
    return int((cutoff - timedelta(days=days_ago)).timestamp() * 1000)


def historical_weights(db: Any, start: int, end: int) -> Tuple[float, float, float]:
    """Again-rate weights in review/learning/new order; no future steps assumed."""

    rows = db.all(
        f"""
        select case when r.type in (1, 3) then 0
                    when r.type = 0 and r.lastIvl = 0 then 2
                    else 1 end as category,
               count(*), sum(case when r.ease = 1 then 1 else 0 end)
        from revlog r
        where r.id >= ? and r.id < ? and {ANSWER_FILTER}
        group by category
        """,
        start, end,
    )
    weights = [1.0, 1.0, 1.0]
    for category, answers, again in rows:
        if answers:
            weights[int(category)] = 1.0 + min(1.0, max(0.0, again / answers))
    return tuple(weights)


def _normalized_counts(counts: Tuple[Any, Any, Any]) -> QueueCounts:
    return tuple(max(0, int(value or 0)) for value in counts)  # type: ignore[return-value]


def queued_cards_counts(queued_cards: Any) -> Optional[QueueCounts]:
    """Return reviewer queue counts in review/learning/new order when available."""

    if queued_cards is None:
        return None
    try:
        return _normalized_counts(
            (
                queued_cards.review_count,
                queued_cards.learning_count,
                queued_cards.new_count,
            )
        )
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def reconcile_queue_counts(
    deck_tree_counts: QueueCounts,
    buried_counts: QueueCounts,
    active_queue_counts: Optional[QueueCounts] = None,
) -> Tuple[int, int, int, int, int, int]:
    """Prefer Anki's built queue and surface siblings omitted from that queue.

    The deck due tree applies daily limits, but it is populated before the queue
    builder anticipates sibling burying.  ``QueuedCards`` is what Anki's own
    reviewer counter displays.  Any category difference is work the queue
    builder has hidden because of sibling-bury settings; add it to the already
    buried database count instead of presenting it as work the user will see.
    """

    tree_rev, tree_lrn, tree_new = _normalized_counts(deck_tree_counts)
    buried_rev, buried_lrn, buried_new = _normalized_counts(buried_counts)
    if active_queue_counts is None:
        return (
            tree_rev,
            tree_lrn,
            tree_new,
            buried_rev,
            buried_lrn,
            buried_new,
        )

    queue_rev, queue_lrn, queue_new = _normalized_counts(active_queue_counts)
    return (
        queue_rev,
        queue_lrn,
        queue_new,
        buried_rev + max(0, tree_rev - queue_rev),
        buried_lrn + max(0, tree_lrn - queue_lrn),
        buried_new + max(0, tree_new - queue_new),
    )


def completed_counts_by_deck(
    db: Any, cutoff: int, end: Optional[int] = None,
    *, current_deck: Optional[int] = None,
) -> Dict[int, Tuple[int, int, int]]:
    range_sql = "r.id >= ?" if end is None else "r.id >= ? and r.id < ?"
    params = [cutoff] if end is None else [cutoff, end]
    deck_expression = "coalesce(nullif(c.odid, 0), c.did)"
    if current_deck is not None:
        # In a selected filtered deck, match the cards used by its time and
        # retention queries. Keep one attribution per answer for home totals.
        deck_expression = f"case when c.did = ? then c.did else {deck_expression} end"
        params.insert(0, current_deck)
    rows = db.all(
        f"""
        select {deck_expression} as deck_id,
               sum(case when r.type in (1, 3) then 1 else 0 end),
               sum(case when r.type in (0, 2) and not (r.type = 0 and r.lastIvl = 0) then 1 else 0 end),
               sum(case when r.type = 0 and r.lastIvl = 0 then 1 else 0 end)
        from revlog r join cards c on c.id = r.cid
        where {range_sql} and {ANSWER_FILTER} group by deck_id
        """,
        *params,
    )
    return {
        int(deck_id): (int(rev or 0), int(learning or 0), int(new or 0))
        for deck_id, rev, learning, new in rows
    }


def queue_counts_for_node(
    db: Any,
    sched: Any,
    node: Any,
    collect_deck_ids: Callable[[Any], List[int]],
    active_queue_counts: Optional[QueueCounts] = None,
) -> Tuple[int, int, int, int, int, int]:
    """Return scheduler-authoritative actionable and separately buried counts."""

    deck_ids = list(dict.fromkeys(collect_deck_ids(node)))
    sched_rev = int(getattr(node, "review_count", 0) or 0)
    sched_lrn = int(getattr(node, "learn_count", 0) or 0)
    sched_new = int(getattr(node, "new_count", 0) or 0)
    if not deck_ids:
        return reconcile_queue_counts(
            (sched_rev, sched_lrn, sched_new), (0, 0, 0), active_queue_counts
        )

    scheduler_day = getattr(sched, "today", None)
    today = int(scheduler_day or 0)
    day_cutoff = int(getattr(sched, "day_cutoff", 0) or 0)
    if scheduler_day is None and day_cutoff > 0:
        today = day_cutoff // 86400
    placeholders = ",".join(["?"] * len(deck_ids))
    counts = db.first(
        f"""
        select sum(case when queue in (-2, -3) and type = 2 and due <= ? then 1 else 0 end),
               sum(case when queue in (-2, -3) and type in (1, 3)
                        and (case when due < 1000000000 then due <= ? else due < ? end) then 1 else 0 end),
               sum(case when queue in (-2, -3) and type = 0 then 1 else 0 end)
        from cards where queue in (-2, -3) and did in ({placeholders})
        """,
        today, today, day_cutoff, *deck_ids,
    ) or (0, 0, 0)
    buried_rev, buried_lrn, buried_new = _normalized_counts(counts)
    return reconcile_queue_counts(
        (sched_rev, sched_lrn, sched_new),
        (buried_rev, buried_lrn, buried_new),
        active_queue_counts,
    )


def revlog_stats(db: Any, start: int, end: int | None, deck_ids: List[int]):
    """Aggregate actual answers in ``[start, end)`` with fractional seconds."""

    base = """
        select sum(case when r.ease >= 1 then 1 else 0 end),
               sum(case when r.ease = 1 then 1 else 0 end),
               sum(case when r.ease = 1 and r.type = 1 then 1 else 0 end),
               sum(case when r.ease > 1 and r.type = 1 then 1 else 0 end),
               sum(case when r.ease > 1 and r.type = 1 and r.lastIvl >= 100 then 1 else 0 end),
               sum(case when r.ease = 1 and r.type = 1 and r.lastIvl >= 100 then 1 else 0 end),
               sum(max(r.time, 0))/1000.0 from revlog r
    """
    range_sql = "r.id >= ?" if end is None else "r.id >= ? and r.id < ?"
    range_sql += " and " + ANSWER_FILTER
    params: List[int] = [start] if end is None else [start, end]
    if not deck_ids:
        return db.first(base + " where " + range_sql, *params)
    placeholders = ",".join(["?"] * len(deck_ids))
    query = base + f""" join cards c on c.id = r.cid where {range_sql}
        and (c.did in ({placeholders}) or (c.odid != 0 and c.odid in ({placeholders})))"""
    return db.first(query, *params, *deck_ids, *deck_ids)
