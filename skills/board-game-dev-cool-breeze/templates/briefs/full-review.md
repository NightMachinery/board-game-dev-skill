# Independent FULL review: <SLICE_ID>

Review only, no repository writes or commits. Repo `<REPO>`, branch `<BRANCH>`,
baseline `<BASE_COMMIT>`, commits `<COMMITS>`, diff `<EXACT_DIFF_COMMAND>`.
Implementation by `<AUTHOR_MODEL>`, review by `<PROVIDER>/<REVIEW_MODEL>`.
Read `<IMPLEMENTATION_BRIEF>`, `<WORKER_RESULT>`, AGENTS.md and `<CONTRACT_DOCS>`.

Review the final behavior independently. Cover the applicable high-risk paths:

- Rules and information boundaries: legal-action membership, determinism,
  observations by viewer, logs and error responses without hidden information.
- Stored data: old records load/replay unchanged; versions freeze semantics;
  unknown or corrupt versions fail clearly. Undo/restore and reconnect preserve
  idempotency. No migration silently changes old games.
- Concurrency: serialized room state, bounded work, structural cancellation,
  watchdog/fallback, stale worker results and disconnected viewers.
- Deployment: actual host/ports, both serving modes, shared Caddy preservation,
  frozen dependencies, readiness checks and honest failed/unknown outcomes.
- Tests/scope: meaningful adversarial cases, CI flags, no weakened assertions,
  generated/wire compatibility, and single-writer boundaries preserved.

Run only relevant checks through the resource guard, one at a time. Keep the
worktree clean and never start a dev server. Each finding needs severity
(blocker, major, minor), a concrete trigger, expected/actual behavior, file/line
and evidence. Do not pad the report or invent a failure from a preference.

Write `<REVIEW_PATH>` first line APPROVED or CHANGES REQUESTED. List exact
checks and limitations. Notify `<COORDINATOR_ID>` with
`paseo send --no-wait <COORDINATOR_ID> "<SLICE_ID> review <VERDICT> <REVIEW_PATH>"`
if authorized, then stop. Re-review only a real blocker's fix.
