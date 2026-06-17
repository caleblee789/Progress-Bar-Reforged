from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, List, Sequence, Tuple


from tests.stubs import DeckNode, QFileDialog, QPainter, QPalette, QRect


class SequenceDB:
    def __init__(self, all_rows: Sequence[Tuple[Any, ...]] = (), first_rows: List[Any] | None = None) -> None:
        self.all_rows = list(all_rows)
        self.first_rows = list(first_rows or [])
        self.first_calls: List[Tuple[str, Tuple[Any, ...]]] = []
        self.all_calls: List[Tuple[str, Tuple[Any, ...]]] = []

    def all(self, query: str, *params: Any):
        self.all_calls.append((query, params))
        return list(self.all_rows)

    def first(self, query: str, *params: Any):
        self.first_calls.append((query, params))
        if self.first_rows:
            return self.first_rows.pop(0)
        return None


def test_config_coercion_and_normalization(addon_module):
    mod = addon_module

    assert mod._coerce_bool("true", False) is True
    assert mod._coerce_bool("0", True) is False
    assert mod._coerce_bool(None, True) is True

    assert mod._coerce_int("5", 1) == 5
    assert mod._coerce_int("oops", 3) == 3
    assert mod._coerce_float("1.5", 0.1) == 1.5
    assert mod._coerce_float("bad", 2.5) == 2.5

    assert mod._normalize_dimension(10) == "10px"
    assert mod._normalize_dimension(-2) == ""
    assert mod._normalize_dimension("25%") == "25%"

    mod._apply_config({"progress_bar_enabled": "false", "max_width": 12, "time_warning_minutes": "30", "use_system_timezone": "false", "tz": -3})
    assert mod.progress_bar_enabled is False
    assert mod.maxWidth == "12px"
    assert mod.time_warning_minutes == 30
    assert mod.settings.use_system_timezone is False
    assert mod.settings.tz == -3
    assert mod.warnings_enabled is False


def test_config_reload_populates_global_settings(mw):
    from addon import config as addon_config

    addon_config.apply_config(mw, {"progress_bar_enabled": True, "toggle_shortcut": "Ctrl+Shift+P"})

    assert addon_config.settings.progress_bar_enabled is True
    assert addon_config.settings.toggle_shortcut == "Ctrl+Shift+P"


def test_warning_colors_fall_back_to_theme(mw):
    from addon import config as addon_config

    addon_config.apply_config(
        mw,
        {
            "appearance": {
                "day": {"text": "#111111", "background": "#eeeeee", "foreground": "#123456", "border_radius": 0},
                "night": {"text": "#ffffff", "background": "#222222", "foreground": "#abcdef", "border_radius": 0},
            },
            "warning_colors": {"text": "", "background": "", "foreground": ""},
        },
    )

    settings = addon_config.settings
    expected_text = addon_config._to_qcolor(settings.active_theme.text).name()
    expected_background = addon_config._to_qcolor(settings.active_theme.background).name()
    expected_foreground = addon_config._to_qcolor(settings.active_theme.foreground).name()

    assert settings.warning_colors.text.name() == expected_text
    assert settings.warning_colors.background.name() == expected_background
    assert settings.warning_colors.foreground.name() == expected_foreground


def test_done_counts_by_deck_since_handles_missing_values(addon_module):
    mod = addon_module
    mod.mw.col.db = SequenceDB(
        all_rows=[
            (1, 5, None, 2),
            (2, 0, 3, 4),
        ]
    )

    result = mod._done_counts_by_deck_since(0)

    assert result == {1: (5, 0, 2), 2: (0, 3, 4)}


def test_queue_counts_for_node_caps_and_excludes_buried(addon_module):
    mod = addon_module
    mod.mw.col.db = SequenceDB(first_rows=[(10, 5, 2, 1, 2, 6)])

    child = DeckNode(2)
    node = DeckNode(1, [child])
    node.review_count = 5
    node.learn_count = 3
    node.new_count = 4

    counts = mod._queue_counts_for_node(node)

    assert counts == (5, 3, 2, 1, 2, 6)


