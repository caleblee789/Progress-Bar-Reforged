# Release Readiness Audit (June 18, 2026)

## Scope

Audited the add-on for AnkiWeb and GitHub release readiness across:

- Reviewer progress bar behavior, keyboard access, and tooltip interaction.
- Deck breakdown, session history, settings dialog, and persisted profile data.
- Configuration defaults, legacy config tolerance, and source-install metadata.
- Latest Anki compatibility metadata and API usage.
- Test coverage, CI coverage, package generation, and release documentation.

## Findings and Fixes

### R1 - Packaged add-on was stale

- **Observed:** `dist/progress_bar_time_left_testing.ankiaddon` still contained deleted `pacing.py` and used an old manifest.
- **Fix:** Added `scripts/package_addon.py` and rebuilt `dist/progress_bar_time_left.ankiaddon` from `addon/` only.
- **Status:** Fixed.

### R2 - Add-on metadata was not release-ready

- **Observed:** `addon/meta.json` had a legacy generated name and embedded old user config values.
- **Fix:** Replaced it with clean release metadata: display name, homepage, `human_version`, empty source-install config, minimum Anki 2.1.49, and latest target Anki 26.05 (`260500`).
- **Status:** Fixed.

### R3 - Keyboard deck-breakdown activation was documented but missing

- **Observed:** The progress bar handled mouse/context-menu activation, but not Enter/Space activation.
- **Fix:** Added Enter, Return, and Space handling to the progress bar interaction filter; added focus policy and accessible metadata.
- **Status:** Fixed and covered by tests.

### R4 - CI did not match release targets

- **Observed:** CI tested Python 3.10/3.11 only and did not exercise package generation.
- **Fix:** Updated CI to test Python 3.10 and 3.13 and build the `.ankiaddon` package.
- **Status:** Fixed.

### R5 - README compatibility and release packaging were outdated

- **Observed:** README still claimed Anki 2.1.49-2.1.66 support and did not describe the GitHub release package path.
- **Fix:** Updated compatibility, installation, verification, and package-build instructions.
- **Status:** Fixed.

## Verification

- `.venv/bin/python -m pytest -q` -> 14 passed.
- `PYTHONPYCACHEPREFIX=.pytest_cache/pycache python3 -B -m py_compile ...` -> passed.
- `.venv/bin/python scripts/package_addon.py` -> created `dist/progress_bar_time_left.ankiaddon`.
- Package inspection confirmed no `pacing.py`, `meta.json`, tests, docs, `.pyc`, `__pycache__`, or `.DS_Store` entries.

## Release Notes

- Latest upstream Anki release checked during this pass: 26.05.
- The package manifest uses positive `max_point_version` metadata (`260500`) to record the latest tested target without disabling the add-on on newer Anki versions.
- Final GUI smoke testing should install `dist/progress_bar_time_left.ankiaddon` in Anki 26.05 and verify reviewer, settings, deck breakdown, and history flows before uploading to AnkiWeb.
