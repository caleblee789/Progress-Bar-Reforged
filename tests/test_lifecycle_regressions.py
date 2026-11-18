from types import SimpleNamespace

from tests.stubs import CollectionStub, DeckNode, ProfileManagerStub


def test_profile_open_preserves_home_refresh_and_isolates_profiles(addon_module, monkeypatch):
    mod = addon_module
    mod._apply_config({"display_location": "review_and_home"})
    history_reads = []

    def historical_weights(db, start, end):
        history_reads.append(db)
        return (1.0, 1.0, 1.0)

    monkeypatch.setattr(mod.progress_scheduler, "historical_weights", historical_weights)
    for deck_id in (12, 27):
        mod.mw.pm = ProfileManagerStub()
        mod.mw.col = CollectionStub()
        mod.mw.col.db = SimpleNamespace(all=lambda *_: [], first=lambda *_: None)
        mod.mw.col.sched.day_cutoff = 86400
        deck = DeckNode(deck_id)
        deck.new_count = 4
        mod.mw.col.sched._deck_tree = DeckNode(0, [deck])
        mod.mw.state = "deckBrowser"

        # loadCollection() opens Home before loadProfile() fires profile_did_open.
        mod.gui_hooks.state_did_change("deckBrowser", "profileManager")
        mod.gui_hooks.profile_did_open()

        assert mod.rawRemainCount == {deck_id: 4}
        mod._open_deck_breakdown_dialog()
        assert [row["deck_id"] for row in mod._deck_breakdown_dialog._raw_rows] == [deck_id]
        assert sum(db is mod.mw.col.db for db in history_reads) == 1
        mod.gui_hooks.profile_will_close()
        assert mod.rawRemainCount == {}


def test_disabled_addon_skips_weight_query_on_startup(addon_module, monkeypatch):
    mod = addon_module
    mod._apply_config({"progress_bar_enabled": False})
    mod.mw.col.db = object()

    def unexpected_query(*args):
        raise AssertionError("disabled progress bar queried review history")

    monkeypatch.setattr(mod.progress_scheduler, "historical_weights", unexpected_query)
    mod.gui_hooks.main_window_did_init()
    mod.gui_hooks.profile_did_open()


def test_sync_invalidates_prior_day_weights_at_next_refresh(addon_module, monkeypatch):
    mod = addon_module
    mod.mw.col.db = object()
    weights = iter([(1.0, 1.0, 1.0), (1.5, 1.0, 1.0)])
    monkeypatch.setattr(mod.progress_scheduler, "historical_weights", lambda *_: next(weights))

    mod.gui_hooks.profile_did_open()
    mod.add_info()
    assert mod.rev_weight == 1.0
    mod.gui_hooks.sync_did_finish()
    assert mod.rev_weight == 1.0
    mod.add_info()
    assert mod.rev_weight == 1.5