def test_warning_palette_applied_when_thresholds_crossed(addon_module):
    mod = addon_module
    mod._apply_config({"warnings_enabled": True})
    mod.mw.col.db = SequenceDB(
        first_rows=[
            (10, 3, 3, 3, 1, 1, 30),  # today
            (0, 0, 0, 0, 0, 0, 0),  # yesterday
        ]
    )

    root = DeckNode(0, [DeckNode(1)])
    mod.mw.col.sched._deck_tree = root
    mod.mw.col.sched.day_cutoff = 1000

    mod.doneCount.clear()
    mod.remainCount.clear()
    mod.totalCount.clear()
    mod.rawDoneCount.clear()
    mod.rawRemainCount.clear()
    mod.rawTotalCount.clear()
    mod.actionableRevCount.clear()
    mod.actionableLrnCount.clear()
    mod.actionableNewCount.clear()
    mod.buriedRevCount.clear()
    mod.buriedLrnCount.clear()
    mod.buriedNewCount.clear()

    mod.doneCount[1] = 2.0
    mod.remainCount[1] = 8.0
    mod.rawDoneCount[1] = 2
    mod.rawRemainCount[1] = 8
    mod.actionableNewCount[1] = 4
    mod.actionableLrnCount[1] = 3
    mod.actionableRevCount[1] = 3
    mod.buriedNewCount[1] = 1
    mod.buriedLrnCount[1] = 0
    mod.buriedRevCount[1] = 0

    mod.initPB()
    mod.updatePB()

    assert mod._warning_active is True
    palette_names = {role: color.name() for role, color in mod.progressBar.palette().colors.items()}
    warning_names = {role: color.name() for role, color in mod.warning_palette.colors.items()}
    assert palette_names == warning_names
    assert "⚠" in mod.progressBar.format()


def test_warnings_can_be_disabled(addon_module):
    mod = addon_module
    mod._apply_config({"warnings_enabled": False, "time_warning_minutes": 1, "again_warning_percent": 1, "retention_warning_percent": 100})
    mod.mw.col.db = SequenceDB(
        first_rows=[
            (10, 3, 3, 3, 1, 1, 30),  # today
            (0, 0, 0, 0, 0, 0, 0),  # yesterday
        ]
    )

    root = DeckNode(0, [DeckNode(1)])
    mod.mw.col.sched._deck_tree = root
    mod.mw.col.sched.day_cutoff = 1000

    mod.doneCount[1] = 2.0
    mod.remainCount[1] = 8.0
    mod.rawDoneCount[1] = 2
    mod.rawRemainCount[1] = 8
    mod.actionableNewCount[1] = 4
    mod.actionableLrnCount[1] = 3
    mod.actionableRevCount[1] = 3
    mod.buriedNewCount[1] = 1
    mod.buriedLrnCount[1] = 0
    mod.buriedRevCount[1] = 0

    mod.initPB()
    mod.updatePB()

    assert mod._warning_active is False
    assert "⚠" not in mod.progressBar.format()


def test_history_export_writes_expected_rows(tmp_path: Path, addon_module):
    mod = addon_module
    history_entry = {
        "day": 1,
        "cards": 5,
        "avg_seconds": 1.234,
        "again": 10.5,
        "retention": 80.0,
        "super_mature_retention": 50.0,
    }
    mod.mw.pm.profile = {mod.HISTORY_PROGRESS_KEY: [history_entry]}

    dialog = mod.SessionHistoryDialog(mod.mw)
    output_path = tmp_path / "history.csv"
    QFileDialog.next_path = str(output_path)

    dialog._export_csv()

    with output_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert rows[0] == [
        "day",
        "cards",
        "avg_seconds",
        "again_percent",
        "retention_percent",
        "super_mature_retention",
        "warning_events",
    ]
    assert rows[1] == ["1970-01-02", "5", "1.23", "10.50", "80.00", "50.00", "0"]


def test_history_loader_tolerates_malformed_metric_values(addon_module):
    mod = addon_module
    profile = {
        mod.HISTORY_PROGRESS_KEY: [
            {
                "day": 2,
                "cards": "not-a-number",
                "avg_seconds": "bad",
                "again": None,
                "retention": "91.5",
                "super_mature_retention": object(),
                "warning_events": "oops",
            },
            {"day": "invalid", "cards": 10},
        ]
    }

    rows = mod.history.read_history_records(profile)

    assert len(rows) == 1
    assert rows[0]["day"] == 2
    assert rows[0]["cards"] == 0
    assert rows[0]["avg_seconds"] == 0.0
    assert rows[0]["retention"] == 91.5
    assert rows[0]["warning_events"] == 0


