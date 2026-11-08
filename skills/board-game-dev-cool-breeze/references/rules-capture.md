# Rules capture

Write the specification before the implementation, in your own words, so tests and reviewers can
check the code against something the code did not produce.

Artifacts: `docs/rules/` (the reference, one file per area), a glossary of recurring terms, the
sources list (what was consulted and what was not available), the data tables, and
`docs/rules/decisions.md` with one entry per ruling: the competing values, the choice, the reason,
the evidence and what remains uncertain. Downloaded rulebooks and photos stay out of the
repository.

## Lessons

Each lesson is a rule and its reason. The label says how strong the evidence was: *seen once* (one concrete finding), *seen repeatedly* (recurring failures or independent checks across subsystems), or *owner decision* (an accepted preference, which a new owner may change).

- **3.01** Write a complete rules reference in original wording before implementing rules slices. It gives tests and reviewers an independent specification instead of letting the implementation define its own correctness. *(seen repeatedly)*

- **3.02** Declare the exact edition, player counts and expansion scope before collecting data. Nearby editions and fan references can agree with each other while describing the wrong game. *(seen repeatedly)*

- **3.03** Build independent data tables blind to the implementation and reconcile every field. Multiple readers copying one existing table provide less independence than their headcount suggests. *(seen repeatedly)*

- **3.04** Normalize names and join keys explicitly before comparing sources. Identifier order, spelling and capitalization caused large apparent disagreement that was separate from actual rule errors. *(seen repeatedly)*

- **3.05** Record each disagreement as the competing values, chosen ruling, reason, evidence and residual uncertainty. A future contributor should be able to reopen one disputed fact without redoing the entire extraction. *(seen repeatedly)*

- **3.06** Prefer primary printed evidence and official clarifications over agreement among derivative implementations. Independent codebases can inherit the same mistaken value. *(seen repeatedly)*

- **3.07** Treat inaccessible or missing sources as explicit evidence gaps with provisional rulings. Do not write “verified” when the remaining basis is secondary agreement or owner acceptance. *(seen repeatedly)*

- **3.08** Define recurring terms once and use them consistently across rules, engine, protocol and UI. Ambiguous words such as turn, point, copy and design caused avoidable contract disagreement. *(seen repeatedly)*

- **3.09** Specify timing, scope, forced choices, empty offers, terminal conditions and simultaneous effects separately from numeric catalog data. Field equality cannot catch an effect applied to the wrong player or at the wrong moment. *(seen repeatedly)*

- **3.10** Write a focused rules test before the code for each behavior and retain named pins for adjudicated edge cases. A broad random sweep is useful evidence but an unreliable substitute for a specific clause's regression test. *(seen repeatedly)*

- **3.11** Check complex payment or allocation solvers against a small independent exhaustive oracle. Optimized code and tests using the same helper can share the same mistake. *(seen repeatedly)*

- **3.12** Require a ruling before changing reference fixtures, then add a narrow pin for the resolved mistake. Blindly regenerating expected data turns the verification gate into a snapshot of whichever implementation ran last. *(seen repeatedly)*
