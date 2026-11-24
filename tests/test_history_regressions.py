import pytest

from tests.test_progress_bar import SequenceDB, SQLiteDB


@pytest.mark.parametrize("hours_until_next_cutoff", [23, 72])
def test_rollover_finishes_last_active_day_after_throttled_save(addon_module, monkeypatch, hours_until_next_cutoff):
    mod = addon_module
    # A 23-hour local day can leave consecutive cutoffs in the same UTC bucket.
    cutoff = 86400 * 20 + 1800
    mod.mw.col.sched.day_cutoff = cutoff
    db = mod.mw.col.db = SQLiteDB()
    db.execute("create table cards (id integer primary key)")
    db.execute("create table revlog (id integer primary key, cid integer, ease integer, type integer, lastIvl integer, time integer)")
    db.execute("insert into cards values (1)")
    def record(offset, cid, milliseconds):
        db.execute("insert into revlog values (?, ?, 3, 1, 1, ?)", (cutoff * 1000 + offset, cid, milliseconds))

    record(-5, 1, 1000)
    record(-4, 999, 1000)  # A deleted card is outside the live deck collection.
    mod.totalCount[1] = 10
    def unexpected_deck_tree():
        raise AssertionError("A collection-wide history save must not rebuild the deck tree.")
    monkeypatch.setattr(mod.mw.col.sched, "deck_due_tree", unexpected_deck_tree)
    mod._persist_progress_snapshot()
    records = mod.mw.pm.profile[mod.HISTORY_PROGRESS_KEY]
    assert records[0]["cards"] == 1

    record(-1, 1, 3000)
    record(0, 1, 5000)
    mod.totalCount[1] += 1
    class NoTraversal(dict):
        def items(self):
            raise AssertionError("Throttled saves must not walk every deck.")
    with monkeypatch.context() as patch:
        patch.setattr(mod, "totalCount", NoTraversal(mod.totalCount))
        patch.setattr(mod.time, "monotonic", lambda: mod._progress_state.last_persisted_ts + 1)
        mod._persist_progress_snapshot()
    assert records[0]["cards"] == 1

    mod.mw.col.sched.day_cutoff += hours_until_next_cutoff * 3600
    mod._ensure_persisted_progress_loaded()
    record, = mod.mw.pm.profile[mod.HISTORY_PROGRESS_KEY]
    assert (record["cutoff"], record["cards"], record["avg_seconds"]) == (cutoff, 2, 2)
    assert mod.PERSISTED_PROGRESS_KEY not in mod.mw.pm.profile


def test_history_rollover_respects_cleared_or_replaced_profile_data(addon_module):
    mod = addon_module
    mod.mw.col.sched.day_cutoff = 3 * 86400
    db = mod.mw.col.db = SequenceDB(first_rows=[(1, 0, 0, 1, 0, 0, 1)])
    mod._persist_progress_snapshot()
    mod.mw.pm.profile[mod.HISTORY_PROGRESS_KEY] = []
    mod.mw.col.sched.day_cutoff += 86400
    mod._ensure_persisted_progress_loaded()
    assert len(db.first_calls) == 1
    assert mod.mw.pm.profile[mod.HISTORY_PROGRESS_KEY] == []


def test_same_day_saves_skip_renormalizing_retained_history(addon_module, monkeypatch):
    mod = addon_module
    mod.mw.col.sched.day_cutoff = 3 * 86400
    mod.mw.pm.profile[mod.HISTORY_PROGRESS_KEY] = [{"day": "2", "cards": 5}]
    mod.mw.col.db = SequenceDB(first_rows=[(1, 0, 0, 1, 0, 0, 1), (2, 0, 0, 2, 0, 0, 4)])
    mod._persist_progress_snapshot()
    mod._apply_config({"history_days": 1})
    def unexpected_normalization(_profile):
        raise AssertionError("Unchanged prior days should not be normalized on each save.")
    monkeypatch.setattr(mod.history, "read_history_records", unexpected_normalization)
    mod._persist_progress_snapshot(force=True)
    records = mod.mw.pm.profile[mod.HISTORY_PROGRESS_KEY]
    assert len(records) == 1
    assert records[0]["cards"] == 2
    assert records[0]["avg_seconds"] == 2


def test_unrepresentable_historical_samples_do_not_break_valid_pace(addon_module):
    mod = addon_module
    mod.mw.pm.profile[mod.HISTORY_PROGRESS_KEY] = [
        {"day": 9, "cards": 100, "avg_seconds": 1e308},
        {"day": 8, "cards": 1e308, "avg_seconds": 1},
        {"day": 7, "cards": 1, "avg_seconds": 1e-320},
        {"day": 6, "cards": 3, "avg_seconds": 2},
        {"day": 5, "cards": 1, "avg_seconds": 4},
    ]
    assert mod._historical_seconds_per_card(10) == 2.5
