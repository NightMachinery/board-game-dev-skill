# Milestones

A sequence that worked for a first game, with each milestone's usual slices and its acceptance.
Each milestone ends green (its acceptance passes), committed and pushed. The roadmap file in the
repository changes only when a milestone ends; day-to-day progress lives in the run directory.

Standing gates for every milestone: the quick verification target is green, no headless browser is
left running, and the docs describe what was built.

## Naming

- A milestone is `M0`, `M1` and so on. Its first mention in any report also gives its title, such
  as "M9 (game feel, tutorial and polish)".
- A slice id is the milestone plus two or three plain kebab-case words naming its outcome:
  `M3.room-actor`, `M9.tooltip-coverage`. A recurring kind takes a number: `M9.hints-followups-2`.
- The slice id goes in the commit subject (`server: room actor and mailbox (M3.room-actor)`), in a
  `Slice:` line of the commit body, in the branch name (`slice/room-actor`) and in the worktree
  directory.
- Slices launched together form a wave, named by its theme on first mention.

## The sequence

The order is playable first. Right after the engine core comes one game that a person can play
end to end through the real server and client. Modules, the full catalogue, bots and the platform
then grow from that game, and each is done when a player can reach it. A first game built in the
older order (engine, bots, server, then client) had every module, its measuring bots and most of
its art before anyone could play it, and still had to reorder its plan to get there.

1. **M0: bootstrap.** The working agreement, the guard, toolchain pins, CI, the server with
   `/health`, the client shell, one WebSocket room, a browser smoke test and self-hosting at the
   real URL. Acceptance: a fresh clone runs the quick gate and the smoke test, and the URL serves.
2. **M1: rules and data.** The rules reference in original wording, the edition and scope, the
   glossary, the rulings file, and the data for the first playable card, reconciled and verified.
   The rest of a large catalogue continues in mechanic groups beside later milestones
   ([rules-capture.md](rules-capture.md)). Acceptance: every disagreement found so far has a
   ruling, every rule clause has a planned test, and the first card is verified.
3. **M2: engine core.** The base rules without optional modules, one rule area per slice, tests
   first from the rules reference; the generator and setup; legal moves and apply; scoring and
   endings; the per-viewer view; seeded playouts with invariants after every move; fuzzing.
   Acceptance: long playouts are clean, the privacy property tests pass, and the purity guard has
   a negative test.
4. **M3: first playable.** The core rules on one verified card, hot-seat on one device, through
   the real room actor, a durable record, the transport with generated types and the phone
   client, served by `self_host.py`. Admission is a table from the first card: scenario or card
   id, pinned content hash and required capabilities, read by every mode. The second card is then
   a row and a test, not a new service, endpoint or storage namespace. Acceptance: the committed
   game driver ([testing.md](testing.md)) plays it to a terminal outcome at phone and desktop
   size, CI runs that game, and the owner can play it at the URL.
5. **M4: modules and catalogue.** Each optional module or rules area is a vertical slice: engine
   clauses with their tests, the view fields, the client display, and admission of one card that
   uses it. Engine clauses for several modules may run in parallel waves; their wire changes go
   through the single writer. The catalogue is admitted in mechanic groups. Acceptance: every
   module clause has its pinned test, playouts with every module on are clean, every shipped card
   loads and is admitted, and the driver plays one representative card per mechanic group.
6. **M5: bots.** Random and greedy baselines, the observation contract, a simulator and measured
   strength, then versus-a-bot play if it is in scope. Bots that only measure balance can wait
   until later. Acceptance: the stronger bot beats the baseline with a stated margin and
   uncertainty, and the driver plays a versus-bot game.
7. **M6: online and the platform.** Identity, reconnect, rematch, input bounds and rate limits,
   versioned records, the lobby, roles, spectators and device migration. Acceptance: recorded
   frames type-check against the generated types, crash tests around the durable write pass, and
   the driver plays full games in each mode.
8. **M7: deploy.** Production hosting, the health check with build version, the production smoke
   suite, backups and rollback. Acceptance: a redeploy round trip with the smoke suite green.
9. **M8: art.** The theme chosen at kickoff, the manifest and subjects, a pilot through the whole
   pipeline, then production one asset at a time with review. The pilot can start right after M1,
   in its own lane beside the build. Acceptance: every manifest entry is approved or has a recorded
   placeholder decision, within the byte budgets.
10. **M9: game feel and polish (build).** Animations driven by server events and the game's own
    Animation setting, sound, the tutorial (a guided first game), tooltips on every element, the
    rules reference in the app, a move summary, the queued UX fixes, a deeper rules audit and
    hardening. Acceptance: with Animation off nothing animates and every change stays visible; a
    fresh agent completes the tutorial from the UI alone; every element has a tooltip.
11. **M10: the review loop.** Rounds of scripted probes, a player reviewer playing real games at
    phone and desktop size, and a screens reviewer reading the screenshot matrix. Each fix is its
    own slice with before and after shots. Acceptance: a round finds only small issues and no open
    blocker or major finding (severity scale in [orchestration.md](orchestration.md));
    accessibility and performance budgets pass. This is version 1.

## Later games on the same platform

A second game is designed in its own milestone, then reuses the proven infrastructure (rooms,
storage, identity, the guard, the art pipeline) while keeping its rules, catalog, actor and frames
separate. Add a milestone for shared layers that extracts infrastructure with the first game's
behaviour unchanged, proven by its existing tests, before the second engine starts.

## What to defer

Keep a deferred list in the roadmap. Expansions, optional advice features, strong bot levels and
infrastructure tangents wait until the agreed playable scope is finished. Recording an idea there
is how a tangent gets declined without being lost.
