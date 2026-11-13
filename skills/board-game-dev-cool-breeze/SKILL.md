---
name: board-game-dev-cool-breeze
description: Build an online multiplayer board game from scratch with a team of coding agents, end to end - rules capture, a server-authoritative deterministic engine (Go by default), a thin SvelteKit client that works on phones, rooms over WebSocket with token identity, moderators and spectators, bots, an art pipeline with inheritable light or dark themes, screenshot and playthrough review, and self-hosting with Caddy and tmux. Use when asked to start, plan, or run development of a digital board or card game for the browser, or to bring an existing one up to these practices.
---

# Board game development, cool-breeze edition

You coordinate the development of an online board game: one coordinator (you), a small fleet of
worker agents, and the owner (the user), who makes product decisions. This skill is the working
method distilled from building a complete two-game platform with agents. It has three parts:

- this file: the phases, the defaults and the rules that matter most;
- [references/](references/): one page per topic, each with the reasoning and the numbered lessons
  behind it;
- [templates/](templates/): tools a new game copies on day one (the heavy-job guard, the headless
  browser tools, the art pipeline, `self_host.py`, an `AGENTS.md` and `Makefile` skeleton, worker
  brief templates and the client helpers). Each template has its own README.
- [themes/](themes/): reusable art directions with their colour tokens. See
  [references/themes.md](references/themes.md).

Treat everything here as a **default with a seam**: the stack, the owner requirements, the review
tiers and the deployment rules are what worked, and each can be overridden by the owner. When the
owner overrides one, record it in the project's decisions file and follow the override.

## The terms used throughout

- **Owner**: the human who commissions the game. Their words are the only source of authority.
- **Coordinator**: the agent that plans, briefs workers, integrates their branches and reports. It
  owns the shared files and the public account of progress.
- **Worker**: an agent given one bounded slice through a written brief.
- **Slice**: one cohesive change with an outcome name, such as `M4.trade-costs`. A **milestone**
  (`M4`) is a group of slices with an acceptance paragraph. Names describe the outcome in plain
  words; never letter-and-number codes such as `S5a`.
- **Run directory**: private state outside the repository (owner instructions verbatim, current
  state, notes, the artifact ledger, briefs, results, logs and screenshots). The repository is
  usually public; the run directory never is.
- **Action key**: a canonical string naming one legal move, such as `build:temple` or `pass`. The
  server offers keys; the client sends one back.
- **View**: the per-viewer, redacted snapshot the server sends after every accepted action. It
  includes the legal `choices` with their costs and explanations.
- **Guard**: the machine-wide admission control for heavy commands (`templates/tools/heavy.py`).

## Phase 0: kickoff with the owner

Do these with the owner before any code. Explain each choice with its tradeoffs first, then ask.

1. **The game and its legal footing.** Read [references/legal-ip.md](references/legal-ip.md). You
   may implement a game's mechanics in original code, with original art, original rules wording
   and an original name and look. You do not reproduce another game's name, art, card frames,
   iconography, logo, rulebook text or trade dress. When the owner names a published game, say
   plainly what you can build (an original game with similar mechanics, or a licensed or
   public-domain one) and agree the new game's own name and identity. Record the decision.
2. **Scope.** The exact rules edition or design, the supported player counts, the modes (versus a
   bot, hot-seat on one device, online between devices), expansions in or out, and what is
   deliberately deferred.
3. **Default requirements.** Walk through [references/requirements.md](references/requirements.md)
   (identity, device migration, roles, spectators, self-hosting, intranet use, tooltips, phone
   first) and ask which, if any, the owner wants changed.
4. **Art direction.** Propose three to five distinct themes for the game: always offer the bundled
   themes that fit, plus fresh ones drawn from the game's setting. For each, give its mood, palette,
   idiom, whether it is light or dark, how it reads at thumbnail size on a phone, and what it costs
   to produce. The owner picks one to start with. A game launches with **one** theme; more themes,
   including a dark one, come later through inheritance. See
   [references/themes.md](references/themes.md).
5. **Operations.** Where it will be hosted and under which URL, the work window (continuous, a
   nightly window such as 00:00-10:00, or paused), which agent providers and accounts may be used,
   and whether the agent may deploy on its own judgement.

Create the run directory before the first question, and record every owner message verbatim in
its `USER-VERBATIM.md` before acting on it. Settled answers go into the repository's decisions file,
`docs/dev/decisions.md` (numbered entries; a later one names what it supersedes). Rulings on
ambiguous game rules have their own file, `docs/rules/decisions.md`.

## Phase 1: bootstrap

The templates are tools, not a game scaffold: the Go module, the SvelteKit app, the root package
and lockfile, CI and the end-to-end suite are yours to create. `templates/README.md` lists the
adoption order. In short:

1. Create the repository and the run directory (`USER-VERBATIM.md`, `STATE.md`, `NOTES.md`,
   `STORAGE.md`, `briefs/`, `results/`, `logs/`). Gitignore the task checklist and local state from
   the first commit ([references/project-setup.md](references/project-setup.md)).
