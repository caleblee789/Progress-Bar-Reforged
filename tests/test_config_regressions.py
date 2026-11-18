from unittest.mock import MagicMock

import pytest


def test_switching_modes_keeps_advanced_retention_preference(addon_module):
    mod = addon_module
    mod._apply_config({"mode": "stats", "show_super_mature_retention": True})
    for mode in ("simple", "stats"):
        dialog = mod.ProgressBarConfigDialog(mod.mw)
        dialog.mode_combo.setCurrentIndex(dialog.mode_combo.findData(mode))
        dialog._save_and_close()
        assert mod.mw.addonManager.config["show_super_mature_retention"] is True
        assert mod.settings.show_super_mature_retention is (mode == "stats")


@pytest.mark.parametrize("orientation, prop", [("horizontal", "min-height"), ("vertical", "min-width")])
def test_configured_minimum_thickness_survives_stylesheet_generation(mw, orientation, prop):
    from addon.config import apply_config

    style = apply_config(mw, {"orientation": orientation, "min_height": 38}).default_stylesheet
    assert f"{prop}: 38px;" in style
    assert style.count(f"{prop}:") == 1


def test_menu_discovers_addons_on_open_and_keeps_unchanged_actions(mw):
    from addon.shared_addon_menu import ADDONS, _STATE_ATTRIBUTE, install_shared_menu_footer

    menu = MagicMock()
    setattr(menu, _STATE_ATTRIBUTE, None)
    manager = MagicMock()
    mw.addonManager = manager
    host = ADDONS[2][0]
    manager.allAddons.return_value = [host, "local_copy"]
    manager.addonMeta.return_value = {"name": "Anki Garden"}
    install_shared_menu_footer(menu, mw, host)
    manager.allAddons.assert_not_called()

    refresh, = menu.aboutToShow.connect.call_args.args
    discovery = menu.addMenu.return_value
    refresh()
    assert discovery.addAction.call_count == 2
    refresh()
    discovery.clear.assert_called_once()

    manager.allAddons.return_value = ["unrelated"] + [addon[0] for addon in ADDONS]
    manager.addonMeta.reset_mock()
    refresh()
    manager.addonMeta.assert_not_called()
    discovery.menuAction.return_value.setVisible.assert_called_with(False)
