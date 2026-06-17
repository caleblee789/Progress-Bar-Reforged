import importlib
import sys
from typing import Any

import pytest

from tests.stubs import install_stubs, reset_stubs


@pytest.fixture(autouse=True)
def _setup_stubs() -> Any:
    install_stubs()
    yield


@pytest.fixture
def mw():
    return reset_stubs()


@pytest.fixture
def addon_module(mw):
    from tests.stubs import install_stubs

    install_stubs()
    for name in [
        "addon.reviewer_progress_bar",
        "addon.nightmode",
        "addon.config",
        "addon.history",
        "addon.ui.progress_bar",
    ]:
        if name in sys.modules:
            del sys.modules[name]
    module = importlib.import_module("addon.reviewer_progress_bar")
    module._apply_config({})
    return module
