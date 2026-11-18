from tests.stubs import DeckNode
from tests.test_progress_bar import SequenceDB, SQLiteDB


def test_large_deck_tree_batches_burials_and_matches_filtered_subdeck_stats(addon_module):
    mod = addon_module

    class LimitedDB(SQLiteDB):
        def first(self, query, *params):
            # Older SQLite builds allow 999 host parameters per statement.
            assert len(params) <= 999
            return super().first(query, *params)

        def all(self, query, *params):
            assert len(params) <= 999
            return super().all(query, *params)

    db = LimitedDB()
    db.execute("create table cards (id integer primary key, did integer, odid integer, "
               "type integer, queue integer, due integer)")
    db.execute("create index ix_cards_sched on cards(did, queue, due)")
    db.execute("create table revlog (id integer primary key, cid integer, type integer, "
               "lastIvl integer, ease integer, time integer)")
    for row in (
        (1, 1001, 9000, 2, -2, 0),  # In a filtered subdeck of the selected parent.
        (2, 9000, 2, 0, 0, 0),     # Originally from a subdeck of the selected parent.
        (3, 3, 0, 3, -3, 0),
        (4, 9000, 0, 2, -2, 0),
    ):
        db.execute("insert into cards values (?, ?, ?, ?, ?, ?)", row)
    for row in (
        (1001, 1, 1, 10, 3, 250),
        (1002, 2, 0, 0, 3, 500),
        (1003, 99999, 1, 10, 3, 750),  # Orphan log, excluded from deck records.
    ):
        db.execute("insert into revlog values (?, ?, ?, ?, ?, ?)", row)
    selected_ids = list(range(1, 1002))
    parent = DeckNode(1, [DeckNode(did) for did in selected_ids[1:]])
    mod.mw.col.db = db
    mod.mw.col.sched._deck_tree = DeckNode(0, [parent, DeckNode(9000)])
    mod.mw.col.sched.day_cutoff = 86400
    mod.mw.col.sched.today = 0
    statements = []
    db.connection.set_trace_callback(statements.append)
    mod.currDID = 1
    mod.updateCountsForAllDecks(True)

    assert sum("where queue in" in sql.lower() for sql in statements) == 1
    assert mod.buriedRevCount[1] == mod.buriedLrnCount[1] == 1
    assert mod.buriedRevCount[1001] == mod.buriedLrnCount[3] == 1
    assert mod.rawDoneCount[1] == mod._revlog_stats_since(0, selected_ids)[0] == 2
    assert mod.rawDoneCount[2] == mod.rawDoneCount[1001] == 1
    assert mod.rawDoneCount[9000] == 0

    mod.currDID = None
    mod.updateCountsForAllDecks(True)
    assert mod.rawDoneCount[1] == mod.rawDoneCount[9000] == 1
    assert mod.progress_scheduler.revlog_stats(db, 0, None, [], existing_cards_only=True)[0] == 2
    assert mod.progress_scheduler.revlog_stats(db, 0, None, [])[0] == 3


def test_unrepresentable_lookback_includes_all_review_history(addon_module):
    assert addon_module.progress_scheduler.day_boundary_ms(1795000000, 10**30) == 0


def test_question_uses_a_single_cutoff_for_counts_stats_and_history(addon_module):
    mod = addon_module
    cutoff = 10 * 86400

    class Scheduler:
        cutoff_reads = today_reads = 0

        @property
        def day_cutoff(self):
            self.cutoff_reads += 1
            return cutoff

        @property
        def today(self):
            self.today_reads += 1
            return 3

        def deck_due_tree(self):
            deck = DeckNode(1)
            deck.review_count = 1
            return DeckNode(0, [deck])

    mod.mw.col.sched = sched = Scheduler()
    mod.mw.col.db = db = SequenceDB(first_rows=[(2, 0, 0, 2, 0, 0, 10)] * 3)
    mod.initPB()

    mod.showQuestionCallBack()
    assert (sched.cutoff_reads, sched.today_reads) == (1, 1)
    assert mod._progress_state.last_history_cutoff == cutoff
    assert mod._progress_state.restored_day_stamp == cutoff // 86400
    assert mod._progress_state.weight_history_key[1] == cutoff
    assert mod.mw.pm.profile[mod.PERSISTED_PROGRESS_KEY]["day"] == cutoff // 86400
    assert any(params == (3, 3, cutoff) for _, params in db.all_calls)

    # Repeated questions also share the cutoff during throttled profile saves.
    mod.showQuestionCallBack()
    assert (sched.cutoff_reads, sched.today_reads) == (2, 2)
