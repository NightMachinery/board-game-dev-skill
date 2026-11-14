# Testing

Test each property at the cheapest layer that can prove it, make every guard prove it can fail, and
keep the CI workload honest.

Layers: pure rules tests (from the rules reference, one clause at a time); seeded playouts with
invariants after every transition; fuzzing of legal play and malformed input; actor contract tests
(first against a small fake engine, then the real one); real-transport tests with recorded frames;
client unit tests; Playwright games driven by offered keys through real controls; the screenshot
matrix and probes; a production smoke suite.

## The game driver

From the first playable milestone, keep one game driver in the repository. It reads the current
redacted view through the read-only test hook (6.13), picks among the offered keys with a seeded
policy or a supplied plan, and performs each choice through the real controls: select, arm,
confirm, private choices and the hand-off between seats. It owns the readiness waits (6.14), so a
harness bug is fixed once for every later run. Its control mapping has offline tests against the
component gallery.

It also captures the complete current viewer UI, including hands, controls, tooltips, staged picks
and confirmation labels. Game information is review evidence, not personal data: do not mask it or
change selections or focus merely to take a screenshot. Exclude credentials and real people's
personal information.

`make e2e` plays one short seeded game per mode to a terminal outcome at one phone size, with a
disposable server secret and journal, and CI runs it on every push. Desktop sizes, every module
group and winning games are a wider opt-in target, run at milestones, releases and by reviewers.
Locally, a slice runs only the specs its change affects (6.17). A new mode, module or rare control
adds one representative case or a gallery case, not a new script. Acceptance runs, reviewer agents
and the production smoke use this driver and add only their own observations. The run directory
holds their evidence, never the only copy of the code that produced it.

## Where acceptance evidence lives

`docs/testing.md` says how to run each check and what it proves. Acceptance evidence goes in one
public file, `docs/dev/acceptance.md`: one entry per area, updated in place, saying what was
checked (sizes, modes, counts, the kind of review), what passed and what was not covered. Change
it in the same commit as the behavior where possible, not in a separate commit that only records
acceptance. Screenshots, traces, private test identities and machine details stay in the run
directory.

## Screenshot review by agents

Agents look at screenshots at two points, and each needs only the images that answer its question.

- **Slice check.** A slice that changes what players see is accepted on screenshots its own agent
  has looked at: the states the change touched, captured by the driver from a real game, at the
  narrowest supported phone, a common phone and a desktop width (for example 320, 390 and 1280 CSS
  pixels), in each direction or locale the change affects. Probes report overflow, bounds and
  console errors; only the image shows whether a player can read the state. This is part of the
  slice's own acceptance, not an extra reviewer.
- **Review round.** At milestones the screens reviewer reads the full matrix (5.11) and player
  reviewers play real games (M10).

Gallery images and real-game images prove different things. A gallery renders named synthetic
states, so it covers rare and private controls cheaply and the same way every time. A real-game
capture proves those controls appear in play. Neither replaces the other. Show the complete
current viewer UI in both, so the review can assess dice, controls and staged choices as a player
sees them. Preserve the game's per-viewer visibility rules; do not expose another seat's hidden
state through the test hook to improve a screenshot.

Record each image a verdict rests on by path and content hash in the run directory, so the verdict
cannot attach to a later capture that overwrote the file. Name the states, sizes and locales left
uncaptured as not covered.

## Timed playthroughs

Separate three questions, because one attempt rarely answers all of them:

- Do the mechanics hold? Expiry, restart and replay are tested on the real clock with no agent in
  the loop.
- Is the game playable well? An agent plays for strategy and understanding on an untimed mode or a
  clearly labelled fixture with the same rules, through the real controls.
- Do the controls keep pace? First measure the budget: the deadline, how many actions a round
  needs, and the agent's measured decision and tool latency. If an agent acting click by click fits,
  let it play. If not, the agent decides once per round from its own current view, as an ordered
  list of offered keys, and the driver performs them through the real controls. A plan may use
  only that viewer's offered keys and private information, never another seat's or a future
  draw. The driver re-reads the view after every action, checks the next key is still offered,
  and stops for a new plan when it is not.

Fix a broken driver on the untimed fixture, not by starting fresh timed games, and set a small
limit on timed attempts before reporting the gap. When the owner asks an agent to play a timed
game directly, do that as asked and report the result. A human playthrough answers how the
pressure feels. A failed winning-game attempt does not invalidate separately established expiry,
replay or transport evidence.

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

- **6.25** Commit the driver that plays full games, and run one short game per mode in CI on every push. Acceptance runs written as private per-run scripts failed several times on harness defects (a cancelling key press, a privacy mask that hid the page, a timeout) rather than on the product, while the committed suite never played a game. *(seen repeatedly)*

- **6.26** For a real deadline, measure the action budget against the agent's decision and tool latency before playing, and let the driver execute a per-round plan when click-by-click play does not fit. Timed attempts in which the agent reasoned between clicks lost on the clock before the first move landed. *(seen once)*

- **6.27** Keep `docs/testing.md` a guide to running checks and keep acceptance evidence in one public file updated in place. Recording each acceptance as its own docs commit made about one commit in seven a docs-only record and turned the testing guide into a long, stale-prone log. *(owner decision)*

- **6.28** Accept a slice that changes the screen on real-game screenshots its agent has looked at, at the narrowest phone, a common phone and desktop, in each affected direction or locale. Bounds, overflow and error counts cannot show whether a player can read the state, and leaving every look to the milestone review finds a slice's regressions only after later slices build on them. *(seen repeatedly)*

- **6.29** Keep gallery and real-game screenshots as separate evidence, but capture the complete current viewer UI in both. Masking game information hides defects, and clearing staged choices destroys the state under review. Protect credentials and personal information rather than treating game state as personal data. *(owner decision)*
