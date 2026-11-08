# UI on phones

Design on a phone first and test height as seriously as width. Real play on a phone found problems
that every portrait screenshot passed.

Client rules that held up: Svelte 5 runes only; `$derived` over `$effect`; `$state.raw` for the
large server views; Tailwind mobile-first with the default palette switched off so every colour is
a theme token; logical CSS properties for chrome while the board keeps explicit spatial
directions; `data-*` attributes as the end-to-end contract (cards, actions, tutorial anchors);
every visible and assistive string through the translation tables; `dir="auto"` on user text; the
game's own Animation setting (with a true off) instead of the operating system's reduced-motion
flag, unless the owner prefers the latter.

## Lessons

Each lesson is a rule and its reason. The label says how strong the evidence was: *seen once* (one concrete finding), *seen repeatedly* (recurring failures or independent checks across subsystems), or *owner decision* (an accepted preference, which a new owner may change).

- **5.01** Design the phone layout first and rearrange shared components for larger screens. Shrinking a desktop board leaves important status and controls unreadable even when nothing technically overflows. *(seen repeatedly)*

- **5.02** Test height independently of width, including landscape and reduced-height split-screen use. Essential player status and phase actions disappeared in real phone play despite ordinary portrait checks passing. *(seen repeatedly)*

- **5.03** Keep the active decision set comparable without horizontal board scrolling. Use container-sized grids and compact summaries rather than requiring players to remember off-screen alternatives. *(seen repeatedly)*

- **5.04** Define and test a minimum playable viewport, then show a clear size notice below it. An honest fallback is preferable to silently hiding required controls. *(seen once)*

- **5.05** Preserve player resources, progress and the current required action when compressing a layout. Decorative space and repeated labels should yield before game-critical information. *(seen repeatedly)*

- **5.06** Measure real hit boxes, aim for comfortable touch targets and probe covered action centers. A visible large control can still be unclickable under another layer. *(seen repeatedly)*

- **5.07** Make phone sheets fit the viewport with reachable actions and deliberate internal scrolling or dismissal gestures. The browser's pull-to-refresh must not become the accidental substitute for closing a card sheet. *(seen repeatedly)*

- **5.08** Repeat long-press-only information in an ordinary card-detail view and add a concise first-use hint or legend. Correct tooltip behavior did not make tiny hint badges discoverable on touch screens. *(seen repeatedly)*

- **5.09** Highlight meaningful affordances using server-supplied availability, and name the object an action affects. A generic button label can conceal a strategically important option on a dense phone screen. *(seen repeatedly)*

- **5.10** Give categories, effects and player identities distinct visual vocabularies, with redundant shapes and patterns. Reusing one subject for different meanings creates ambiguity that color cannot reliably fix. *(seen repeatedly)*

- **5.11** Render screenshot matrices from stable named states across supported sizes, directions and themes. Preserve before and after images in separate directories so a visual fix remains reviewable. *(seen repeatedly)*

- **5.12** Combine screenshots with overflow, contrast, target, occlusion and console probes, then play actual games. Automated geometry cannot establish whether players understand the state or reach an action naturally. *(seen repeatedly)*

- **5.13** Build animations, sound, tutorials and explanatory UI before the main product review loop. Repeatedly reviewing an unfinished game spends effort rediscovering already planned gaps. *(owner decision)*

- **5.14** Review complete play flows, including reconnect, extra decisions, phase transitions, results and returning players. Static board beauty did not catch missing summaries, inaccessible dialogs or stale presentation. *(seen repeatedly)*

- **5.15** Let the game's saved Animation setting control pacing, including a true off mode. With animation disabled, the new state, grouped reveal and recap must remain understandable. *(owner decision)*

- **5.16** Separate authoritative state from paced presentation and wait for the presentation to finish before opening dependent dialogs. A result or phase chooser that appears early can hide the final move or expose the new board before its reveal. *(seen repeatedly)*

- **5.17** Measure cold transfer, DOM count and throttled first-paint metrics with an explicit profile. Budgets should protect real entry paths, not merely a nominal bundle file that users may never load alone. *(seen repeatedly)*

- **5.18** Offer install and fullscreen controls where supported and preserve a usable ordinary-browser path. Home-screen mode can recover scarce phone height, but capability checks and copy fallbacks still matter. *(owner decision)*
