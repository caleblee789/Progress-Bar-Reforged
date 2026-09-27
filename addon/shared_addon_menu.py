"""Shared menu footer, bundled independently so each add-on works on its own."""
from __future__ import annotations

import logging


SUPPORT_URL = "https://buymeacoffee.com/caleblee78f"
# IDs, display names, links, and exact local-install identities (not fuzzy matches).
ADDONS = (
    ("1888718775", "Anki Garden", "https://ankiweb.net/shared/info/1888718775",
     ("anki_garden", "ankigarden", "Anki Garden")),
    ("808247776", "Home Screen Dashboard", "https://ankiweb.net/shared/info/808247776",
     ("home_dashboard_overhaul", "Home Screen Dashboard", "Homescreen Dashboard")),
    ("1511983907", "Progress Bar Reforged", "https://ankiweb.net/shared/info/1511983907",
     ("progress_bar_time_left", "progress_bar_reforged", "Progress_Bar_Reforged", "Progress Bar Reforged")),
    ("1352407063", "PronounceIt", "https://ankiweb.net/shared/info/1352407063",
     ("pronounceit",)),
)
_LOG = logging.getLogger(__name__)
_STATE_ATTRIBUTE = "_caleb_m_shared_footer_v1"


def _installed_addons(manager, hosts):
    installed = set(hosts)
    identities = {
        identity.casefold(): addon_id
        for addon_id, _label, _url, aliases in ADDONS
        for identity in (addon_id, *aliases)
    }
    for package in manager.allAddons():
        known = identities.get(str(package).casefold())
        if known is None:
            metadata = manager.addonMeta(package)
            known = identities.get(str(metadata.get("name", "")).casefold())
        if known is not None:
            installed.add(known)
    return installed


def _open_link(url):
    from aqt.utils import openLink

    openLink(url)


def install_shared_menu_footer(menu, main_window, host_id):
    """Register once per shared QMenu, regardless of which add-on loads first."""
    # Minimal/older shells without native menu signals retain their settings.
    if not callable(getattr(getattr(menu, "aboutToShow", None), "connect", None)):
        return
    state = getattr(menu, _STATE_ATTRIBUTE, None)
    if state is None:
        from aqt.qt import QAction

        discovery_separator = menu.addSeparator()
        discovery_separator.setObjectName("caleb_m_discovery_separator")
        discovery = menu.addMenu("Get other add-ons")
        discovery.setObjectName("caleb_m_discovery_menu")
        discovery.menuAction().setObjectName("caleb_m_discovery_action")
        support_separator = menu.addSeparator()
        support_separator.setObjectName("caleb_m_support_separator")
        support = QAction("Support the creator", menu)
        support.setObjectName("caleb_m_support_action")
        support.triggered.connect(lambda _checked=False: _open_link(SUPPORT_URL))
        menu.addAction(support)
        state = {
            "hosts": set(),
            "actions": (discovery_separator, discovery.menuAction(), support_separator, support),
            "discovery": discovery,
            "discovery_failed": False,
        }
        setattr(menu, _STATE_ATTRIBUTE, state)

        def refresh():
            # Older versions and other add-ons may append settings after us.
            # Moving only our actions preserves every existing settings action.
            for action in state["actions"]:
                menu.removeAction(action)
                menu.addAction(action)
            try:
                installed = _installed_addons(main_window.addonManager, state["hosts"])
                missing = [item for item in ADDONS if item[0] not in installed]
                state["discovery_failed"] = False
            except Exception:
                missing = []
                if not state["discovery_failed"]:
                    _LOG.warning("Unable to discover installed add-ons; hiding recommendations", exc_info=True)
                state["discovery_failed"] = True
            discovery.clear()
            for addon_id, label, url, _aliases in missing:
                action = QAction(label, discovery)
                action.setObjectName("caleb_m_get_" + addon_id)
                action.triggered.connect(lambda _checked=False, target=url: _open_link(target))
                discovery.addAction(action)
            discovery_separator.setVisible(bool(missing))
            discovery.menuAction().setVisible(bool(missing))
            support_separator.setVisible(True)
            support.setVisible(True)

        state["refresh"] = refresh
        menu.aboutToShow.connect(refresh)
    state["hosts"].add(host_id)
    state["refresh"]()