2. Copy the templates and fill `tools/project.json`: project name, run directory, ports, theme,
   art kinds, hosting. Copy the chosen theme and every theme it inherits from into `themes/`.
3. Create the Go module and the SvelteKit app, the root package with its lockfile, and CI, so
   `make verify-quick` (the **acceptance gate** every slice must pass) runs green on an empty game.
4. Write `AGENTS.md` from `templates/AGENTS.md.template`: the architecture paragraph, where things
   live, the guard, browsers, processes, engine purity, client rules, assets, documentation,
   privacy, commits, owner phrases, and the **single-writer list** (lockfiles, the Makefile,
   generated code, the protocol document and the frozen core types such as the engine's state,
   action and event types, by path). Every worker reads it first.
5. Pin each toolchain (Go, Node, pnpm) once, and make every other place that needs the version
   (CI, the deploy script) read it or be checked against it.
6. Milestone 0 is a **vertical skeleton**: the server with `/health`, the client shell, one room
   over WebSocket, a browser smoke test, CI, and `self_host.py setup` serving it at the real URL.
   Toolchain and deployment problems surface here, before game logic buries them.

## The default stack and its seams

- **Server: Go**, holding the only rules engine. The engine is pure (standard library plus an
  allow-list, enforced by an import test and the linter), integer-only, map-free in rules logic,
  and deterministic: all chance is drawn from the seed when the game is created, so a game is its
  seed, options and accepted action keys.
- **Rooms**: one actor goroutine per room serializes every mutation. Local, bot and online play are
  the same room with different seat controllers.
- **Client: SvelteKit with Svelte 5 runes and Tailwind**, mobile-first. It renders views and sends
  action keys; it never computes legality or cost. Wire types are generated from the server's DTOs.
- **Storage**: the seed, options and keys, written durably before a move is acknowledged, with
  versioned records. Keeping old games playable across a format change is optional by default:
  most stored games go stale, so a change may bump the version and refuse older games instead of
  carrying parallel formats. Their bytes are kept, never deleted or rewritten, unless the owner
  has said that data is disposable; see [references/architecture.md](references/architecture.md).
- **Hosting**: one Go binary that embeds or sits behind the static build, Caddy in front, tmux for
  processes, no Docker.

Seams: another backend language is fine when the owner asks, but any new backend service defaults
to Go. A two-player game may freeze its moderators at Start and skip live moderation during play
([references/requirements.md](references/requirements.md), "Two-player games may simplify"). Read [references/architecture.md](references/architecture.md) before designing the engine
and protocol, and [references/platform.md](references/platform.md) before rooms, identity and
roles.

## Phases 2 to 6: the build

Run these as milestones. [references/milestones.md](references/milestones.md) has the execution
order, each milestone's acceptance and the slices that usually belong to it. The order is
playable first: right after the engine core comes one game a person can play end to end, and
modules, the catalogue, bots and the full platform grow from it. The list below is grouped by
theme, not by order.

- **Rules capture** ([references/rules-capture.md](references/rules-capture.md)): a complete rules
  reference in your own words, independent data tables reconciled field by field, and a rulings
  file for every disagreement, before the first rules slice. A large catalogue of cards or
  scenarios is verified in groups by the mechanics it uses, with one shared automated check.
- **Engine** (tests first, one rule area per slice), then **rooms and the platform** (identity,
  lobby, roles, spectators, reconnect, rematch), then the **client** on a phone
  ([references/phone-ui.md](references/phone-ui.md)).
- **Bots** ([references/bots.md](references/bots.md)): random and greedy baselines first, honest
  observations only, measured strength before any named difficulty ships.
- **Art and sound** ([references/art-and-sound.md](references/art-and-sound.md)): a pilot through
  the whole pipeline before bulk production; vectors drawn by a strong model in a render, look,
  correct loop, bitmaps generated one at a time; approved originals committed losslessly; shipped
  files derived and content-hashed.
- **Polish before review**: animations, sound, the tutorial and explanatory UI are built before the
  main review loop, so reviewers do not rediscover planned gaps. Two of these are must-haves, not
  optional polish: the custom, stacked tooltips on every element, and the in-app rules reference
  (a drawer or sheet over the live board, and `/rules`), which tooltips link into.
- **Review loop**: screenshot matrices from named states across sizes and directions, scripted
  probes for overflow, contrast, targets and occlusion, and real games played by a reviewer agent.
  Stop when no critical gameplay issue remains and new findings are small.

## Testing, in one paragraph

Test each property at the cheapest layer that can prove it: pure rules, the room actor's
contracts, the real transport, client plumbing, then full browser games driven by the server's
offered keys through real controls. Check invariants after every transition in seeded playouts,
fuzz legal and malformed input, prove privacy by varying hidden state and comparing views, and
keep expensive strength or performance runs opt-in. The details and the reasons are in
[references/testing.md](references/testing.md).

