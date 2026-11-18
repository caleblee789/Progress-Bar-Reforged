import pytest

from tests.stubs import QDialog, QEvent


def test_waiting_bar_survives_layout_events(addon_module):
    mod = addon_module
    mod.initPB()
    bar = mod.progressBar
    bar._progress_label_variants = ("Previous counts", "Compact", "Minimal")
    mod.setScrollingPB()
    for kind in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.FontChange):
        mod.progress_ui.interaction_filter.eventFilter(bar, QEvent(kind))
    assert bar.format() == "Waiting..."
    assert "Waiting" in bar._accessible_description


def test_repeated_segment_data_skips_redraw(addon_module):
    bar = addon_module.progress_ui.SegmentedProgressBar({})
    bar.setSegmentData(3, 2, 1, 0.25)
    bar.setSegmentData(3, 2, 1, 0.25)
    assert bar._update_calls == 1
    bar.setSegmentData(3, 2, 0, 0.25)
    bar.setSegmentData(3, 2, 0, 0.5)
    assert bar._update_calls == 3


def test_side_bar_uses_only_native_dock_registration(addon_module, monkeypatch):
    mod = addon_module
    registered = mod.mw.dock_areas
    monkeypatch.setattr(mod.mw, "addDockWidget", lambda area, dock: registered.update({dock: area}))
    monkeypatch.setattr(mod.mw, "removeDockWidget", registered.pop)
    mod._apply_config({"dock_area": "left", "orientation": "vertical"})
    mod.initPB()
    assert list(registered) == [mod.progress_ui.progress_dock]
    mod._remove_progress_bar()
    assert not registered
    assert not mod.mw.docks


@pytest.mark.parametrize(("dialog_type", "open_dialog"), [
    ("ProgressBarConfigDialog", "_open_config_dialog"),
    ("SessionHistoryDialog", "_open_session_history_dialog"),
])
def test_modal_dialogs_release_their_widgets(addon_module, monkeypatch, dialog_type, open_dialog):
    dialog = QDialog(addon_module.mw)
    monkeypatch.setattr(addon_module, dialog_type, lambda parent: dialog)
    getattr(addon_module, open_dialog)()
    assert dialog._deleted
    assert addon_module._session_history_dialog is None
