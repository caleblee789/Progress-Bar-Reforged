Progress_Bar_Reforged for Anki
===============================

Progress_Bar_Reforged adds a dockable progress bar to Anki's reviewer. It shows how much of today's review work is done, how much is left, how fast you are moving, and when you are likely to finish.

Current release: **v1.1.1**. Install from AnkiWeb with code `1511983907`, or download `progress_bar_time_left.ankiaddon` from the GitHub release artifacts.

What's new in v1.1.1
--------------------

* **Simpler settings** - choose Simple or Advanced mode, with review-only display as the default and legacy Time Left settings migrated safely to Advanced.
* **Correct macOS shortcut behavior** - the portable `Ctrl+G` setting now appears as `Command+G` on macOS instead of binding the physical Control key.
* **Shared add-on menu** - settings now live under **Caleb M. Add-ons Settings**, alongside other compatible add-ons from the same author.
* **More useful early-session estimates** - ETA and time-left projections use recent history until today's pace becomes reliable after five reviewed cards.
* **Modernized internals** - progress state, scheduler queries, lifecycle hooks, and text measurement are separated into focused modules, with current Anki hooks and more visible UI fallbacks.

Features
--------

* **Live reviewer progress** - choose Simple or Advanced mode to control how much progress detail appears while reviewing.
* **Current-deck counting** - track active New/Learning/Review work, completed cards, percentage done, speed, time spent, time left, and ETA.
* **Deck breakdown dialog** - click the bar to inspect per-deck actionable and buried counts for New/Learning/Review cards, with ETAs once today's pace is known.
* **Retention metrics** - Advanced mode shows Again rate, Retention, optional super-mature retention, and yesterday comparisons.
* **Display and appearance controls** - show the bar during reviews only or on both the deck browser and review screens, choose top or bottom docking, and use Auto, Light, or Dark theme.
* **Session history data** - preserve daily pace metrics for compatibility with existing profiles.
* **Keyboard and persistence** - toggle the bar with a configurable shortcut and preserve same-day progress across Anki restarts/profile reloads.
* **Accessible theme system** - coordinated Light, Dark, and Auto palettes with visible focus states and contrast-tested text, controls, borders, and progress graphics.

Compatibility
-------------

The add-on supports Anki 2.1.49 and newer. Release metadata records Anki 26.05 (`260500`) as the current tested API target in `addon/meta.json`.

Installation
------------

### From AnkiWeb

1. In Anki, open **Tools -> Add-ons -> Get Add-ons...**
2. Enter code `1511983907`.
3. Restart Anki.

AnkiWeb page: <https://ankiweb.net/shared/info/1511983907>

### From a Release Package

1. Download `progress_bar_time_left.ankiaddon` from the GitHub release artifacts.
2. In Anki, open **Tools -> Add-ons -> Install from file...**
3. Select the downloaded `.ankiaddon` file.
4. Restart Anki.

### From Source

1. Download or clone this repository.
2. In Anki, open **Tools -> Add-ons -> View Files...**
3. Copy the contents of this repo's `addon` directory into a new folder in Anki's add-ons directory.
4. Restart Anki.

Usage
-----

* The progress bar appears as a dock in Anki's main window, top-docked by default, during reviews only.
* Press the toggle shortcut, `Ctrl+G` by default (`Command+G` on macOS), to show or hide it.
* Hover the bar for context-aware explanations of the current metrics.
* Click the bar, or focus it and press Enter/Space, to open the deck breakdown.
* Open **Caleb M. Add-ons Settings -> Progress Bar settings** to configure the add-on without editing JSON.

Configuration
-------------

Most users should use **Caleb M. Add-ons Settings -> Progress Bar settings**. The settings dialog is intentionally small: enable the bar, choose where it appears, choose Simple or Advanced mode, optionally show SMTR, choose top/bottom position, choose a theme, and set the shortcut.

You can also edit JSON from **Tools -> Add-ons -> Progress_Bar_Reforged -> Config**. After manual edits, restart Anki.

Useful configuration keys:

* **Core** - `progress_bar_enabled`, `display_location`, `mode`, `show_super_mature_retention`, `dock_area`, `theme`, `toggle_shortcut`.
* **Modes** - `simple` shows count/percent, and `stats` powers the Advanced label with ETA, review time, retention, speed, and optional SMTR. Legacy `time_left` configs are accepted and saved as `stats` from the settings dialog.
* **Compatibility** - older advanced JSON keys are tolerated, but the supported settings surface is intentionally lightweight.

See [docs/config.md](docs/config.md) for more detail.

Troubleshooting
---------------

* If the bar disappears, confirm `progress_bar_enabled` is true and restart Anki.
* If labels are crowded, use Simple mode.
* If text is hard to read, switch Theme between Auto, Light, and Dark. Explicit custom progress-bar colors remain unchanged when switching themes.

Development
-----------

Install test dependencies:

```bash
python3 -m pip install -r requirements-dev.txt
```

Run the test suite:

```bash
.venv/bin/python -m pytest -q
```

Useful smoke checks:

```bash
PYTHONPYCACHEPREFIX=.pytest_cache/pycache .venv/bin/python -B -m py_compile addon/config.py addon/history.py addon/nightmode.py addon/reviewer_progress_bar.py addon/progress/state.py addon/progress/scheduler.py addon/progress/lifecycle.py addon/ui/metrics.py addon/ui/progress_bar.py addon/__init__.py scripts/package_addon.py
.venv/bin/python -c "from tests.stubs import install_stubs; install_stubs(); import addon.reviewer_progress_bar"
```

Build the release package:

```bash
.venv/bin/python scripts/package_addon.py
unzip -l dist/progress_bar_time_left.ankiaddon
```

The package builder emits `dist/progress_bar_time_left.ankiaddon` with a generated `manifest.json`. It excludes local `meta.json`, tests, docs, Python caches, and platform files.

Architecture and UI QA notes are in [docs/developer-notes-ux-onboarding.md](docs/developer-notes-ux-onboarding.md).

Acknowledgments
---------------

This project is built on Glutanimate's Progress Bar and Carlos Duarte's More Decks Stats and Time Left add-ons. Their work made this add-on possible.

Feedback and Support
--------------------

Open an issue or discussion in this repository, or use the AnkiWeb page, if you find a bug or have an improvement request.

License
-------

This add-on is licensed under the [GNU AGPLv3](https://www.gnu.org/licenses/agpl-3.0.en.html).
