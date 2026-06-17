# UI Stabilization Pass Report (April 9, 2026)

## Scope
Single-pass audit across all add-on UI surfaces:
- Reviewer progress bar (standard + segmented variants)
- Progress legend + info affordance
- Deck breakdown dialog
- Session history dialog
- Progress Bar settings dialog
- Quick setup wizard

Assessment dimensions: layout consistency, responsiveness, accessibility, and interaction-state behavior.

## Defect Log

### P1-01 — Progress bar was mouse-only for opening deck breakdown (fixed)
- **Area:** Reviewer progress bar interaction model
- **Type:** Accessibility / interaction-state
- **Observed:** Deck breakdown could be opened via mouse only; keyboard users had no equivalent action path.
- **Fix:** Added key handling for `Enter`, `Return`, and `Space` on the progress bar interaction filter; added strong focus policy on the bar so keyboard navigation reaches it.
- **Status:** ✅ Fixed in this pass.

### P1-02 — Missing accessible metadata on core reviewer controls (fixed)
- **Area:** Reviewer progress bar + info button
- **Type:** Accessibility
- **Observed:** Primary progress widget and info button had no explicit accessible name/description.
- **Fix:** Added accessible name/description for progress bar and info button; increased info button minimum hit target and keyboard focusability.
- **Status:** ✅ Fixed in this pass.

### P1-03 — Deck breakdown “Focus selected deck” action was non-functional (fixed)
- **Area:** Deck breakdown dialog
- **Type:** Interaction-state / expectation mismatch
- **Observed:** Button only showed a tooltip and did not actually switch focus to selected deck.
- **Fix:** Implemented deck focus flow by selecting deck ID and moving to overview state, with failure-safe user feedback.
- **Status:** ✅ Fixed in this pass.

### P2-01 — Dense control row in deck breakdown can feel cramped on narrow widths (fixed)
- **Area:** Deck breakdown dialog
- **Type:** Responsiveness / polish
- **Observed:** Sort/filter/search + two buttons in one horizontal row can become visually tight on smaller windows.
- **Fix:** Split deck breakdown controls into a two-row layout: sort/filter/search stay together, while pin/focus actions move to a separate action row.
- **Status:** ✅ Fixed in follow-up pass.

### P2-02 — Session history chart area lacks explicit keyboard navigation affordances (fixed)
- **Area:** Session history charts
- **Type:** Accessibility / polish
- **Observed:** Charts are visual-only and don’t expose a tab-focus summary surface.
- **Fix:** Added focusable chart summary text plus synchronized accessible descriptions/tooltips on each chart.
- **Status:** ✅ Fixed in follow-up pass.

### P2-03 — Settings dialog minimum width remains desktop-first (fixed)
- **Area:** Progress Bar settings dialog
- **Type:** Responsiveness / polish
- **Observed:** Large minimum width favors desktop but can be restrictive at smaller display scales.
- **Fix:** Reduced the minimum width, split footer controls into compact rows, and added a compact section selector that replaces the side navigation below the responsive breakpoint.
- **Status:** ✅ Fixed in follow-up pass.

### P2-04 — Malformed history records can interrupt history loading (fixed)
- **Area:** Session history persistence
- **Type:** Robustness
- **Observed:** Invalid numeric values in stored history records could raise during dialog load.
- **Fix:** Added safe numeric coercion for persisted history metrics while continuing to skip entries with invalid day identifiers.
- **Status:** ✅ Fixed in follow-up pass.

### P3-01 — Next-day ETA strings sorted after unavailable ETA values (fixed)
- **Area:** Deck breakdown sorting
- **Type:** Polish / ordering
- **Observed:** ETA strings with a `+1` day suffix were not parsed by the due-soon sort key.
- **Fix:** Parse optional day offsets in ETA sort keys so next-day times sort before `N/A`.
- **Status:** ✅ Fixed in follow-up pass.

## Regression / Visual Check
- Ran full unit test suite after fixes.
- Performed static code inspection of touched interaction paths and dialog wiring.
- Follow-up pass expanded regression coverage to 36 tests and ran Python compile checks.
- Screenshot capture not produced because these are Anki/Qt add-on dialogs rather than browser-rendered surfaces.

## Files Updated During Stabilization
- `addon/ui/progress_bar.py`
- `addon/reviewer_progress_bar.py`
- `addon/history.py`
- `AUDIT_REPORT.md`
- `tests/stubs.py`
- `tests/test_progress_bar.py`
