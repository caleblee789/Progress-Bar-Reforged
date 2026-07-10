# UX Settings Notes

The supported settings surface is intentionally small:

- `progress_bar_enabled` (default: `true`)
- `display_location` (default: `review`)
- `mode` (default: `stats`)
- `dock_area` (default: `top`)
- `theme` (default: `auto`)
- `toggle_shortcut` (default: `Ctrl+G`, which is `Command+G` on macOS)

First-run setup wizards are not part of this baseline. The only custom Tools menu entry should be **Caleb M. Add-ons Settings -> Progress Bar settings**, and it should open the simplified settings dialog directly.

## Implementation boundaries

- `addon/progress/state.py` owns mutable per-profile counts, persistence markers, and dashboard snapshots.
- `addon/progress/scheduler.py` owns collection and scheduler SQL; it must remain free of Qt widget dependencies.
- `addon/progress/lifecycle.py` registers idempotent modern `gui_hooks` callbacks. Do not reintroduce legacy `addHook()` callbacks or Anki 2.0 stylesheet patches.
- `addon/ui/metrics.py` is the single font-measurement fallback. New UI sizing must use Qt font metrics rather than character-count arithmetic.

## Release UI smoke pass

Before publishing, install the generated archive in a disposable Anki profile with sync disabled. Check light, dark, and Auto theme transitions; normal, compact, and HiDPI/narrow widths; long, emoji, CJK, and RTL deck names; and shortcut idle, recording, conflict, and focus-loss states. Capture any Qt fallback log before treating it as a cosmetic issue.
