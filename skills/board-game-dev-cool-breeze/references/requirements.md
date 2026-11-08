# Default requirements

These are the platform requirements a new game gets unless the owner changes them at kickoff. They
come from an owner who plays casually with friends, often on phones, sometimes on a network
without access to the wider internet. Present them at kickoff as a list, ask which to change, and
record the answer.

## Identity without accounts

- **Token identity.** The client generates a random token on first visit and keeps it in
  `localStorage`. The server derives its identifiers from the token with a secret-keyed function,
  and the token never appears in a URL or a log.
- **Saved display name.** The display name belongs to the token and is saved, so a returning
  player is not asked again.
- **Device migration.** A "migrate device" button copies a link carrying a **room-scoped claim**.
  Opening it on another device takes over this player's seat in that room, using the claim instead
  of the new device's own token. The claim reveals nothing about the global token and works only in
  its room. The claim stays in the link (in the URL fragment), so the link can be refreshed, and a
  revoke action invalidates it and detaches sessions that used it.
- **Moderators copy any player's link.** A compact, icon-only button (an SVG icon with a tooltip)
  lets a moderator copy any player's migration link, for a friend who lost their device.
- **Duplicate names.** Equal display names get a stable number suffix, scoped to the room. The
  numbers never change when someone leaves.
- **Self is visible.** The viewer's own name and seat are styled differently, with shape or text as
  well as colour, so players always know which one is them.

## Roles in a room

- **Creator.** The room's creator is its owner, permanently. The role never transfers.
- **Moderators.** The creator promotes and demotes moderators. A moderator can promote others but
  can demote only those they promoted themselves.
- **Temporary moderators.** When no moderator has been online for 5 minutes, a present player is
  promoted to temporary moderator, at random the first time. A temporary moderator has full
  moderator powers and loses them as soon as a real moderator comes back online. The temporary
  designation is remembered: the next time no moderator is online, a previous temporary moderator
  who is present is chosen again instead of a random player. Anyone a temporary moderator promotes
  is also temporary.
- **Observers.** A moderator can move a player to the observers and back. A player moved to the
  observers can rejoin by themselves. Observers are a real viewer role with their own redacted
  view; watching never claims a seat or shows private offers.

Recheck time-dependent authority when an action arrives, and fail closed while its durable state is
uncertain.

## Phone first

- The game is designed on a phone in portrait first, then rearranged for landscape and desktop.
  It is played at short heights too (a phone in landscape, split screen).
- The board never scrolls horizontally, and the current required action and each player's
  essential status stay visible.
- Install-to-home-screen and fullscreen controls are offered where the browser supports them.

## Tooltips on everything

Every element gets a tooltip, down to the smallest meaningful atom: a symbol, a chip, a pip or a
glyph on a card or board. The text is short and clear and may include a small vector diagram whose
labels are translatable text. The project's own tooltip helper is used, never the browser's native
`title`:

- a fine pointer shows it on hover after a short delay and on keyboard focus; Escape closes it;
- on touch, a tap shows it on an element with no action; an actionable element keeps its tap action
  and shows the tooltip on a long-press, and releasing the long-press never triggers the action;
- any tap closes an open tooltip and is swallowed, so it never acts on what lies beneath;
- one tooltip at a time, the innermost one under the pointer or finger.

- **Stacked tooltips.** A tooltip can carry a stack: a second panel joined to the bubble that
  previews the things the tooltip refers to, drawn as the real components (the card a symbol makes
  free, the token a chip stands for). It sits beside the bubble on wide screens and on its far side
  on phones, holds at most two items, and has no stack of its own, so a tooltip is never more than
  two levels deep.
- **A link into the rules.** A tooltip whose topic has a section in the rules reference shows a
  "More in Rules" link that opens the rules at that section and closes the tooltip. Only the link
  takes the pointer; the bubble lets board clicks pass. Hover intent gives a moving pointer time
  to reach the link. On touch, the link is the one tap inside a tooltip that acts.

A lint test fails on any native `title=`. `templates/web/` has the helper. The custom, stacked
tooltips are a must-have, not a polish item.

## The rules reference in the app

A must-have. The complete rules, in the game's own words, built from the real components and the
tooltips' concept diagrams, so the pictures in the rules are the pieces on the board:

- in a game, a side drawer on desktop that leaves the board visible and live, and a tall bottom
  sheet on phones, opened from the game menu;
- the same content as a page at `/rules`, reachable from Home;
- sections with stable ids, which tooltips link to;
- every word through the translation tables, like the rest of the client.

## One look per game

A game launches with one deliberately chosen theme, light or dark, picked with the owner at
kickoff. Further themes (a dark variant, a seasonal look, a parody) are added later through theme
inheritance, never as an automatic light and dark pair. See [themes.md](themes.md).

## Self-hosting and intranet use

- `self_host.py setup|redeploy|start|stop|dev-start|status`, documented in `docs/self-hosting.md`.
  The URL is supplied by the user and defaults to `https://<short-name>.<default domain>`, with the
  default host and domain read from the environment.
- `setup` stops, sets up, then starts. `start`, `dev-start` and `redeploy` first stop both serving
  modes. Every command that starts serving prints the final URL.
- Caddy serves the static build itself; no extra static file server. An HTTPS site also gets an
  explicit HTTP-to-HTTPS redirect block; an HTTP site gets an HTTPS-to-HTTP redirect. The blocks
  live in `~/Caddyfile`.
- `dev-start` points the Caddy block at the dev server with hot reload, and `start` points it back.
  On macOS, `dev-start` listens on localhost, so the same code serves the domain on a server and
  localhost on a laptop.
- Uncommon default ports; scan for free ones when taken; persist the last used ports locally
  (gitignored); check the ports are free on the server too.
- Every component runs in tmux (kill the session, then `tmux new -d -s NAME`), with environment
  passed as `-e VAR=value`. No Docker. A backend that supports REPL-driven development runs its
  tmux session in REPL mode.
- Proxy variables (`ALL_PROXY`, `HTTP_PROXY`, `HTTPS_PROXY`, their lower-case forms and the npm
  ones) are passed through when present. They are never hardcoded and never required.
- pnpm with its lock file and its de-duplicating store, for poor networks and small disks.
- Everything the client needs is in the repository: fonts are self-hosted, nothing loads from a
  CDN, no captcha or third-party service. External services are replaced by a mature, lightweight
  local alternative.
- The game works on plain HTTP, including copying to the clipboard (a fallback for insecure
  contexts). WebSockets use `ws` or `wss` from the page's own scheme.
- The running server's URL is always determined at runtime, never hardcoded.

## When starting from someone else's code

- Point URLs at the new repository, remove the previous creators' names, donation links and any
  political or religious messaging that came with the code.
- If a submodule needs changes, vendor it into the main repository instead of forking it.
