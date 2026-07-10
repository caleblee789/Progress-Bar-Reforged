## Configuration

Progress Bar Time Left is configured from **Caleb M. Add-ons Settings -> Progress Bar settings**. The normal settings surface is intentionally small:

- **Enable progress bar** (`progress_bar_enabled`): show or hide the progress bar.
- **Show on** (`display_location`): use `review` for review screens only, or `review_and_home` to show it on the deck browser and review screens.
- **Mode** (`mode`): choose `simple` or `stats` through the Simple and Advanced options.
- **Show SMTR** (`show_super_mature_retention`): optionally include super-mature retention in the Advanced label.
- **Position** (`dock_area`): dock the bar at the `top` or `bottom` of Anki.
- **Theme** (`theme`): use `auto`, `light`, or `dark`.
- **Shortcut** (`toggle_shortcut`): set the show/hide shortcut.

### Modes

- `simple`: percent plus completed/total cards.
- `stats`: the default Advanced mode; shows the rich current metric set with Again rate, Retention, speed, yesterday comparisons, ETA, and time totals. SMTR can be added with the Show SMTR setting.

### JSON compatibility

Older configs may still contain advanced keys from previous releases. They are tolerated during load so existing profiles do not break, but the supported settings surface is the lightweight set above.

Older configs may also contain `time_left`. It is still accepted for compatibility, but the settings dialog now maps it to Advanced and saves `stats`.

The warning feature has been removed. Legacy warning keys are ignored if they appear in an existing JSON config.
