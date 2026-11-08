# Platform features

Identity, rooms, roles, spectators, reconnect and the protocol. The owner's default requirements
for these are in [requirements.md](requirements.md); the lessons below are how to build them so they
survive restarts, reconnects and multiple tabs.

## Lessons

Each lesson is a rule and its reason. The label says how strong the evidence was: *seen once* (one concrete finding), *seen repeatedly* (recurring failures or independent checks across subsystems), or *owner decision* (an accepted preference, which a new owner may change).

- **4.01** For casual play, a locally stored random browser token can provide identity without accounts. Derive server identifiers with a secret-keyed function and keep the token out of URLs and logs. *(owner decision)*

- **4.02** Associate the saved display name with device identity so returning users do not repeatedly answer the same prompt. Distinguish the viewer's own seat with shape or text as well as color. *(owner decision)*

- **4.03** Give duplicate display names stable room-local suffixes and avoid renumbering others when someone leaves. A label that changes under the player's feet undermines recognition in a long game. *(owner decision)*

- **4.04** Provide room-scoped device-transfer claims that cannot reveal the global identity token. Keep the claim refreshable in the URL fragment and expose a revocation action because the link grants seat access. *(owner decision)*

- **4.05** Bind device claims to a revocable seat epoch and detach connections whose authority is lost. Relinking or replacing a controller must invalidate both future claims and already attached sessions. *(seen repeatedly)*

- **4.06** Keep creator ownership permanent and specify promotion and demotion ancestry explicitly. Moderation rules should survive restart and should not accidentally grant arbitrary users the creator's powers. *(owner decision)*

- **4.07** Define temporary moderation as a separate revocable role for the period when all real moderators are absent. By default it has full moderator powers, and anyone it promotes is also temporary; a project that restricts those powers should say so as an explicit decision. *(owner decision)*

- **4.08** Recheck time-dependent authorization at the moment of action and fail closed while its durable state is uncertain. A failed role write must not preserve powers that the timeout rule has already withdrawn. *(seen repeatedly)*

- **4.09** Keep spectators as a real viewer role with its own projection, join policy and capacity accounting. Watching must neither claim a player seat nor expose private offers. *(seen repeatedly)*

- **4.10** Let authorized moderators change seat controllers without altering the underlying table and retain a previous-seat hint where useful. Explicitly acknowledge that software cannot erase information a former controller already saw. *(owner decision)*

- **4.11** Freeze player order and game options at an explicit lobby Start. A populated lobby should not unexpectedly become a game merely because the final guest joined. *(seen repeatedly)*

- **4.12** Keep a disconnect separate from abandonment of a seat. Reconnecting players should regain their persisted seat, while takeover and resignation follow explicit room policy. *(seen repeatedly)*

- **4.13** Scope idempotency by both authenticated user and client identity, with a state reference on requests. Two users choosing the same client identifier must not interfere with each other's acknowledgments. *(seen repeatedly)*

- **4.14** Preserve the same request identity when retrying after reconnect, but bind seat-dependent intent to the seat originally targeted. An old resignation or pick must never be reinterpreted for a newly assigned seat. *(seen repeatedly)*

- **4.15** Give client identifiers and sequence counters matching lifetimes. A component remount that resets the counter while retaining its identifier can make valid new requests look like old duplicates. *(seen once)*

- **4.16** Make rematch creation idempotent and crash-resumable with one durably reserved successor code. Simultaneous requests or a restart between writes must not produce different next games. *(seen repeatedly)*

- **4.17** Generate client wire types from server DTOs and type-check actual recorded frames against them. Type generation alone cannot prove that the runtime serializer emits the declared shape. *(seen repeatedly)*

- **4.18** Translate all visible and assistive strings, send structured codes from the server and use locale-aware number formatting. Tooltips, errors, alt text and accessible names are part of the language contract. *(seen repeatedly)*

- **4.19** Use logical layout properties for interface chrome while keeping spatial game directions explicit. Mirroring a rules-defined neighbor relation or board geometry can change the meaning of the screen. *(seen repeatedly)*

- **4.20** Implement one tooltip helper for the smallest meaningful symbols: hover and focus on fine pointers, tap on non-actions, long-press on actions, Escape or a swallowed dismissing tap to close. Show only one tooltip, prefer the innermost target and suppress action on long-press release so explanations never trigger a move. *(owner decision)*

- **4.21** Separate room-wide assistance settings from device-local hiding and future-game defaults. Fairness-affecting settings belong to the room and its authorized moderators, while a player may privately hide information the room permits. *(owner decision)*

- **4.22** Define undo around the last human decision and replay the original random setup, with explicit multi-human restrictions. Undo must neither reroll hidden outcomes nor restore authority or information that another human has already acquired. *(seen repeatedly)*

- **4.23** Make end-of-game disclosure and downloadable replay policy explicit. A replay seed and hidden action keys reveal more than a public score sheet, so a game that keeps secrets at the end must also restrict the complete record. *(seen repeatedly)*

- **4.24** Apply authentication, request budgets and connection bounds before expensive room or engine work, including across tabs and reloads. A superficially per-connection limit can be bypassed by reconnecting or opening more clients. *(seen repeatedly)*

- **4.25** Decode protocol families strictly, rejecting unknown, duplicate, missing or wrongly typed fields before dispatch. Required false and zero values must remain distinguishable from absence. *(seen repeatedly)*
