# Testing

Test each property at the cheapest layer that can prove it, make every guard prove it can fail, and
keep the CI workload honest.

Layers: pure rules tests (from the rules reference, one clause at a time); seeded playouts with
invariants after every transition; fuzzing of legal play and malformed input; actor contract tests
(first against a small fake engine, then the real one); real-transport tests with recorded frames;
client unit tests; Playwright games driven by offered keys through real controls; the screenshot
matrix and probes; a production smoke suite.

## Timed playthroughs

Prove the player's control path before starting a real deadline: selectors, action confirmation,
private-choice order and measured decision/tool latency must fit the round budget. Practise on
an untimed mode or a clearly labelled fixture; keep the accepted timed game on its real clock.
A script or agent that spends the window debugging controls has not tested strategic playability.
Record that coverage gap honestly, repair the driver outside the live attempt, and choose a
bounded next test or a human playthrough instead of an indefinite series of fresh games. A failed
winning-flight check does not invalidate separately established expiry, replay or transport evidence.

## Lessons

Each lesson is a rule and its reason. The label says how strong the evidence was: *seen once* (one concrete finding), *seen repeatedly* (recurring failures or independent checks across subsystems), or *owner decision* (an accepted preference, which a new owner may change).

- **6.01** Test in layers: pure rules, actor contracts, real transport, client plumbing and full UI games. Use the cheapest layer capable of proving each property so the browser suite does not carry every rule assertion. *(seen repeatedly)*

- **6.02** Check invariants after every accepted transition in long seeded playouts, not just at game end. Intermediate corruption can be hidden by later moves. *(seen repeatedly)*

- **6.03** Fuzz both legal play and malformed inputs, requiring rejected actions to leave state unchanged. A parser's safety contract includes exact canonical round trips and fail-closed malformed frames. *(seen repeatedly)*

- **6.04** Retain minimized fuzz failures as ordinary regression seeds and discover fuzz targets automatically in CI. A fixed bug should remain covered even when long fuzzing is not running. *(seen repeatedly)*

- **6.05** Pin deterministic setup, generator draws, replay results and protocol output with deliberate goldens. Regeneration must be an explicit reviewed change, never part of the normal assertion path. *(seen repeatedly)*

- **6.06** Give guards negative tests and mutation probes showing that a violation is detected. A passing import or privacy check is weak evidence if the scanner can silently skip files or its oracle shares the implementation's mistake. *(seen repeatedly)*

- **6.07** Prove privacy by varying forbidden hidden state while preserving the viewer's permitted information. Require equal views, hints, bot decisions and relevant counters, and separately vary legitimate knowledge to prove it was not erased. *(seen repeatedly)*

- **6.08** Build leak oracles independently from setup and accepted actions, and deliberately plant leaks. Comparing one view builder with another call to itself cannot detect shared omissions. *(seen repeatedly)*

- **6.09** Capture every viewer's actual network frames through full games, including resync, history, spectators and end policies. Privacy must hold over time and across all message surfaces, not just a representative snapshot. *(seen repeatedly)*

- **6.10** Inject write failures and crashes around durable rename, then verify both restart state and client-visible effects. This tests the boundary between “accepted” and “appeared accepted.” *(seen repeatedly)*

- **6.11** Test arrival permutations, duplicate retries, multi-tab actions, controller changes and pending subsets around restart. Simultaneous actors and reconnect logic fail at these intersections more often than on their happy path. *(seen repeatedly)*

- **6.12** Use a small fake engine to develop generic actor interleavings, but prohibit its production imports. Then run the same actor contracts against the real engine so a convenient fake does not become the release evidence. *(seen repeatedly)*

- **6.13** Drive end-to-end games by the server's offered keys and actual UI controls. A read-only hook may expose the current redacted view and readiness, but must not bypass clicks or implement game legality. *(seen repeatedly)*

- **6.14** Define readiness as welcomed, mounted, current, presentation-idle and free of pending requests. Receiving a state before a lazy screen mounts is insufficient for a UI driver to act. *(seen repeatedly)*

- **6.15** Wait for progress from any participant capable of advancing a multi-client game. Waiting exclusively on one client's publication can deadlock a driver even while the room and other clients are progressing. *(seen once)*

- **6.16** Make scenarios seed-independent or use explicit fixed setup rather than relying on a shared room-creation counter. Run seed-sensitive specs with their neighbors, because isolated success can conceal order dependence. *(seen repeatedly)*

- **6.17** Choose regression specs by searching for the affected component's test attributes, and include standard cross-cutting acceptance specs. Hand-picked lists from memory missed tutorial and result-screen dependencies. *(seen repeatedly)*

- **6.18** Test behavior without arbitrary sleeps, using state, mounting, animation completion and injected clocks. Time delays obscure whether a wait is for real application progress or accidental machine speed. *(seen repeatedly)*

- **6.19** When adding expensive tests, run the CI-shaped command with its actual race, shuffle, short-mode and timeout settings. A green quick target did not reveal a large increase in the normal CI race workload. *(seen repeatedly)*

- **6.20** Keep costly strength and performance measurements opt-in or deliberately sampled while retaining correctness coverage. Replaying full strong-bot games under every race test can exhaust CI headroom without adding distinct assertions. *(seen repeatedly)*

- **6.21** Inspect post-push CI and keep fast local gates aligned with CI prerequisites. Local green checks once concealed a module-tidiness failure that prevented downstream browser jobs from running. *(seen repeatedly)*

- **6.22** Diagnose performance failures with traces and stated hardware/load instead of repeatedly widening thresholds. Separate application callbacks from garbage collection, compositor waits and runner noise before changing code. *(seen repeatedly)*

- **6.23** Measure paired clean baseline and candidate builds and distinguish cumulative budgets from per-slice allowances. Build hashes and shared runtime helpers can move compressed entry bytes even without an obvious new import. *(seen repeatedly)*

- **6.24** Restrict production browser runs to an explicit smoke suite and health-check reachability before taking the browser lock. An unreachable live URL can otherwise monopolize shared test capacity for minutes per spec. *(seen repeatedly)*
