"""Scheduler and collection queries used by the progress controller."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple


def completed_counts_by_deck(db: Any, cutoff: int) -> Dict[int, Tuple[int, int, int]]:
    rows = db.all(
        """
        select coalesce(nullif(c.odid, 0), c.did) as deck_id,
               sum(case when r.type in (1, 3) then 1 else 0 end),
               sum(case when r.type in (0, 2) and not (r.type = 0 and r.lastIvl = 0) then 1 else 0 end),
               sum(case when r.type = 0 and r.lastIvl = 0 then 1 else 0 end)
        from revlog r join cards c on c.id = r.cid
        where r.id > ? group by deck_id
        """,
        cutoff,
    )
    return {
        int(deck_id): (int(rev or 0), int(learning or 0), int(new or 0))
        for deck_id, rev, learning, new in rows
    }


def queue_counts_for_node(
    db: Any, sched: Any, node: Any, collect_deck_ids: Callable[[Any], List[int]]
) -> Tuple[int, int, int, int, int, int]:
    """Return actionable and buried counts while respecting scheduler limits."""

    deck_ids = list(dict.fromkeys(collect_deck_ids(node)))
    sched_rev = int(getattr(node, "review_count", 0) or 0)
    sched_lrn = int(getattr(node, "learn_count", 0) or 0)
    sched_new = int(getattr(node, "new_count", 0) or 0)
    if not deck_ids:
        return sched_rev, sched_lrn, sched_new, 0, 0, 0

    today = int(getattr(sched, "today", 0) or 0)
    day_cutoff = int(getattr(sched, "day_cutoff", 0) or 0)
    if today <= 0 and day_cutoff > 0:
        today = day_cutoff // 86400
    placeholders = ",".join(["?"] * len(deck_ids))
    counts = db.first(
        f"""
        select sum(case when queue = 2 then 1 else 0 end),
               sum(case when queue in (1, 3) then 1 else 0 end),
               sum(case when queue = 0 then 1 else 0 end),
               sum(case when queue in (-2, -3) and type = 2 and due <= ? then 1 else 0 end),
               sum(case when queue in (-2, -3) and type in (1, 3)
                        and due <= case when due < 1000000000 then ? else ? end then 1 else 0 end),
               sum(case when queue in (-2, -3) and type = 0 then 1 else 0 end)
        from cards where queue in (0, 1, 2, 3, -2, -3) and did in ({placeholders})
        """,
        today, today, day_cutoff, *deck_ids,
    ) or (0, 0, 0, 0, 0, 0)
    raw_rev, raw_lrn, raw_new, buried_rev, buried_lrn, buried_new = (
        int(value or 0) for value in counts
    )
    new_limit = max(0, sched_new - min(buried_new, max(0, sched_new - raw_new)))
    return (
        min(raw_rev, sched_rev), min(raw_lrn, sched_lrn), min(raw_new, new_limit),
        buried_rev, buried_lrn, buried_new,
    )


def revlog_stats(db: Any, start: int, end: int | None, deck_ids: List[int]):
    """Aggregate review metrics after ``start`` or in ``[start, end)``."""

    base = """
        select sum(case when r.ease >= 1 then 1 else 0 end),
               sum(case when r.ease = 1 then 1 else 0 end),
               sum(case when r.ease = 1 and r.type = 1 then 1 else 0 end),
               sum(case when r.ease > 1 and r.type = 1 then 1 else 0 end),
               sum(case when r.ease > 1 and r.type = 1 and r.lastIvl >= 100 then 1 else 0 end),
               sum(case when r.ease = 1 and r.type = 1 and r.lastIvl >= 100 then 1 else 0 end),
               sum(r.time)/1000 from revlog r
    """
    range_sql = "r.id > ?" if end is None else "r.id >= ? and r.id < ?"
    params: List[int] = [start] if end is None else [start, end]
    if not deck_ids:
        return db.first(base + " where " + range_sql, *params)
    placeholders = ",".join(["?"] * len(deck_ids))
    query = base + f""" join cards c on c.id = r.cid where {range_sql}
        and (c.did in ({placeholders}) or (c.odid != 0 and c.odid in ({placeholders})))"""
    return db.first(query, *params, *deck_ids, *deck_ids)
