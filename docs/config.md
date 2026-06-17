## Configuration

ProgressBarTimeLeft reads all of its settings from the add-on configuration dialog (Tools → Add-ons → Progress Bar Time Left → Config). The JSON file is structured with human-readable keys so you can edit it directly if you prefer. The most important groups are:

- **Queue selection** (`include_new`, `include_rev`, `include_lrn`, `include_new_after_revs`): choose which queues contribute to the progress bar totals.
- **Visibility & control** (`progress_bar_enabled`, `toggle_shortcut`, `invert_progress`, `scrolling_bar_when_editing`): hide or show the bar, change the fill direction, and decide how the Tools menu shortcut behaves.
- **Appearance** (`orientation`, `dock_area`, `max_width`, `progress_bar_style`): control where the bar is docked and how it looks. The `appearance.day` and `appearance.night` dictionaries provide separate colour themes for light and dark modes (text, background, foreground, and border radius).
- **Statistics text** (`show_percent`, `show_number`, `show_again`, `show_retention`, `show_super_mature_retention`, `show_yesterday`, `show_debug`, `label_style`): toggle which metrics are rendered in the progress label. `label_style` can be `compact` or `detailed` and only changes presentation copy, not calculations. When `show_yesterday` is true, yesterday's speed/retention appears in parentheses next to today's numbers.
- **Behaviour** (`lrn_steps`, `force_forward`, `no_days`, `tz`, `scrolling_bar_when_editing`): adjust how review speed and time remaining are calculated and how the widget behaves when editing cards.
- **Warnings** (`warnings_enabled`, `warning_colors`, `time_warning_minutes`, `again_warning_percent`, `retention_warning_percent`): opt into warning indicators and control which thresholds trigger them (projected time, Again rate, and retention). Warnings are disabled by default. Leave entries in `warning_colors` blank to reuse the current theme; fill them to change the bar's text/background/chunk colours when a warning is active.


- **Onboarding & UX polish** (`quick_setup_enabled`, `focus_mode`, `responsive_breakpoints`, `show_warning_badge`, `completion_celebration`): controls first-run setup and optional visual simplifications.
- **Motion controls** (`reduced_motion`, `animated_updates`, `warning_transition_animations`): smooth progress and warning changes, while allowing reduced-motion behavior.
- **Segment enhancements** (`show_segment_inline_labels`): render compact labels directly on segmented bars when space allows.
- **Deck breakdown pins** (`pinned_deck_views`): persist your preferred deck subset in the breakdown dialog.

All options accept standard JSON booleans (`true`/`false`), numbers, or strings as appropriate. Most changes can be applied immediately via **Tools → Progress Bar → Reload Configuration** or **Apply / Reload** in the settings dialog.

## Validation and troubleshooting

- Use **Tools → Progress Bar → Validate Config** to run normalization checks and show key-specific issues.
- Use **Tools → Progress Bar → Open Config JSON** to jump to the add-on config editor quickly.
- Invalid config values never crash the add-on; unsupported values fall back to defaults and a non-intrusive message is shown.
- `max_width` expects a CSS-like unit (for example `320px`, `60%`, `12em`) or digits (interpreted as px).
- Percentage thresholds (`again_warning_percent`, `retention_warning_percent`) are clamped to `0..100`.


## New pacing and UX controls

- `pacing_strategy`: `average|ewma|trimmed|median|segmented` (default `ewma`).
- `show_eta_confidence`: show Low/Medium/High confidence next to ETA.
- `warning_hysteresis_percent` and `warning_cooldown_seconds`: stabilize warning toggles.
- `display_preset`: `minimal|compact|expanded`.
- `auto_adjust_contrast`: auto-correct low contrast theme text colors.
- `deck_profiles`: optional per-deck weights and expected seconds.
