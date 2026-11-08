# Thin-client helpers

Copy `src/lib/` into a Svelte 5 application. Mount `ui/TooltipLayer.svelte`
once in the root layout, after the page content. Register text with
`{@attach tooltip({ text: translatedText })}` from `ui/tooltip.svelte.ts`.
Give icon-only controls an accessible name as well. All visible text and the
required `rulesLabel` come from the app's translations. A `rulesId` draws that
link and calls `openRules(id)` after closing the tooltip; `onrules` can override
the integration.

The helper owns one tooltip, picks the innermost registered element, delays
fine-pointer hover, shows keyboard focus, and closes on Escape. Touch taps
show passive elements' tips. Actionable elements retain tap actions and use
long-press for tips; release after a long-press never acts. A tap closing an
open tip is swallowed, including the generated click. Only the optional
rules link acts inside the bubble. Tooltips are manual popovers so they can
appear above modal dialogs. Keep the gesture cleanup returned by the layer.
`stack: [{caption, render}]` adds caller-rendered real previews in a joined
second panel, at most two. It sits beside on wide screens and on the bubble's
far side on phones. No nested stack is possible: anchors inside the tooltip
layer never register as targets. Keep previews noninteractive; only the rules
link receives the pointer, with hover intent to cross to it and a touch exception
that lets the link act. `tooltip-place` contains tested viewport placement; set tooltip CSS variables
from the chosen theme. Add safe-area padding for edge-to-edge device shells.

`session/socket-url.ts` derives ws/wss from `location`; use it when constructing
the one application WebSocket. `ui/clipboard.ts` returns a success boolean and
uses the legacy copy selection on plain HTTP. On failure offer selectable
text. Call it directly from the user's click/tap, never from a timer.

`session/identity.ts` keeps a random 128-bit token and cleaned display name in
localStorage, with a fresh per-page client id. Change `STORAGE_PREFIX` to the
same name as `tools/project.json`. Call `loadIdentity` once per page after
mounting, then keep it in memory; blocked storage only lasts for that page.
Treat tokens as credentials: never log them or put them in a URL. The server
still validates names and authenticates the WebSocket; this helper grants
no authority to a client-supplied user or seat id. `getRandomValues` works on
HTTP; do not replace it with `Math.random` or require `randomUUID`.

`theme.ts` applies one flattened art index and its explicit light/dark mode.
Only load the chosen index, then fetch the asset URLs it contains; a `null`
entry means a procedural placeholder. Do not preload unrelated theme packs
or bind mode to an OS media query. A dark theme is a separate explicit choice.

Tests use Vitest and the project's normal TypeScript/Svelte check. Copy the
tests too and add `vitest run` to verify-quick. Tooltip gestures/placement,
identity, same-origin WebSocket and native-title lint run without a browser.
Also run a real browser check for mouse/focus/Escape, passive touch, actionable
tap, long-press and swallowed closing taps after adoption. Unit tests do not
prove browser event ordering or popover layering on supported devices.

Mount `rules/RulesOverlay.svelte` once in the layout, with the current
`pathname`, translator `t`, and optional real-component diagram snippets by
section id. Call `openRules(sectionId?)` from the game menu or tooltips. Desktop
uses a nonmodal side drawer, keeping the board live; phone uses a tall modal
bottom sheet. Escape closes it, and a pathname change closes stale overlays.
Copy `routes/rules/+page.svelte` and replace its translator adapter. The page
and overlay share `RulesContent`, diagrams and stable `sections.ts` ids. Fill
all translation keys with the complete rules in your own words before release;
the skeleton has no game rules of its own. Link `/rules` from Home, and the
overlay from the game menu. Keep released ids stable for tooltip/deep links.
