from unittest.mock import Mock

import pytest

from tests.stubs import DeckNode, Qt
from tests.test_progress_bar import SequenceDB


@pytest.mark.parametrize("mode, yesterday_queries", [("simple", 0), ("time_left", 0), ("stats", 1)])
def test_question_uses_one_scheduler_tree_and_only_visible_comparisons(
    addon_module, mode, yesterday_queries
):
    mod = addon_module
    mod._apply_config({"mode": mode})
    sched = mod.mw.col.sched
    sched.day_cutoff = 10 * 86400
    sched.deck_due_tree = Mock(return_value=DeckNode(0, [DeckNode(1)]))
    mod.mw.col.db = db = SequenceDB()
    mod.initPB()

    mod.showQuestionCallBack()

    sched.deck_due_tree.assert_called_once_with()
    yesterday = mod.progress_scheduler.day_boundary_ms(sched.day_cutoff, 2)
    assert sum(params[0] == yesterday for query, params in db.first_calls) == yesterday_queries


def test_closed_breakdown_skips_rendering_and_reopens_with_latest_counts(addon_module, monkeypatch):
    mod = addon_module
    mod.mw.col.db = SequenceDB()
    deck = DeckNode(1)
    deck.review_count = 6
    child = DeckNode(2)
    child.review_count = 1
    deck.children.append(child)
    mod.mw.col.sched._deck_tree = DeckNode(0, [deck])
    mod.initPB()
    build_row = Mock(wraps=mod._deck_breakdown_for_node)
    monkeypatch.setattr(mod, "_deck_breakdown_for_node", build_row)
    mod.showQuestionCallBack()
    build_row.assert_not_called()

    mod._open_deck_breakdown_dialog()
    dialog = mod._deck_breakdown_dialog
    assert dialog._summary["actionable"] == (0, 0, 6)
    dialog.hide()
    build_row.reset_mock()
    deck.review_count = 3
    mod.showQuestionCallBack()
    build_row.assert_not_called()

    mod._open_deck_breakdown_dialog()
    assert dialog._summary["actionable"] == (0, 0, 3)
    tree = dialog._tree
    parent_item = tree._items[0]
    parent_item.setExpanded(False)
    tree.setCurrentItem(parent_item, 1)
    deck.review_count = 2
    mod.showQuestionCallBack()
    assert dialog._summary["actionable"] == (0, 0, 2)
    parent_item = tree._items[0]
    assert tree.currentItem() is parent_item
    assert not parent_item.isExpanded()
    assert parent_item.data(1, Qt.ItemDataRole.AccessibleTextRole) == "Due today: 2; New 0, Learning 0, Review 2"

    mod.afterStateChangeCallBack("deckBrowser", "review")
    assert not dialog.isVisible()
