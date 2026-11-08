# Orchestration with agents

One coordinator, a small fleet of workers in isolated worktrees, written briefs, result files,
integration one branch at a time, review sized by risk, and a guard that keeps the machine
responsive.

**The guard** (`templates/tools/heavy.py`) wraps every heavy command: builds, test suites, linters,
installs, browsers, image generation, fuzzing and benchmarks. It enforces a memory floor, the run
mode (continuous, a nightly window, or paused), one headless browser and one image job at a time,
and a fair first-in-first-out queue with coordinator-only priority. Exit code 75 means it refused.
Long jobs run detached and notify the agent that launched them, or its parent if that agent has
closed.

**Owner phrases** steer a long run: "switch to nightshift HH:MM-HH:MM", "switch to continuous",
"pause", "resume" and "status". Each is recorded verbatim, then acted on: set the guard's mode and
arm the start, last-call and wind-down jobs for the window, plus an hourly recovery ping.

**A brief** names: the objective; the base commit; owned paths (the only files the worker may
change); read paths; settled decisions; the exact checks to run; an observable stop condition; the
result file path and its format (first line DONE or PARTIAL, commits, checks with outcomes,
artifact paths, open issues); how to notify the coordinator. Templates are in `templates/briefs/`.

**Integration**: rebase the branch onto the mainline; scan its added lines for private information;
confirm it touched no single-writer file; run the acceptance gate on the rebased tree;
fast-forward; push; remove the worktree; watch CI.

## Lessons

Each lesson is a rule and its reason. The label says how strong the evidence was: *seen once* (one concrete finding), *seen repeatedly* (recurring failures or independent checks across subsystems), or *owner decision* (an accepted preference, which a new owner may change).

- **9.01** Give one coordinator responsibility for plan consistency, integration, shared files and the public account of progress. Independent workers accelerate bounded work only when someone owns the boundaries between them. *(seen repeatedly)*

- **9.02** Write each brief with objective, base, owned paths, read paths, exact checks, observable stop condition and result destination. An unattended worker needs enough context to finish without inventing product policy. *(seen repeatedly)*

- **9.03** Require result files with a clear status, commits, checks and outcomes, artifact paths and unresolved issues. A partial result must remain partial even if the worker spent substantial time on it. *(seen repeatedly)*

- **9.04** Make workers check existing slice commits and dirty owned files before restarting. Recovery should continue durable work rather than duplicate it after a quota reset or coordinator replacement. *(seen repeatedly)*

- **9.05** Assign one writer to lockfiles, build entry points, generators, protocol contracts and frozen core types. Other workers request changes through results, reducing shared-file conflicts and accidental contract drift. *(seen repeatedly)*

- **9.06** Use a bounded number of isolated worktrees for disjoint slices and install dependencies from the shared locked store. Isolation reduces file collisions but does not create additional RAM or browser capacity. *(seen repeatedly)*

- **9.07** Integrate one branch at a time by rebasing onto the current mainline, running the acceptance gate, then fast-forwarding. Checks from a pre-rebase branch cannot prove compatibility with newly merged work. *(seen repeatedly)*

- **9.08** Require every mainline writer, including the coordinator, to honor the integration lock. Release it only after the intended commit and clean state are confirmed, because unconditional cleanup after a failed commit can hand over a dirty checkout. *(seen repeatedly)*

- **9.09** Commit with explicit pathspecs and inspect the resulting commit immediately. The index is shared state, and unrelated staged edits can otherwise enter an apparently careful worker's commit. *(seen repeatedly)*

- **9.10** Choose independent review by risk: strong cross-family review for rules, storage, protocol, security, deployment and weaker-model implementation; one lighter review for ordinary UI; coordinator inspection plus checks for low-risk chores. Re-review only real blocker fixes to avoid low-yield review loops. *(owner decision)*

- **9.11** Ask reviewers for concrete reproductions, baseline controls and findings ordered by severity. A probe that fails on the change and passes on the earlier writer is stronger evidence than speculative criticism. *(seen repeatedly)*

