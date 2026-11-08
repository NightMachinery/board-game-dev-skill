# Milestones

A sequence that worked for a first game, with each milestone's usual slices and its acceptance.
Each milestone ends green (its acceptance passes), committed and pushed. The roadmap file in the
repository changes only when a milestone ends; day-to-day progress lives in the run directory.

Standing gates for every milestone: the quick verification target is green, no headless browser is
left running, and the docs describe what was built.

## Naming

- A milestone is `M0`, `M1` and so on. Its first mention in any report also gives its title, such
  as "M10 (game feel, tutorial and polish)".
- A slice id is the milestone plus two or three plain kebab-case words naming its outcome:
  `M4.room-actor`, `M10.tooltip-coverage`. A recurring kind takes a number: `M10.hints-followups-2`.
- The slice id goes in the commit subject (`server: room actor and mailbox (M4.room-actor)`), in a
  `Slice:` line of the commit body, in the branch name (`slice/room-actor`) and in the worktree
  directory.
- Slices launched together form a wave, named by its theme on first mention.

## The sequence

1. **M0: bootstrap.** The working agreement, the guard, toolchain pins, CI, the server with
   `/health`, the client shell, one WebSocket room, a browser smoke test and self-hosting at the
   real URL. Acceptance: a fresh clone runs the quick gate and the smoke test, and the URL serves.
2. **M1: rules and data.** The rules reference in original wording, the edition and scope, the
   glossary, independent data tables reconciled against each other, and the rulings file.
   Acceptance: every disagreement has a ruling, and every rule clause has a planned test.
3. **M2: engine.** One rule area per slice, tests first from the rules reference; the generator and
   setup; legal moves and apply; scoring and endings; the per-viewer view; seeded playouts with
   invariants after every move; fuzzing. Acceptance: long playouts are clean, the privacy property
   tests pass, and the purity guard has a negative test.
4. **M3: bots.** Random and greedy baselines, the observation contract, a simulator, and measured
   strength. Acceptance: the stronger bot beats the baseline with a stated margin and uncertainty.
5. **M4: server.** The room actor, durable storage with versioned records, the protocol with
   generated client types, identity, reconnect, rematch, input bounds and rate limits. Acceptance:
   recorded frames type-check against the generated types, and crash tests around the durable
   write pass.
6. **M5: web core and hot-seat.** The phone-first board, choices with server costs, hot-seat play,
   i18n tables, logical CSS properties. Acceptance: a full hot-seat game in the browser at phone
   and desktop size.
7. **M6: versus a bot** and **M7: online**, with the lobby, roles, spectators and device migration.
   Acceptance: full games in each mode, driven by offered keys through real controls.
8. **M8: deploy.** Production hosting, the health check with build version, the production smoke
   suite, backups and rollback. Acceptance: a redeploy round trip with the smoke suite green.
9. **M9: art.** The theme chosen at kickoff, the manifest and subjects, a pilot through the whole
   pipeline, then production one asset at a time with review. Acceptance: every manifest entry is
   approved or has a recorded placeholder decision, within the byte budgets.
10. **M10: game feel and polish (build).** Animations driven by server events and the game's own
    Animation setting, sound, the tutorial (a guided first game), tooltips on every element, the
    rules reference in the app, a move summary, the queued UX fixes, a deeper rules audit and
    hardening. Acceptance: with Animation off nothing animates and every change stays visible; a
    fresh agent completes the tutorial from the UI alone; every element has a tooltip.
11. **M11: the review loop.** Rounds of scripted probes, a player reviewer playing real games at
    phone and desktop size, and a screens reviewer reading the screenshot matrix. Each fix is its
    own slice with before and after shots. Acceptance: a round finds only small issues and no open
    critical or high finding; accessibility and performance budgets pass. This is version 1.

## Later games on the same platform

A second game is designed in its own milestone, then reuses the proven infrastructure (rooms,
storage, identity, the guard, the art pipeline) while keeping its rules, catalog, actor and frames
separate. Add a milestone for shared layers that extracts infrastructure with the first game's
behaviour unchanged, proven by its existing tests, before the second engine starts.

## What to defer

Keep a deferred list in the roadmap. Expansions, optional advice features, strong bot levels and
infrastructure tangents wait until the agreed playable scope is finished. Recording an idea there
is how a tangent gets declined without being lost.
