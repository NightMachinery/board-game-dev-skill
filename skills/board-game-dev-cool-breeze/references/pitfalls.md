# Mistakes that cost the most time

Each entry is a failure that cost hours or days, and the rule that prevents it. Read this list
before the first worker launches and again before the first release.

## Lessons

Each lesson is a rule and its reason. The label says how strong the evidence was: *seen once* (one concrete finding), *seen repeatedly* (recurring failures or independent checks across subsystems), or *owner decision* (an accepted preference, which a new owner may change).

- **12.01** Unbounded concurrent builds caused machine thrashing and stalled agents. Prevent recurrence with a shared pressure-aware admission guard and a deliberately small active fleet. *(seen repeatedly)*

- **12.02** Agent polling of locks and long jobs consumed repeated full-context turns. Prevent recurrence by arming completion notifications at launch and yielding the agent until a real event arrives. *(seen repeatedly)*

- **12.03** Results disappeared when notifications targeted a former coordinator or ran from a deleted worktree. Prevent recurrence with stable notifier directories, explicit report routing, durable failure alerts and a fallback to the live parent. *(seen repeatedly)*

- **12.04** Re-reviewing low-risk work repeatedly cost time while finding little new. Prevent recurrence with risk tiers and a targeted second review only for a genuine blocker fix. *(seen repeatedly)*

- **12.05** Integration checks passed locally but omitted affected tutorial and review specs. Prevent recurrence by deriving the test list from DOM contracts and retaining the standing cross-cutting web suite. *(seen repeatedly)*

- **12.06** A spec passed alone and failed when earlier tests consumed a global deal counter. Prevent recurrence by controlling setup explicitly or making the policy robust across deals, then running it beside neighboring specs. *(seen once)*

- **12.07** A tiny frontend change increased another game's cold transfer through shared runtime chunk changes. Prevent recurrence with paired entry-path measurements, lazy helper isolation and a cumulative baseline budget. *(seen repeatedly)*

- **12.08** Game discovery briefly joined as a player, causing presence flashes and lost bot presentation events before the real session mounted. Prevent recurrence by preserving the existing direct path or explicitly handing over one live connection with its events and authority intact. *(seen once)*

- **12.09** Recreated sessions reset request counters while keeping the old client identifier, and retries could target a different seat. Prevent recurrence by aligning identifier lifetimes and binding pending intent to its original viewer and seat. *(seen once)*

- **12.10** Stricter security limits and hashed client keys broke valid old records or forgot sequence barriers. Prevent recurrence by deciding per change whether old records stay playable (architecture 2.26): when they do, test the migration against records written by the earlier version, including values above new defaults; when they do not, refuse them cleanly and leave their bytes untouched. *(seen repeatedly)*

- **12.11** Store size checks covered ordinary writes but missed load-time hash and archive rewrites. Prevent recurrence by enforcing the write/read cap at the final shared write boundary and testing every rewriting path. *(seen once)*

- **12.12** Stronger default bots made correctness suites much slower and threatened CI timeouts. Prevent recurrence by measuring the actual CI-shaped workload against baseline and moving full strength measurements behind explicit gates. *(seen repeatedly)*

- **12.13** A frozen preset lacked tests pinning actual choices, so later evaluator edits could silently change stored games. Prevent recurrence with decision goldens, exact work counters and supported policy-version mappings. *(seen once)*

- **12.14** Nearly instantaneous CSS transitions made a same-task geometry read observe the old box. Prevent recurrence by disabling transitions on measurement-sensitive elements or measuring after the relevant frame settles. *(seen once)*

- **12.15** Component-local cascade layers were registered before root layers and lost unexpectedly to reset styles. Prevent recurrence by declaring shared layer order and layered defaults centrally, then checking actual computed rendering. *(seen once)*

- **12.16** Scripts killed processes by broad command patterns and disrupted other workers. Prevent recurrence by recording task-owned process identities, terminating by PID and checking for surviving children. *(seen repeatedly)*

- **12.17** Rebuilding separately for multiple hosts allowed source changes to split the release, and proxy or TLS differences obscured the real health-check failure. Prevent recurrence with one fixed artifact and explicit bounded probes from known network vantage points. *(seen repeatedly)*

- **12.18** Temporary code and capture directories grew or interfered with formatting gates despite being ignored by git. Prevent recurrence by keeping scratch sources outside checkouts and assigning artifact retention through a central ledger. *(seen repeatedly)*

- **12.19** Dense phone layouts passed common viewport checks but failed during real play at short heights and hid useful tooltips. Prevent recurrence with reduced-height playtests, persistent essential status and ordinary detail views for touch-only explanations. *(seen repeatedly)*

- **12.20** Long runs confused owner instructions, coordinator assignments, old defaults and proposed measurements. Prevent recurrence by preserving source attribution, recording explicit supersession, and labeling plans, accepted exceptions and measured evidence separately. *(seen repeatedly)*