- **9.12** Finish product review when no critical gameplay issue remains and new findings are small. Use one player perspective plus scripted screen probes rather than automatically adding judges and refuters to every round. *(owner decision)*

- **9.13** Route mechanical work to cheaper capable workers and reserve scarce reasoning for rules, difficult design and risk review. Measure useful completed work rather than assuming the strongest available model should do everything. *(seen repeatedly)*

- **9.14** Put all expensive commands behind a machine-wide guard for run mode, memory pressure and resource lanes. Scheduling instructions alone cannot stop a late prompt from launching work outside the owner's window. *(seen repeatedly)*

- **9.15** Use one fair admission queue with resource-specific eligibility and coordinator-controlled exceptions. Agents repeatedly checking status and yielding starved compliant workers, while a memory-blocked browser should not block unrelated tests. *(seen repeatedly)*

- **9.16** Run no more heavy commands per worker than the shared policy permits and avoid unneeded development servers. A parallel fleet that causes swapping loses more time than it gains in concurrency. *(seen repeatedly)*

- **9.17** Have lightweight watchers and tracked jobs send completion events, then let the waiting agent end its turn. Polling a lock or process with model turns repeatedly rereads a large context for no new reasoning. *(seen repeatedly)*

- **9.18** Make reporting explicitly nonblocking and address it from a verified agent registry. A synchronous send can wait for the recipient's whole turn, and a guessed identifier can silently send the result nowhere. *(seen repeatedly)*

- **9.19** Handle notification failures durably with retries, an alert file and a fallback recipient when the worker is closed. Launch notifiers from a stable directory so removing a finished worktree cannot break result delivery. *(seen repeatedly)*

- **9.20** On coordinator handoff, rebind inherited workers' report routes and reconcile result files against live status. Completion events may still belong to the original creator, and reboot queues can lose messages. *(seen repeatedly)*

- **9.21** Keep a small private recovery set: verbatim owner instructions, current state, curated learnings, task checklist, artifact ledger and structured results. Preserve owner words separately from coordinator prompts so later agents do not mistake delegated directions for authorization. *(owner decision)*

- **9.22** Checkpoint before quota exhaustion, compaction, reboot or worker closure, including the remaining steps for long jobs. Durable state is useful only when it states what is live and who still owns the next action. *(seen repeatedly)*

- **9.23** Use provider-aware cache warming only during useful waiting periods and compact at a configured natural threshold after saving state. Reuse existing lifecycle tools rather than inventing competing keepalive or compaction mechanisms in each project. *(owner decision)*

- **9.24** Monitor quota and reset behavior across authorized accounts and stop monitoring once the run is idle. A worker that paused cleanly may need an explicit resume event rather than the harness's quota-failure continuation. *(seen repeatedly)*

- **9.25** Make pause and nightshift state durable and enforce it in job admission, with self-contained start, last-call and wind-down procedures. Recovery should act on discrepancies between live jobs and recorded state rather than launch another copy of everything. *(seen repeatedly)*

- **9.26** Stop only processes the task owns, by recorded identity, and verify children are gone. Broad name matching once killed other workers' servers and browsers while failing to provide reliable cleanup. *(seen repeatedly)*

- **9.27** Track bulky artifacts with size, purpose and a safe-deletion date or condition; keep screenshots long enough for follow-up comparisons. Preserve written state and costly uncommitted art instead of treating every temporary directory as disposable. *(owner decision)*

- **9.28** At a stall, inspect resource pressure, last job outcome, permission requests, network errors and result files before restarting agents. Several apparent workflow hangs were actually thrashing, lost notifications or idle sessions after API failure. *(seen repeatedly)*

- **9.29** Dry-run orchestration scripts with stub workers and execute every prompt-construction path before launch. A syntax-only check missed an undefined variable and spent an entire coordination round discovering it. *(seen once)*
