Progress Bar Time Left for Anki
===============================

Progress Bar Time Left adds a dockable progress bar to Anki's reviewer. It shows how much of today's review work is done, how much is left, how fast you are moving, and when you are likely to finish.

The add-on builds on Glutanimate's original Progress Bar and Carlos Duarte's More Decks Stats and Time Left, then adds pacing, warnings, deck breakdowns, session history, keyboard control, and modern configuration tools.

Features
--------

* **Live reviewer progress** - track new, learning, and review cards with raw counts, percentages, seconds/card, time spent, ETA, Again rate, true retention, and optional yesterday comparisons.
* **Configurable counting** - choose whether progress advances when cards are answered or when cards are first shown, and whether the bar follows the current deck or the whole session.
* **Deck breakdown dialog** - click the bar to inspect per-deck actionable and buried counts for New/Learning/Review cards, with ETAs when pacing data is available.
* **Pacing and goals** - set daily card or review-time goals, choose the ETA strategy, show ETA confidence, and use per-deck expected seconds as an early-session ETA fallback.
* **Warnings** - highlight the bar when projected time, Again rate, retention, goal pace, or cutoff timing crosses your thresholds. Hysteresis and cooldown settings reduce flicker.
* **Appearance controls** - dock top/bottom/left/right, switch horizontal or vertical orientation, constrain width, invert fill direction, use compact or detailed labels, and enable segmented queue colours.
* **Session history** - store daily pace metrics, review trend charts, export CSV, or clear history from the built-in dialog.
* **Keyboard and persistence** - toggle the bar with a configurable shortcut and preserve same-day progress across Anki restarts/profile reloads.

Compatibility
-------------

The add-on targets Anki 2.1.49 through 2.1.66, matching `addon/meta.json`. Later Anki versions may work, but they are outside the declared support range.

Installation
------------

### From AnkiWeb

1. In Anki, open **Tools -> Add-ons -> Get Add-ons...**
2. Enter code `1097423555`.
3. Restart Anki.

AnkiWeb page: <https://ankiweb.net/shared/info/1097423555>

### From Source

1. Download or clone this repository.
2. In Anki, open **Tools -> Add-ons -> View Files...**
3. Copy the contents of this repo's `addon` directory into a new folder in Anki's add-ons directory.
4. Restart Anki.

Usage
-----

* The progress bar appears as a dock in Anki's main window, top-docked by default.
* Press the toggle shortcut, `Ctrl+G` by default (`Meta+G` on macOS), to show or hide it.
* Hover the bar for context-aware explanations of the current metrics and warnings.
* Click the bar, or focus it and press Enter/Space, to open the deck breakdown.
* Open **Tools -> Progress Bar -> Session History** to review, export, or clear historical pace data.
* Open **Tools -> Progress Bar -> Settings...** to configure the add-on without editing JSON.

Configuration
-------------

Most users should use **Tools -> Progress Bar -> Settings...**. The settings dialog includes section navigation, search, presets, a live preview, import/export, autosave, and an **Apply / Reload** button.

You can also edit JSON from **Tools -> Add-ons -> Progress Bar Time Left -> Config**. After manual edits, use **Tools -> Progress Bar -> Reload Configuration** or restart Anki.

Useful configuration groups:

* **Visibility** - `progress_bar_enabled`, `toggle_shortcut`, `scrolling_bar_when_editing`, `invert_progress`.
* **Counting** - `include_new`, `include_lrn`, `include_rev`, `include_new_after_revs`, `counting_basis`, `count_scope`, `force_forward`.
* **Display** - `show_percent`, `show_number`, `show_again`, `show_retention`, `show_super_mature_retention`, `show_yesterday`, `show_debug`, `label_style`, `display_preset`.
* **Pacing** - `pacing_strategy`, `show_eta_confidence`, `daily_target_cards`, `target_review_minutes`, `deck_profiles`.
* **Warnings** - `warnings_enabled`, `pace_warnings_enabled`, `time_warning_minutes`, `again_warning_percent`, `retention_warning_percent`, `warning_hysteresis_percent`, `warning_cooldown_seconds`, `warning_transition_animations`, `warning_colors`.
* **Appearance** - `orientation`, `dock_area`, `max_width`, `progress_bar_style`, `appearance.day`, `appearance.night`, `stacked_segments`, `segment_colors`, `show_progress_legend`, `legend_position`.
* **Accessibility and motion** - `auto_adjust_contrast`, `focus_mode`, `responsive_breakpoints`, `reduced_motion`, `animated_updates`, `show_warning_badge`, `completion_celebration`.
* **History** - `history_days`.

See [docs/config.md](docs/config.md) for more detail.

Counting and ETA Notes
----------------------

`counting_basis` controls when progress advances:

* `answered` keeps the default behavior: progress advances from cards recorded in the review log.
* `seen` can advance progress as cards are shown in the reviewer, before the answer is logged.

`count_scope` controls what the bar measures:

* `per_deck` follows the selected deck and its children.
* `global` treats all root decks as one review session.

`deck_profiles` can override queue weights and provide `expected_seconds` per deck. Expected seconds are used for early ETA estimates before enough same-day pace samples exist.

Troubleshooting
---------------

* Use **Tools -> Progress Bar -> Validate Config** to check for invalid JSON values and normalization issues.
* Use **Tools -> Progress Bar -> Open Config JSON** as a shortcut to Anki's config editor.
* If the bar disappears, confirm `progress_bar_enabled` is true and reload configuration.
* If labels are crowded, try `display_preset: "minimal"`, `label_style: "compact"`, a wider dock area, or Focus Mode.
* If warnings flicker around a threshold, increase `warning_hysteresis_percent` or `warning_cooldown_seconds`.
* If text is hard to read, keep `auto_adjust_contrast` enabled or adjust the active theme colours.

Development
-----------

Install test dependencies:

```bash
python3 -m pip install -r requirements-dev.txt
```

Run the test suite:

```bash
python3 -m pytest -q
```

Useful smoke checks:

```bash
python3 -B -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in pathlib.Path('.').rglob('*.py')]"
python3 -B -c "from tests.stubs import install_stubs; install_stubs(); import addon.reviewer_progress_bar"
```

Acknowledgments
---------------

This project is built on Glutanimate's Progress Bar and Carlos Duarte's More Decks Stats and Time Left add-ons. Their work made this add-on possible.

Feedback and Support
--------------------

Open an issue or discussion in this repository, or use the AnkiWeb page, if you find a bug or have an improvement request.

License
-------

This add-on is licensed under the [GNU AGPLv3](https://www.gnu.org/licenses/agpl-3.0.en.html).
