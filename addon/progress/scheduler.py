"""Scheduler and collection queries used by the progress controller."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


QueueCounts = Tuple[int, int, int]
FilteredAnswers = Dict[int, Tuple[int, int]]  # revlog ID -> (card ID, filtered deck ID)
ANSWER_FILTER = "r.ease between 1 and 4 and r.type in (0, 1, 2, 3)"


def day_boundary_ms(day_cutoff: int, days_ago: int = 0) -> int:
    """Move between local scheduler cutoffs, including 23/25-hour days."""

    if days_ago == 0:
        return int(day_cutoff * 1000)
    cutoff = datetime.fromtimestamp(day_cutoff)
    try:
        return int((cutoff - timedelta(days=days_ago)).timestamp() * 1000)
    except (OverflowError, OSError, ValueError):
        if days_ago > 0:
            # An oversized history lookback includes every possible Anki answer.
            return 0
        raise


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


def add_counts(first: QueueCounts, second: QueueCounts) -> QueueCounts:
    return first[0] + second[0], first[1] + second[1], first[2] + second[2]


def _deck_ids_sql(deck_ids: Iterable[int]) -> str:
    # An integer-only IN list also works on SQLite builds with a 999-bind limit.
    return ",".join(str(int(deck_id)) for deck_id in deck_ids)


def latest_answer_id(db: Any, card_id: int) -> Optional[int]:
    row = db.first(
        f"select r.id from revlog r where r.cid = ? and {ANSWER_FILTER} order by r.id desc limit 1",
        card_id,
    )
    return row[0] if row else None


def _answer_deck_sql(
    deck_ids: List[int], start: int, end: Optional[int], filtered_answers: Optional[FilteredAnswers],
) -> str:
    original_deck = "coalesce(nullif(c.odid, 0), c.did)"
    if not deck_ids or not filtered_answers:
        return original_deck

    selected = set(deck_ids)
    by_deck: Dict[int, List[str]] = {}
    for log_id, (card_id, deck_id) in filtered_answers.items():
        if deck_id in selected and log_id >= start and (end is None or log_id < end):
            by_deck.setdefault(deck_id, []).append(f"({int(log_id)},{int(card_id)})")

    # Match the exact surviving answer, so undo removes it from totals. If the
    # card moves to a different filter, a known answer keeps its original scope.
    if not by_deck:
        return original_deck
    cases = [
        f"when (r.id, r.cid) in (values {','.join(answers)}) then {int(deck_id)}"
        for deck_id, answers in by_deck.items()
    ]
    return f"case {' '.join(cases)} else {original_deck} end"


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
    current_deck_ids: Optional[List[int]] = None,
    filtered_answers: Optional[FilteredAnswers] = None,
) -> Dict[int, Tuple[int, int, int]]:
    range_sql = "r.id >= ?" if end is None else "r.id >= ? and r.id < ?"
    params = [cutoff] if end is None else [cutoff, end]
    if current_deck_ids is None and current_deck is not None:
        current_deck_ids = [current_deck]
    deck_expression = _answer_deck_sql(current_deck_ids or [], cutoff, end, filtered_answers)
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


def buried_counts_by_deck(
    db: Any, sched: Any, deck_ids: List[int], *, day_cutoff: Optional[int] = None,
) -> Dict[int, QueueCounts]:
    """Read due buried cards once per refresh using the deck/queue index."""
    if not deck_ids:
        return {}

    scheduler_day = getattr(sched, "today", None)
    today = int(scheduler_day or 0)
    if day_cutoff is None:
        day_cutoff = int(getattr(sched, "day_cutoff", 0) or 0)
    if scheduler_day is None and day_cutoff > 0:
        today = day_cutoff // 86400
    rows = db.all(
        f"""
        select did,
               sum(case when type = 2 and due <= ? then 1 else 0 end),
               sum(case when type in (1, 3)
                        and (case when due < 1000000000 then due <= ? else due < ? end) then 1 else 0 end),
               sum(case when type = 0 then 1 else 0 end)
        from cards where queue in (-2, -3) and did in ({_deck_ids_sql(deck_ids)})
        group by did
        """,
        today, today, day_cutoff,
    )
    return {int(did): (rev, lrn, new) for did, rev, lrn, new in rows}


def queue_counts_for_node(
    db: Any,
    sched: Any,
    node: Any,
    collect_deck_ids: Callable[[Any], List[int]],
    active_queue_counts: Optional[QueueCounts] = None,
    *,
    buried_counts: Optional[QueueCounts] = None,
) -> Tuple[int, int, int, int, int, int]:
    """Return scheduler-authoritative actionable and separately buried counts."""
    if buried_counts is None:
        buried_counts = (0, 0, 0)
        for counts in buried_counts_by_deck(db, sched, collect_deck_ids(node)).values():
            buried_counts = add_counts(buried_counts, counts)
    return reconcile_queue_counts(
        (getattr(node, "review_count", 0), getattr(node, "learn_count", 0), getattr(node, "new_count", 0)),
        buried_counts,
        active_queue_counts,
    )


def revlog_stats(
    db: Any, start: int, end: int | None, deck_ids: List[int], *, existing_cards_only: bool = False,
    filtered_answers: Optional[FilteredAnswers] = None,
):
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
    if deck_ids or existing_cards_only:
        base += " join cards c on c.id = r.cid"
    if not deck_ids:
        return db.first(base + " where " + range_sql, *params)
    selected = _deck_ids_sql(deck_ids)
    deck_expression = _answer_deck_sql(deck_ids, start, end, filtered_answers)
    query = base + f" where {range_sql} and {deck_expression} in ({selected})"
    return db.first(query, *params)
