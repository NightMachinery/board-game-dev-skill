# Bots

Bots see exactly what their seat may know, spend a fixed amount of deterministic work, and earn a
named difficulty only after measured evidence. Strength claims need held-out evaluation, not the
numbers used for tuning.

## Lessons

Each lesson is a rule and its reason. The label says how strong the evidence was: *seen once* (one concrete finding), *seen repeatedly* (recurring failures or independent checks across subsystems), or *owner decision* (an accepted preference, which a new owner may change).

- **7.01** Start with explicitly defined Random and deterministic Greedy baselines before adding search. Without baselines and measurement tooling, additional computation is not evidence of stronger play. *(seen repeatedly)*

- **7.02** Define random choice over meaningful decisions rather than uniformly over encoded keys when one option has many payment variants. Otherwise representation multiplicity biases the supposedly neutral baseline. *(seen once)*

- **7.03** Give every bot an immutable permitted observation, never the real game state. Difficulty should change computation and noise rather than access to concealed cards or pending opponent choices. *(seen repeatedly)*

- **7.04** Put hidden-world construction in the engine's information contract and bound its work. A failed sampler should return no world and trigger an honest legal fallback, rather than fabricate a convenient inconsistent state. *(seen repeatedly)*

- **7.05** Preserve legitimately remembered information in observations and sampled worlds. Honesty means using exactly what the player may know, not discarding memory simply because it is difficult to reconstruct. *(seen repeatedly)*

- **7.06** Report sampling support separately from sampling probabilities and measure bias on independently enumerable cases. Reaching every feasible world does not establish a uniform distribution or a strategically correct posterior. *(seen once)*

- **7.07** Simulate simultaneous rounds by creating all seat observations before any choice is generated. A rollout opponent must not react to another pick that was hidden at that same decision point. *(seen repeatedly)*

- **7.08** Compare candidate actions on paired sampled worlds and shared, indexed randomness. This reduces comparison noise and stops one candidate's extra calls from shifting another candidate's opponent behavior. *(seen repeatedly)*

- **7.09** Derive bot entropy from logical decision identity and permitted information, with separate random domains for policy and setup. Presence changes, private opponent edits, scheduling and transport revisions must not change a bot's choice. *(seen repeatedly)*

- **7.10** Define search work deterministically and use wall clocks only for exceptional watchdogs. Fixed work makes decisions repeatable and separates measured strength from machine load. *(seen repeatedly)*

- **7.11** Keep per-bot difficulty work constant as the table gains more bots, and present the resulting wait tradeoff honestly. Silently dividing a room-wide budget makes the same named level weaker in fuller games. *(owner decision)*

- **7.12** Freeze effective policy, preset and work bounds durably before launching a decision. Restart, undo and controller changes must preserve the promised work and already accepted picks. *(seen repeatedly)*

- **7.13** Support old released preset mappings explicitly or reject them explicitly. New tables may gain a stronger level without silently changing how existing stored games continue. *(seen repeatedly)*

- **7.14** Pin actual released decisions and work counters on synthetic fixtures, not just preset constants. Evaluator, shortlist, tie-break and noise changes can alter a supposedly frozen policy while leaving its stored version untouched. *(seen once)*

- **7.15** Share search permits fairly, keep at most one queued or active job per room when serial service suffices, and release between picks. One large bot table should not fill the queue ahead of every other player. *(seen repeatedly)*

- **7.16** Cancel within samplers and rollouts, wait for physical worker completion before releasing its permit, and reject late results by task identity. Cancellation of a logical task does not prove the underlying computation has stopped. *(seen repeatedly)*

- **7.17** Accept only complete comparison sweeps and distinguish cancellation, sampler fallback and watchdog fallback in diagnostics. A partial incumbent can bias decisions according to runtime timing. *(seen repeatedly)*

- **7.18** Tune on development and validation partitions, freeze the candidate, then inspect an untouched held-out gate once. If informed retuning follows failure, use a new held-out epoch and disclose that the old seeds are spent. *(seen repeatedly)*

- **7.19** Rotate the focal policy through seats within fixed deal blocks and compute uncertainty with those blocks intact. Treating rotations as independent games exaggerates confidence and can hide seat or neighbor advantages. *(seen repeatedly)*

- **7.20** Gate each supported player count and relevant mixed lineup separately at the production preset. A pooled average or oversized offline budget can hide a weak configuration that players actually receive. *(seen repeatedly)*

- **7.21** Report search, queue, persistence, delivery and presentation latency as different clocks, with hardware, load, sample count and quantiles. A fast simulator result does not establish live-room wait or production capacity. *(seen repeatedly)*

- **7.22** Keep advanced levels and predictive advice unavailable until their independent strength, privacy and runtime gates pass. Optional post-move teaching should use the pre-decision observation and remain quiet when evidence is incomplete or uncertain. *(owner decision)*
