import sys
import importlib.util
from pathlib import Path


def _load_module(rel_path: str, name: str):
    module_path = Path(__file__).resolve().parents[1] / rel_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_estimate_pace_ewma_is_stable():
    pacing = _load_module("addon/pacing.py", "addon_pacing_test")
    estimate = pacing.estimate_pace("ewma", [10, 10, 11, 10, 9, 10])
    assert estimate is not None
    assert 9 <= estimate.seconds_per_card <= 11
    assert estimate.confidence in {"Low", "Medium", "High"}


def test_stabilized_warning_hysteresis_and_cooldown():
    pacing = _load_module("addon/pacing.py", "addon_pacing_test2")
    s = pacing.StabilizedWarning()
    assert s.evaluate("again", 16, 15, higher_is_worse=True, hysteresis=2, cooldown_s=0, now=1.0) is True
    assert s.evaluate("again", 14.5, 15, higher_is_worse=True, hysteresis=2, cooldown_s=0, now=2.0) is True
    assert s.evaluate("again", 12.9, 15, higher_is_worse=True, hysteresis=2, cooldown_s=0, now=3.0) is False


def test_contrast_helpers_exist_in_config_source():
    config_source = (Path(__file__).resolve().parents[1] / "addon" / "config.py").read_text()
    assert "def _ensure_contrast" in config_source
    assert "def _contrast_ratio" in config_source
