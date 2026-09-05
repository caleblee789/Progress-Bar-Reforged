## Configuration

Progress Bar Reforged is configured from **Caleb M. Add-ons Settings -> Progress Bar settings**. The normal settings surface is intentionally small:

- **Enable progress bar** (`progress_bar_enabled`): show or hide the progress bar.
- **Show on** (`display_location`): `review` (Review Only) is the default. `review_and_home` also shows the bar on the deck browser and overview. This option does not change Advanced metrics during review.
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

Legacy `lrn_steps` is retained only as ignored compatibility data. Changing it cannot affect any calculation. Anki's Learning/Relearning queue counts are used directly, without estimating future repetitions.

### Progress and time calculations in v1.1.3

The fill is weighted by `1 + historical Again rate`, separately for New, Learning/Relearning, and Review. Rates use the previous `no_days` completed scheduler days (default 7), excluding today. Each actual answer belongs to one category; categories without history have weight 1. Weights refresh on profile/day/lookback changes and stay stable during today's answers.

The displayed completion percentage always uses raw counts: completed answers divided by completed answers plus actionable remaining cards. Repeated answers count separately. Four answers at weight 1.5 plus six remaining cards at weight 1 give 50% fill and 40% displayed completion. The bar explains the adjustment in its tooltip and accessibility description without adding a second completion percentage.

ETA uses measured review time, never weights or learning-step counts. Before five answers today, it uses the answer-weighted average of usable retained daily history; afterward, it uses today's recorded seconds per answer. Without either estimate it displays N/A. Anki's recorded time may be capped by the deck's answer-time limit.

Completed answers follow the cards' current deck ownership, with original-deck attribution for filtered cards in Home totals. A selected filtered deck uses its currently contained cards consistently for counts and statistics. Anki's revlog has no deck ID, so historical deck attribution cannot be reconstructed after moves, return from a filtered deck, or deletion. Those scope changes can change progress.

Advanced labels refit when the dock is resized, including a bar retained between Home and Review. Spacing is reduced before falling back to compact text at narrow widths; the detailed tooltip remains available.
