# Comprehensive Audit Report (July 6, 2026)

## Scope and safety boundary

Audited the complete working tree, including the existing uncommitted theme/UI work. The audit covered configuration and migration behavior, scheduler/count calculations, persistence and history, Qt hook/widget lifecycles, shortcuts, all add-on UI surfaces, accessibility, and packaging.

Real-runtime checks used Anki 26.05 with the disposable base `/tmp/progressbar-audit.nf2qM8`, profile `User 1`, no sync key, and add-on package `1511983907`. The normal Anki base/profile was not used or modified.

## Findings and fixes

### Medium: malformed stored progress/history could break startup or dialogs

- **Reproduction:** Store non-numeric, non-finite, negative, or structurally invalid values in `progress_bar_persistent_counts`, `progress_bar_history`, `appearance`, or `segment_colors`.
- **Root cause:** Several restoration paths converted values without guarded finite/range checks; two object-validation branches could not report malformed payloads.
- **Fix:** Added bounded, finite, backward-compatible normalization; invalid entries are skipped or repaired; repairs are idempotent and preserve valid records and explicit user colors.
- **Verification:** Migration/config/history regression tests and isolated restart restoration passed.

### Medium: day rollover and profile close could retain or erase the wrong snapshot

- **Reproduction:** Keep Anki open across the scheduler cutoff, or open/close a profile before progress restoration runs.
- **Root cause:** Restoration was guarded by one process-wide boolean with no restored-day identity; profile close could persist empty in-memory maps before loading the saved snapshot.
- **Fix:** Track the restored scheduler day, reset counts on rollover, restore before persisting, force a final close-time flush, and clear profile-specific state after teardown.
- **Verification:** Same-day restart, rollover, unrestored-close, retention, and isolated Anki restart tests passed.

### Medium: completed-card categories changed after cards changed state

- **Reproduction:** Answer new, learning, relearning, or filtered-deck cards, then recalculate after the card graduates or returns to its original deck.
- **Root cause:** Completed categories were derived from each card's current `cards.type`, not the historical `revlog.type`/`lastIvl` answer state.
- **Fix:** Classify completed answers from revlog history and continue attributing filtered-deck answers to the original deck via `odid`.
- **Verification:** Real SQLite tests cover new, learning, relearning, review, filtered-deck, nested-deck, limit, suspended, and buried cases.

### Medium: lifecycle cleanup left stale Qt/dock references

- **Reproduction:** Reapply settings repeatedly, close/reopen profiles, or retheme after a dialog's native Qt object has been deleted.
- **Root cause:** The progress widget was deleted without explicitly deleting/tracking its dock, and cached dialogs were called without handling deleted wrapper objects.
- **Fix:** Track and delete the owning dock, drop deleted dialog references, close dialogs and remove the bar on profile close/profile-manager transitions, and guard startup callbacks when no collection is available.
- **Verification:** Dock reuse/teardown, deleted-dialog, profile-switch, and isolated close/reopen checks passed.

### Medium: progress details were computed but discarded; long labels clipped

- **Reproduction:** Hover the progress bar or use Stats mode at a normal-width Anki window.
- **Root cause:** The tooltip layer replaced every supplied detail string with the deck-breakdown hint; the progress label had no measured-width fallback.
- **Fix:** Preserve completed/remaining/default tooltip detail plus the breakdown hint, honor tooltip disablement, and use compact/minimal measured labels when the full Stats label does not fit.
- **Verification:** Tooltip-region/disabled tests passed; real Anki captures show `0/1 (0%) | 1 left` without clipping at 667 logical pixels.

### Medium: theme tokens missed requested WCAG component thresholds

- **Reproduction:** Measure disabled text, structural/control borders, semantic chip borders, empty/active workload segments, and tooltip/destructive borders in Light and Dark modes.
- **Root cause:** Several subtle borders and segment colors were below 3:1; disabled text was below 4.5:1.
- **Fix:** Adjusted cool-neutral and semantic tokens while preserving explicit saved progress-bar colors. New default semantic segment colors clear 3:1 against both built-in tracks.
- **Verification:** Automated contrast matrix enforces 4.5:1 text and 3:1 controls/borders/focus/graphics across both themes.

### Low: UI surfaces clipped or rendered inconsistently

- **Reproduction:** Open settings/history at their minimum sizes or force Dark mode for the donation raster.
- **Root cause:** Settings opened narrower than the shortcut row, history opened narrower than its columns, and macOS tinted the branded raster when painted as a native icon.
- **Fix:** Increased practical minimum widths, shortened recorder guidance, widened history, and rendered the raster as an untinted stylesheet image.
- **Verification:** Final real-Anki Light/Dark/Auto captures show unclipped settings/history/progress content and the correct Dark-mode donation image.

### Low: boundary and paint rounding defects

- **Reproduction:** Place a revlog row exactly at a day boundary or divide a small segmented bar into rounded widths.
- **Root cause:** History queries used inclusive end boundaries; independently rounded segment widths could leave gaps or overflow.
- **Fix:** Use half-open `[start, end)` history windows and assign the final segment the remaining pixels.
- **Verification:** SQLite boundary and exact-fill painting regressions passed.

## Compatibility and interfaces

- Add-on ID remains `1511983907`.
- Human version is `1.1.0` for this release.
- Existing config/profile-history keys, menu behavior, public exports, and explicit saved colors remain supported.
- Minimum/maximum metadata remains Anki 2.1.49 through tested target 26.05 (`49` / `260500`). Older compatibility was checked through static/stub coverage only, as required.
- Release packaging was prepared after the audit; publication history is tracked in Git and the release platforms.

## Verification evidence

- `./.venv/bin/python -m pytest -q` -> 77 passed.
- `git diff --check` -> passed.
- `py_compile` across all shipped Python modules and the package script -> passed.
- Stub import smoke test -> passed.
- Package build -> `dist/progress_bar_time_left.ankiaddon`.
- Final archive SHA-256 -> `db3cb38272954171e26765e84a5d2c7a1457f387ff9f0dae89d7f3e160d42925`.
- Archive manifest -> package `1511983907`, human version `1.1.0`, minimum `49`, maximum `260500`.
- Archive payload -> 10 intended source files, byte-for-byte equal to `addon/`; no tests, docs, metadata state, caches, or development files.
- Isolated Anki result -> `/tmp/progressbar-audit.nf2qM8/integration-result.json` reports Anki `26.05`, sync disabled, config restart verified, progress restart verified, theme hook available, and final package smoke verified.
- Runtime exercised startup, deck-browser/overview/review callbacks, real scheduler/database counts, Apply persistence, restart restoration, shortcut toggling, top/bottom dock placement, dialogs, live retheming, history, profile close, and reopen.
- Native Retina captures cover settings, deck breakdown, history, and progress surfaces in Light, Dark, and Auto. macOS retained DPR 2.0 despite Qt scale overrides; the 1x inspection set was therefore downsampled to each widget's exact logical dimensions and visually inspected separately.

## Final status

No reproducible high- or medium-severity defects remain. No cosmetic issue is intentionally deferred.