def test_history_charts_publish_keyboard_readable_summary(addon_module):
    mod = addon_module
    mod.mw.pm.profile = {
        mod.HISTORY_PROGRESS_KEY: [
            {"day": 2, "cards": 20, "avg_seconds": 3, "again": 5, "retention": 95, "warning_events": 1},
            {"day": 1, "cards": 10, "avg_seconds": 4, "again": 10, "retention": 90, "warning_events": 0},
        ]
    }

    dialog = mod.SessionHistoryDialog(mod.mw)

    assert "2 days visible" in dialog.chart_summary_label.text()
    assert "average 15.0 cards/day" in dialog.chart_summary_label.text()
    assert "Cards per day: 2 points" in dialog.cards_chart._accessible_description
    assert dialog.chart_summary_label._focus_policy is not None


def test_segmented_progress_bar_paints_remaining_segments():
    from addon.ui import progress_bar as progress_ui

    palette = QPalette()
    bar = progress_ui.SegmentedProgressBar(
        {"new": progress_ui.QColor("#111"), "learning": progress_ui.QColor("#222"), "review": progress_ui.QColor("#333")}
    )
    bar.setSegmentData(3, 2, 1, 0.25)

    painter = QPainter()
    bar._draw_segments_horizontal(painter, QRect(0, 0, 100, 10), palette)

    assert len(painter.filled) >= 3
    assert any(fill[1].name() == "#111" for fill in painter.filled)



def test_progress_bar_style_name_matching_is_case_insensitive(mw, monkeypatch):
    from addon import config as addon_config

    class DummyStyle:
        pass

    def fake_create(name: str):
        return DummyStyle() if name == "Fusion" else None

    monkeypatch.setattr(addon_config.QStyleFactory, "create", staticmethod(fake_create))
    monkeypatch.setattr(addon_config.QStyleFactory, "keys", staticmethod(lambda: ["Fusion"]), raising=False)

    addon_config.apply_config(mw, {"progress_bar_style": "fusion"})

    assert isinstance(addon_config.settings.progress_bar_qstyle, DummyStyle)


def test_deck_breakdown_uses_two_row_controls_and_sorts_next_day_etas(addon_module):
    mod = addon_module
    dialog = mod.DeckBreakdownDialog(mod.mw)

    assert dialog._controls_layout_mode == "two_row"
    assert dialog._eta_sort_key("11:30 PM") < dialog._eta_sort_key("12:05 AM+1")
    assert dialog._eta_sort_key("12:05 AM+1") < dialog._eta_sort_key("N/A")


def test_settings_dialog_has_compact_section_selector(addon_module):
    mod = addon_module

    dialog = mod.ProgressBarConfigDialog(mod.mw)
    dialog._apply_compact_mode(600)

    assert dialog._minimum_width == 560
    assert dialog._compact_layout_active is True
    assert dialog._section_selector.isVisible() is True
    assert dialog._nav_frame.isVisible() is False

    dialog._nav_list.setCurrentItem(dialog._nav_list.item(2))
    assert dialog._section_selector.currentIndex() == 2

    dialog._apply_compact_mode(840)

    assert dialog._compact_layout_active is False
    assert dialog._section_selector.isVisible() is False
    assert dialog._nav_frame.isVisible() is True


def test_legacy_ctrl_shortcut_is_normalized_on_macos(mw, monkeypatch):
    from addon import config as addon_config

    monkeypatch.setattr(addon_config.sys, "platform", "darwin")

    addon_config.apply_config(mw, {"toggle_shortcut": "Ctrl+G"})

    assert addon_config.settings.toggle_shortcut == "Meta+G"
    assert addon_config.settings.raw_config["toggle_shortcut"] == "Meta+G"


def test_apply_bar_style_to_preserves_stylesheet_with_qstyle():
    from addon.ui import progress_bar as progress_ui

    class DummyStyle:
        pass

    palette = QPalette()
    bar = progress_ui.QProgressBar()
    stylesheet = "QProgressBar { max-width: 120px; color: #fff; }"

    progress_ui.apply_bar_style_to(bar, palette, stylesheet, DummyStyle())

    assert bar.styleSheet() == stylesheet
    assert bar.palette() == palette


