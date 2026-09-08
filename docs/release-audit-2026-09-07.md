# Release functionality audit — September 7, 2026

Four verified bugs were fixed. Automated and headless native checks pass. Interactive desktop acceptance remains incomplete because the UI automation surface selected the normal Anki profile instead of the newly launched disposable profile. No interaction was performed on the normal window.

## Fixes

- **Incorrect deck totals after re-enabling the bar.** Navigation now updates the selected deck while the bar is disabled or hidden by Review Only. This also fixes enabling Review and Home from a previously hidden overview and restoring collection-wide totals on Home.
- **Bar disappears after the study day changes.** Daily metric reset now preserves the current screen and deck, allowing settings changes and toggling to keep working immediately after rollover.
- **Appearance conflicts with Anki and other add-ons.** Bar refreshes no longer replace the main-window stylesheet. Rounded/custom-style bars no longer change the main-window palette. The legacy Night Mode integration no longer modifies another add-on's stylesheet.
- **Startup errors from malformed numeric settings.** Non-finite dimensions and overflowing numeric conversions fall back to defaults instead of raising exceptions during configuration loading.

Weighted bar fill and raw completion percentage retain their existing behavior.

## Validation

- Original suite: **99 passed**.
- Four focused regression checks failed against the original implementation, reproducing the identified issues.
- Final suite: **101 passed**. Two existing tests were extended; two tests were added for navigation and host-theme preservation.
- **20 headless component checks passed** with the installed Anki 26.08.1 backend and real Qt widgets. Coverage includes actual scheduler answer/undo, active-queue counts, nested-deck aggregation, hidden-bar navigation, rollover, theme isolation, native settings Apply/Cancel, deck-breakdown population, and same-day controller/profile-state restoration. These checks use a synthetic collection and a minimal main-window host, not the full desktop application workflow.
- The exact candidate loaded in the full Anki 26.08.1 application in a fresh disconnected profile with automatic and media sync disabled. Review Only was hidden on startup Home as expected.
- ZIP integrity, canonical add-on ID, source/archive equality, and installed/archive equality passed for all **16 payload files**.
- Size and modification-time snapshots of **22 normal-profile/add-on files** were unchanged. No installation was made into the normal profile.

## Candidate

File: `dist/progress_bar_time_left-release-candidate.ankiaddon`

Size: **60,797 bytes**

SHA-256: `3eaec54ccc3da5e89303a465dc9539fa277fa43cc6069f5a2f71c34c36817ded`

This is a local candidate. Its existing **1.1.3** metadata is unchanged; it has not been published. The existing release archive was preserved.

Machine-readable checks and the headless reproduction script are in `review_evidence/20260907-release-audit/`. The full desktop startup profile is `/private/tmp/anki-release-qa.ncrqa1cs`; its process was stopped after recording the window-targeting mismatch.

Before publication, complete interactive review/shortcut/dialog/restart checks against this exact candidate or the final versioned archive. Windows, Linux, and the advertised older Anki versions were not exercised in this run.
