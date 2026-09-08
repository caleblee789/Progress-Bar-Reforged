# Dock controls regression fix — September 8, 2026

The preceding theme-isolation change exposed Qt's resize strip beneath the progress bar. Right-clicking that area could open an unnamed, checked dock-visibility action.

The progress dock now has no dragging, floating, or closing features, a zero-size title widget, and a hidden native visibility action. Its thickness is fixed to its styled content size while its length still follows the window. Position settings and the add-on's existing toggle shortcut remain available. Anki's main-window stylesheet and palette remain untouched.

The original styled dock had a minimum height of 21 pixels and a maximum of 22 pixels. That difference is sufficient for Qt to expose a resize handle. The corrected native layout has equal minimum and maximum thickness. This follows [Qt's separator layout and painting rules](https://raw.githubusercontent.com/qt/qtbase/6.8/src/widgets/widgets/qdockarealayout.cpp); the checkmark originates from [Qt's default dock context menu](https://raw.githubusercontent.com/qt/qtbase/6.8/src/widgets/widgets/qmainwindow.cpp).

Validation:

- **101 regression tests passed**, with the existing initialization test extended to cover the dock controls.
- **42 headless real Anki/Qt component checks passed** against the rebuilt archive. These include top/bottom placement, default/larger text, resizing, hidden menu entries, another dock remaining resizable and accessible, answer/undo counts, deck scope, rollover, settings persistence, and host-theme preservation.
- Rendered top/default and bottom/larger-text layouts were inspected. No resize grip or clipping was visible. These are offscreen Qt checks, not full desktop acceptance with the user's installed add-on combination.
- ZIP integrity, Python syntax, canonical package ID, and source/archive equality passed for all 16 payload files. No additional regressions were found in these checks.

Rebuilt archive: `dist/progress_bar_time_left.ankiaddon` (61,053 bytes). The `dist/progress_bar_time_left-release-candidate.ankiaddon` alias contains identical bytes.

SHA-256: `d9d3e41c2bf26a049cc05098576127b42b3f9c2bde7168655d7987829d2d010f`

Evidence: `review_evidence/20260908-dock-regression/`. The superseded candidate is preserved under `review_evidence/20260907-release-audit/`. No normal-profile installation or public release was performed.


## Follow-up: remove the apparent resize strip

The installed add-on matched the prior archive byte for byte, but live macOS inspection showed a 16px gap between the fixed 25px dock and central content at y=41. Locking the dock prevented resizing without removing the reserved separator space.

Top/bottom placement now inserts the progress widget directly into Anki's existing content layout. Side placement retains the locked dock. Removal detaches the inline widget before deletion; host styling and other docks remain unchanged.

Validation: 101 existing tests passed; 42 real Anki/Qt component checks passed, including zero top/bottom gap with default and larger text, window resizing, lifecycle cleanup, and another add-on dock. The installed payload matches the rebuilt archive. The UI module was refreshed in the existing review window without restarting Anki or answering a card. Live geometry is now bar `(0, 0, 1710, 22)` followed by toolbar `(0, 22, 1710, 35)`: zero gap, no progress dock. The resulting review screen was visually inspected.

Current archive SHA-256: `76a90435f1e2309a1efa3804815db6781e211f89a2d776cb41fcb5bc4e81a2ee`.
Evidence and prior installed-file backup: `review_evidence/20260908-inline-bar/`. Both distribution archives match. Installed metadata was updated while preserving settings. No public release was performed.
