# Project setup and the working agreement

Set up the agreement, the commands and the privacy boundary before the first feature. The cheapest
moment to fix a workflow is before any worker has copied it.

Day-one checklist:

- `AGENTS.md` from `templates/AGENTS.md.template`, read fully by every worker.
- A short README (what the game is, how to try it) linking to `docs/README.md`, an index of the
  focused guides: architecture, protocol, rules, testing, self-hosting, art, legal, decisions,
  roadmap.
- A decisions file with numbered entries; later decisions name what they supersede.
- The run directory outside the repository, with `AUTHORITY.md` listing the owner's standing
  grants and refusals ([orchestration.md](orchestration.md)), and the task checklist gitignored.
- Toolchain pins in the `Makefile`, CI and the deploy script, changed together.
- The guard and its `make` targets, so no worker runs a raw heavy command.
- Conventions turned into checks from the start: engine import guard, translation coverage,
  generated-file freshness, forbidden UI patterns (native `title`, physical CSS properties, raw
  colours).

## Lessons

Each lesson is a rule and its reason. The label says how strong the evidence was: *seen once* (one concrete finding), *seen repeatedly* (recurring failures or independent checks across subsystems), or *owner decision* (an accepted preference, which a new owner may change).

- **1.01** Establish the working agreement before implementation: architecture boundaries, commands, ownership, privacy, verification and completion rules. Putting these in one entry document prevents each worker from inventing a different workflow. *(seen repeatedly)*

- **1.02** Make the first milestone a runnable vertical skeleton with health, a client shell, a browser smoke test and CI. This exposes deployment and toolchain failures before they are buried beneath game logic. *(seen repeatedly)*

- **1.03** Plan end to end, then execute routine choices within the agreed scope without repeatedly asking which next task to run. Escalate genuine product decisions and authority boundaries, because autonomy is useful only within a clear mandate. *(owner decision)*

- **1.04** Name milestones and slices by their outcome, using one consistent scheme. Reports full of opaque short codes make coordination harder as the project grows. *(seen repeatedly)*

- **1.05** Keep the README short enough to explain the product and a first run, then link to focused technical guides. A navigable documentation index prevents architecture and operations knowledge from becoming transcript archaeology. *(seen repeatedly)*

- **1.06** Pin the language, package manager and compiler versions used locally, in CI and in deployment. A newer compiler or unsupported frontend type checker can change behavior even when application code is unchanged. *(seen repeatedly)*

- **1.07** Expose supported verification through a small command interface, including targeted package and test filters. Workers should not need to reconstruct the environment or bypass resource controls to run a focused check. *(seen repeatedly)*

- **1.08** Turn critical conventions into checks, including engine import restrictions, translation coverage, generated-file freshness and forbidden UI patterns. Prose alone did not reliably prevent violations across many workers. *(seen repeatedly)*

- **1.09** Keep generated outputs under one reproducible generator and require a clean regeneration check. Editing the generated language binding directly only hides disagreement with its source. *(seen repeatedly)*

- **1.10** Finish the agreed playable scope before pursuing infrastructure tangents, expansions or optional advice features. Record useful ideas in a deferred list so declining the tangent does not lose it. *(owner decision)*

- **1.11** Separate public development documentation from private operational state at project creation. Retrofitting privacy after transcripts and machine configuration enter git is substantially harder. *(seen repeatedly)*

- **1.12** Choose visual defaults deliberately rather than automatically offering every theme and setting. Each supported variant adds design and review work, so a generic workflow should not inherit an older project's variant count. *(owner decision)*