def test_segmented_progress_bar_assigns_all_remaining_width():
    from addon.ui import progress_bar as progress_ui

    palette = QPalette()
    bar = progress_ui.SegmentedProgressBar(
        {"new": progress_ui.QColor("#111"), "learning": progress_ui.QColor("#222"), "review": progress_ui.QColor("#333")}
    )
    bar.setSegmentData(1, 1, 1, 0.3)

    painter = QPainter()
    bar._draw_segments_horizontal(painter, QRect(0, 0, 10, 10), palette)

    # First two fills are base + completed chunk.
    segment_fills = painter.filled[2:]
    assert len(segment_fills) == 3
    assert sum(fill[0].width() for fill in segment_fills) == 7

def test_smoke_progress_bar_initialization(addon_module):
    mod = addon_module
    mod.mw.col.db = SequenceDB(first_rows=[None, None])
    mod.mw.col.sched._deck_tree = DeckNode(0, [])

    mod.initPB()
    mod.updatePB()

    assert mod.progressBar is not None
    parent = mod.progressBar.parentWidget()
    assert parent is None or parent.objectName() == "pbDock"
    assert mod.progressBar._event_filters, "Tooltip filter should be installed"

def test_first_run_detection_handles_missing_config(addon_module):
    mod = addon_module
    assert mod.should_run_quick_setup({}) is True
    assert mod.should_run_quick_setup({"quick_setup_enabled": False}) is False
    assert mod.should_run_quick_setup({"onboarding_completed": True, "quick_setup_enabled": True}) is False


def test_new_config_persistence_round_trip(mw):
    from addon import config as addon_config

    addon_config.apply_config(
        mw,
        {
            "quick_setup_enabled": True,
            "focus_mode": True,
            "responsive_breakpoints": False,
            "animated_updates": False,
            "pinned_deck_views": ["1", "2"],
        },
    )

    cfg = addon_config.settings.raw_config
    assert cfg["focus_mode"] is True
    assert cfg["responsive_breakpoints"] is False
    assert cfg["animated_updates"] is False
    assert cfg["pinned_deck_views"] == ["1", "2"]


def test_responsive_breakpoints_helper(addon_module):
    mod = addon_module
    assert mod._is_compact_layout(500, True) is True
    assert mod._is_compact_layout(900, True) is False
    assert mod._is_compact_layout(500, False) is False


def test_animation_toggle_interpolation(addon_module):
    mod = addon_module
    assert mod._interpolate_progress_value(100, 200, False) == 200
    animated = mod._interpolate_progress_value(100, 200, True)
    assert 100 < animated < 200


def test_warning_transition_animation_config_controls_stylesheet(mw):
    from addon import config as addon_config

    addon_config.apply_config(mw, {"warning_transition_animations": True, "reduced_motion": False})
    assert "transition:" in addon_config.settings.warning_stylesheet

    addon_config.apply_config(mw, {"warning_transition_animations": False, "reduced_motion": False})
    assert "transition:" not in addon_config.settings.warning_stylesheet


def test_deck_breakdown_filter_preserves_parent_for_matching_child(addon_module):
    mod = addon_module
    dialog = mod.DeckBreakdownDialog.__new__(mod.DeckBreakdownDialog)

    rows = [
        {
            "name": "Parent",
            "deck_id": 1,
            "actionable": (0, 0, 0),
            "buried": (0, 0, 0),
            "eta": "N/A",
            "children": [
                {
                    "name": "Child Review",
                    "deck_id": 2,
                    "actionable": (0, 0, 3),
                    "buried": (0, 0, 0),
                    "eta": "1:00PM",
                    "children": [],
                }
            ],
        }
    ]

    filtered = dialog._filter_and_sort_rows(rows, "review", "remaining", "")

    assert len(filtered) == 1
    assert filtered[0]["name"] == "Parent"
    assert len(filtered[0]["children"]) == 1
    assert filtered[0]["children"][0]["name"] == "Child Review"


