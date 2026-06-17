# UX + Onboarding Extension Notes

New optional settings (all backward-compatible defaults):

- `quick_setup_enabled` (default: `true`)
- `focus_mode` (default: `false`)
- `reduced_motion` (default: `false`)
- `animated_updates` (default: `true`)
- `warning_transition_animations` (default: `true`)
- `show_segment_inline_labels` (default: `false`)
- `show_warning_badge` (default: `true`)
- `completion_celebration` (default: `true`)
- `responsive_breakpoints` (default: `true`)
- `pinned_deck_views` (default: `[]`)

## Extending Quick Setup

`QuickSetupWizard.selected_config()` returns a dictionary merged into the existing config. Add new wizard options by:

1. Creating a new control in `QuickSetupWizard.__init__`.
2. Emitting that value from `selected_config()`.
3. Adding a sane default in `addon/config.json` and validation in `addon/config.py`.

## Optional behavior guarantee

All UX polish features are togglable and disabled gracefully in constrained layouts:

- Focus mode suppresses non-essential bar text and legend elements.
- Responsive compact mode reduces text verbosity below small-width breakpoints.
- Reduced-motion mode bypasses progress interpolation.
