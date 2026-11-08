# Common worker agreement

Replace `<REPO>`, `<RUN_DIR>`, `<COORDINATOR_ID>`, `<PROVIDER>`, `<MODEL>` and
result/checkpoint paths before sending. Runs unattended; the assignment settles
routine design questions. Scope never expands permissions.

Read `<REPO>/AGENTS.md` and `<RUN_DIR>/NOTES.md` first. Work only on the assigned
branch and owned paths. Coordinator messages go in your checkpoint, never in
the owner's verbatim instruction file. Read-only reviewers do not change code.

Install cached dependencies once with `make install-offline`. Heavy commands
go through the guard, once, detached with completion notification:
`HEAVY_NOTIFY=auto python3 tools/heavy.py run --kind KIND --wait 3600 -- COMMAND`.
For a whole Make target, use outer `--kind light -- make TARGET`. Never export
HEAVY_NOTIFY, submit concurrent heavy jobs, retry exit 75 in a loop, poll with
model turns or use stop-all. End your turn while a detached job waits. For a
sandbox refusal request only the access that specific authorized command needs.

Use the pinned Go toolchain. Keep engine and client boundaries from AGENTS.md.
Search affected end-to-end tests by changed data attributes and behavior. Run
the normal CI flags for affected packages; do not claim a short-only test proves
the full/race suite. If tests slow down, measure the affected CI command and
report elapsed time against the baseline. Never weaken checks to make them pass.

The repository may be public. No private paths, people, service destinations,
secrets, agent ids or account information in committed code/docs. Keep review
artifacts and private runtime state under `<RUN_DIR>`. Stop owned test processes
by verified PID, close testing browsers, leave owner-managed services alone.

Commit cohesive changes with explicit pathspecs, recheck status immediately
before committing, inspect `git show --stat` afterward. Subject
`area: summary (<SLICE_ID>)`, trailer `Slice: <SLICE_ID>` and a Co-Authored-By
trailer naming the actual model. No push, merge, rebase, branch change or
deployment unless the assignment explicitly requests it. Single-writer changes
are requests in the result.

Keep `<CHECKPOINT_PATH>` current. Write `<RESULT_PATH>` with first line DONE,
PARTIAL or FAILED; include commits, actual checks/outcomes, evidence paths and
sizes, limitations and requests. Always write the result, even on failure.
Then `paseo send --no-wait <COORDINATOR_ID> "<SLICE_ID> <STATUS> <RESULT_PATH>"`
and stop. Use this notification only when the assignment authorizes it.
