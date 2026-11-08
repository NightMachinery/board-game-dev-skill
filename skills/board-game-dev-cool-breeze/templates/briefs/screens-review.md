# Screens review: <ROUND_ID>

Review only. Change no repo files. Read AGENTS.md, `<DESIGN_CONTRACTS>` and
`<SCREEN_MANIFEST>`. Images/contact sheets: `<ARTIFACT_DIR>`. Provider/model
`<PROVIDER>/<MODEL>`. Use supplied captures; no browser or build is needed.

Inspect every named screen family. Sample portrait/landscape phone, desktop,
supported seat counts, directions, locales and each shipped theme. Open the
full-resolution PNG for dense or doubtful states. Report missing coverage
instead of inferring that uncaptured states are fine.

Look for cut-off/overlapping text; numbers or state a player cannot interpret;
unclear next actions; direction/translation problems; inconsistent controls;
crowded many-seat boards; incorrect art; hidden information leaks; symbols
that rely on hue; unreadable tooltip/card-sheet content or blocked controls.
Inspect from a player's perspective, not just as a collection of boxes.

Every finding: severity P0 (cannot play/leaks hidden facts), P1 (misleads or
blocks real play), P2 (noticeably rough), P3 (small polish); screen, state,
viewport, seats, direction, locale, theme, exact PNG path; what is wrong, why
it matters and a concrete suggested fix. Skip these assigned overlaps:
`<OTHER_WORK_OWNERSHIP>`. Do not pad good screens with praise or stop after a
fixed finding count. Keep all real issues but separate polish from playability.

Write `<REPORT_PATH>`, first line counts per severity, then coverage and
findings. Notify `<COORDINATOR_ID>` through the brief's authorized report-back
channel, then stop. The coordinator ends the loop when only small issues
remain that do not affect real play.