## Running a fleet of agents

Read [references/orchestration.md](references/orchestration.md) before launching the first worker.
The rules that cost the most to learn:

- **One coordinator** owns the plan, integration, the single-writer files (lockfiles, the Makefile,
  generated code, the protocol and frozen core types) and the progress report. Workers request
  changes to those in their results.
- **Every brief is self-contained**: objective, base commit, owned paths, read paths, exact checks,
  an observable stop condition and the result path. Use `templates/briefs/`.
- **Integrate one branch at a time**: rebase onto the mainline, run the acceptance gate, then
  fast-forward. Commit with explicit pathspecs and inspect the commit afterwards, because another
  session may share the index.
- **Review by risk.** A full independent review from a different model family for rules, storage,
  protocol, security, deployment and anything a weaker model wrote; one light review for ordinary
  UI; the coordinator's own inspection plus the checks for low-risk chores. Re-review only fixes
  of real blockers.
- **Route by difficulty.** Cheaper capable models do mechanical slices; the strongest model does
  rules design, hard reviews and vector art. Bitmap generation goes one at a time through one lane.
- **Heavy commands go through the guard**, one at a time per worker. It enforces the memory budget,
  the run mode (continuous, a nightly window, or paused) and a single headless browser.
- **Never poll with model turns.** Launch long jobs detached with a completion notification and end
  the turn. Arm the notification at launch. Without an agent host that delivers messages, use the
  harness's own tracked background task, or a small watcher script whose exit is the event.
- **Keep state durable**: owner words verbatim, the owner's standing grants and refusals with
  their sources (`AUTHORITY.md`), current state newest first, curated learnings, the task
  checklist, the artifact ledger and one result file per assignment. Checkpoint before quota
  exhaustion, compaction or handoff.
- **Scope blockers to their dependencies.** A permission question, failed check or incident blocks
  the affected actions, not every task in the project. Contain active harm first, then continue
  independent authorized work. Before reporting idle, identify the next useful task or explain why
  each remaining task is actually blocked; see the blocked-work procedure in orchestration.
- **Carry authority forward.** Do not ask again for an approved design, account or deployment
  within its agreed scope. Prepare and verify the concrete action before seeking genuinely missing
  approval. A recovery heartbeat reconciles work and advances the backlog; it never repeats an
  unchanged status. When every remaining task waits on the owner, ask once with the full question
  and let the reply resume the work.

If these skills are installed, use them rather than reinventing their mechanisms:
`event-driven-agents` (completion notifications), `long-run-handoff` (state that survives
compaction), `quota-management` (headroom across accounts), `delegate` (choosing model, account
and backend) and `paseo` (agent hosting). Without them, follow the rules above directly and say
which skill was unavailable.

## Deployment

Read [references/deployment.md](references/deployment.md) and adopt
`templates/self_host.py`, which runs on the serving host. Defaults:
`setup|redeploy|start|stop|dev-start|status`, with `setup` and `redeploy` building before they
stop the old server, no extra static file server (Caddy serves the build, or the Go server embeds
it, by your judgement), blocks in `~/Caddyfile` with an explicit redirect between schemes, uncommon
ports that are scanned and persisted, tmux sessions with `-e` for environment, proxy variables
passed through when present but never hardcoded, everything self-hosted so the game runs on an
intranet over plain HTTP, and a content hash in every changing asset URL.

Private defaults come from the environment, never from the repository: `BGD_DEFAULT_DOMAIN` gives
the default URL `https://<game>.<domain>` (`BGD_DEFAULT_HOST` overrides the `<game>` label), and
`BGD_DEPLOY_HOST` names the machine production runs on, reached over ssh, where `self_host.py` runs.
When a variable is unset, ask the owner. Unless the owner says otherwise:

- on a local machine, develop with `dev-start`, not `start`;
- after finishing and committing, run `self_host.py redeploy` in the tmux session
  `<repo-name>-setup` and wait 120 seconds before reading its log;
- once the owner has granted deployment authority, redeploy production after each committed,
  verified change that affects the running game, then check `/health` for the expected build and run
  the production smoke suite. Keep unreleased features behind their own creation flags.

## Privacy in a public repository

Commit no personal information: no home-directory paths, email addresses, hostnames, domains,
usernames, agent or account ids, quota or billing figures, or credentials. Hosting targets and
remembered flags live in gitignored or external config. Scan every push for these patterns and read
each hit in context. Never publish a third party's identifying details without the owner's consent.

## Where this method does not fit unchanged

The evidence comes from finite, turn-based games with hidden hands and simultaneous drafting.
Cooperative games with communication limits, real-time play, secret objectives and true offline
play need their own information and interaction contracts. Check moderator visibility, undo,
end-of-game reveal, memory aids, bot access and hint defaults against the new game's rules rather
than inheriting them.
