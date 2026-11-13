# Slice: <MILESTONE.outcome>

Read `<COMMON_BRIEF_PATH>`. Repo `<REPO>`, current branch `<BRANCH>`, baseline
`<BASE_COMMIT>`. Provider/model `<PROVIDER>/<MODEL>`. Keep the current branch.
Owned paths: `<EXPLICIT_PATHS>`. Single writers/exclusions: `<PATHS>`. Runs
unattended; this brief settles routine design questions within scope.

## Problem and intended behavior

<Concrete trigger, current failure, desired outcome and why players need it.>

## Contract

<Inputs/outputs, engine/view/wire boundaries, hidden information, deterministic
entropy, persistence/version behavior, migrations and failure/cancellation rules.>

## Work

1. <One cohesive change, with an observable acceptance example.>
2. <Meaningful tests from the rule/contract, including stale/adversarial input.>
3. <Docs and generated output updates, or single-writer request.>

## Checks and acceptance

<Exact quick checks, affected package tests with normal CI flags, relevant
browser specs and invariants. Identify controlled server/ports if needed.>
<If the slice changes the screen: the states, sizes and directions/locales whose
real-game screenshots the agent inspects, per "Screenshot review by agents".>

## Finish

Atomic commit group(s): `<GROUPS>`. Result `<RESULT_PATH>`, checkpoint
`<CHECKPOINT_PATH>`, private artifacts `<ARTIFACT_DIR>`. Report actual outcomes,
check elapsed times, concerns and any unmet acceptance criterion. Notify
`<COORDINATOR_ID>` with `paseo send --no-wait` as the common brief specifies.