def test_deck_breakdown_eta_sort_treats_na_as_last(addon_module):
    mod = addon_module
    dialog = mod.DeckBreakdownDialog.__new__(mod.DeckBreakdownDialog)

    rows = [
        {"name": "No ETA", "deck_id": 1, "actionable": (1, 0, 0), "buried": (0, 0, 0), "eta": "N/A", "children": []},
        {"name": "Soon", "deck_id": 2, "actionable": (1, 0, 0), "buried": (0, 0, 0), "eta": "9:30AM", "children": []},
        {"name": "Later", "deck_id": 3, "actionable": (1, 0, 0), "buried": (0, 0, 0), "eta": "10:15AM", "children": []},
    ]

    filtered = dialog._filter_and_sort_rows(rows, "all", "eta", "")

    assert [row["name"] for row in filtered] == ["Soon", "Later", "No ETA"]


def test_match_filter_uses_deck_id_not_name_for_pinned(addon_module):
    mod = addon_module
    dialog = mod.DeckBreakdownDialog.__new__(mod.DeckBreakdownDialog)

    row = {"name": "Shared Name", "deck_id": 22, "actionable": (0, 1, 0)}

    assert dialog._match_filter(row, "pinned", {"22"}) is True
    assert dialog._match_filter(row, "pinned", {"33"}) is False


def test_text_hierarchy_config_defaults_and_validation(mw):
    from addon import config as addon_config

    addon_config.apply_config(
        mw,
        {
            "text_hierarchy_style": "invalid",
            "compact_separators": False,
            "vertical_text_line_break": True,
        },
    )

    settings = addon_config.settings
    assert settings.text_hierarchy_style == "compact"
    assert settings.compact_separators is False
    assert settings.vertical_text_line_break is True


def test_hierarchical_text_formatter_supports_two_line(addon_module):
    mod = addon_module

    rendered = mod._format_hierarchical_progress_text(
        ["45/100 (45%)", "ETA 7:30 PM"],
        ["12 Again", "92% TR"],
        hierarchy_style="two_line",
        compact_separators=True,
        vertical=False,
        vertical_line_break=False,
    )

    assert "\n" in rendered
    assert "ETA 7:30 PM" in rendered


def test_settings_dialog_constructs(addon_module):
    mod = addon_module

    dialog = mod.ProgressBarConfigDialog(mod.mw)

    assert dialog.shortcut_field.value()
    assert dialog.counting_basis_combo.currentData() == "answered"
    assert dialog.count_scope_combo.currentData() == "per_deck"


def test_counting_basis_seen_advances_on_question_display(addon_module):
    mod = addon_module
    mod._apply_config({"counting_basis": "seen"})
    mod.totalCount[10] = 5.0
    mod.rawTotalCount[10] = 5

    mod.updateCountsForDeck(10, remain=4.0, raw_remain=4, rev_done=0, lrn_done=0, new_done=0, weighted_done=0.0, updateTotal=False)

    assert mod.doneCount[10] == 1.0
    assert mod.rawDoneCount[10] == 1
    assert mod.totalCount[10] == 5.0


def test_count_scope_global_uses_all_root_decks(addon_module):
    mod = addon_module
    root = DeckNode(0, [DeckNode(1), DeckNode(2)])
    mod.currDID = 1

    mod._apply_config({"count_scope": "per_deck"})
    assert [node.deck_id for node in mod._target_nodes_for_progress(root)] == [1]

    mod._apply_config({"count_scope": "global"})
    assert [node.deck_id for node in mod._target_nodes_for_progress(root)] == [1, 2]


def test_expected_seconds_used_when_no_pace_samples(addon_module):
    mod = addon_module
    mod._apply_config({"deck_profiles": {"1": {"expected_seconds": 12}}})
    mod.rawRemainCount[1] = 5

    assert mod._expected_seconds_for_decks([1]) == 60


def test_profile_close_persistence_tolerates_missing_deck_tree(addon_module):
    mod = addon_module
    mod.totalCount[1] = 1.0
    mod.rawTotalCount[1] = 1

    def broken_tree():
        raise RuntimeError("scheduler closed")

    mod.mw.col.sched.deck_due_tree = broken_tree

    mod._on_profile_will_close()

    assert mod.mw.pm.profile[mod.PERSISTED_PROGRESS_KEY]["data"]["1"]["raw_total"] == 1
