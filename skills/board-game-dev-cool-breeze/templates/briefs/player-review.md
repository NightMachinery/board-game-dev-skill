# Player review: <ROUND_ID>

Review only, no fixes. Repo/context `<REPO>`, rules `<RULES_DOCS>`, controlled
build `<TEST_URL_OR_ARTIFACTS>`, test credentials/seeds `<PRIVATE_FIXTURE_PATH>`.
Provider/model `<PROVIDER>/<MODEL>`. Read AGENTS.md and `<TEST_CONTRACT>` first.
Use only the supplied build and private test identities. Never use a daily
browser profile. Any browser runs through the guard and closes on completion.

Play as someone learning the game, then as a returning player. Understand
whose turn it is, available actions and consequences, resources/score, the
opponent's public state and how to recover from a mistaken selection. Exercise
the relevant create/join/reconnect, waiting/opponent action, card sheet, rules,
tooltip, undo/rematch and end-game paths. Keep viewer identities separate.
Try keyboard and touch where the assignment supplies them. Follow the rules
instead of testing only the implementation's happy path.

For each real problem record priority P0..P3 using the screens-review scale,
the exact state/steps, expected versus observed behavior, why it matters to
play, and screenshot or trace evidence. Include the viewport, input method,
locale/direction, theme and seed when available. Never include private tokens
in the report or screenshot. Distinguish a confusing rule explanation from an
engine rule error. Flag uncaptured/unexercised areas as limitations.

Write `<REPORT_PATH>` with severity counts first, then coverage and findings.
Stop only owned processes, close the testing browser, record artifacts/sizes,
notify `<COORDINATOR_ID>` through the authorized channel and stop. Do not
request another broad review round for polish alone.
