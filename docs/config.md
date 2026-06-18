## Configuration

Progress Bar Time Left is configured from **Tools -> Progress Bar Settings**. The normal settings surface is intentionally small:

- **Enable progress bar** (`progress_bar_enabled`): show or hide the progress bar.
- **Show on** (`display_location`): use `review_and_home` to show it on the deck browser and review screens, or `review` for review screens only.
- **Mode** (`mode`): choose `simple`, `time_left`, or `stats`.
- **Show SMTR** (`show_super_mature_retention`): optionally include super-mature retention in the Stats label.
- **Position** (`dock_area`): dock the bar at the `top` or `bottom` of Anki.
- **Theme** (`theme`): use `auto`, `light`, or `dark`.
- **Shortcut** (`toggle_shortcut`): set the show/hide shortcut.

### Modes

- `simple`: percent plus completed/total cards.
- `time_left`: simple mode plus ETA, time spent, and time remaining.
- `stats`: the default; shows the rich current metric set with Again rate, Retention, speed, yesterday comparisons, ETA, and time totals. SMTR can be added with the Show SMTR setting.

### JSON compatibility

Older configs may still contain advanced keys from previous releases. They are tolerated during load so existing profiles do not break, but the supported settings surface is the lightweight set above.

The warning feature has been removed. Legacy warning keys are ignored if they appear in an existing JSON config.
