# Bitmap and vector tools

Copy `tools/art`, `tools/config.mjs`, `tools/project.json`, `heavy.py`, and the
`art/` skeletons. Requires Node 22+, ImageMagick, cwebp and avifenc. The vector
fast renderer also needs librsvg. Tools call executable files directly, without
shell aliases. Set `CODEX_BIN` to the real Codex binary's absolute path.

Project settings live in `tools/project.json`: `themes_dir`, `default_theme`,
and `art.kinds` with generation size and shipped sizes (`name,w,h,budget` bytes).
`BGD_ART_ROOT` points tests at another data tree; `BGD_RUN_DIR` keeps attempts
private and shares the guard's state directory.

Each `themes/<id>/theme.json` contains `id`, `name`, `mode` (required `light`
or `dark`), `inherits` (ordered parent ids), `tokens` (semantic CSS token keys)
and `artDirection` (relative style file path inside that theme). Copy `art/style.md`
there and adapt it. A theme contains style, not game content. Game-wide
`art/subjects.json` maps `kind/slug` to `{ "subject": "...", "accent": "..." }`.
Optional `themes/<id>/subjects.json` overrides selected subjects. Child values
win; first parents win over later parents, recursively, then the game map.
Cycles and unknown parents fail. Copy every parent theme directory along with a
child. Token groups inherit the same way.

Use these steps for each theme (replace `THEME` and `card/sample`):

```sh
node tools/art/manifest.mjs --theme THEME
node tools/art/generate.mjs --theme THEME --id card/sample --dry-run
node tools/art/generate.mjs --theme THEME --id card/sample
node tools/art/sheet.mjs --theme THEME --out /tmp/contact.png
node tools/art/apply-review.mjs --theme THEME --review /tmp/decisions.json
node tools/art/process.mjs --theme THEME --id card/sample
node tools/art/gate.mjs --theme THEME
node tools/art/index.mjs --theme THEME
```

The generator automatically enters the guard's exclusive `codex` lane and
generates exactly one bitmap per call. Submit once and wait for its outcome.
It requires exactly one new PNG and verifies its shape and pixel size.
Review files are arrays of `{id,attempt,fingerprint,status,reviewer,reasons,amend?}`;
copy the full fingerprint from the manifest. Only an explicit approval ships
that attempt. A subject, style or size change clears approval and outputs on
manifest rebuild. `process --out /tmp/preview` processes an unapproved attempt
without changing committed files. Keep one pipeline writer per theme.

Originals become RGBA-verified lossless WebP in `art/originals/<theme>/...`.
AVIF files ship under `web/static/art/<theme>/...`, with hard byte budgets.
The generated `web/src/lib/art/<theme>.gen.json` contains only resolved approved
assets, inherited tokens, mode and content-hashed URLs. A missing asset is
`null`: draw a procedural placeholder. Parent art may appear in a child's
index; unrelated sibling assets never do. The client loads one index at a time
and fetches only URLs in that index. Apply its mode as CSS `color-scheme` and
its tokens as the game's theme. Never follow OS light/dark changes automatically.
If multiple packs ship, an explicit settings choice can select another.

No catalog parser, game aliases, icon-PNG special case, or painting-specific
paper/mask correction is included. Add such processing only when the game's
art direction calls for it. Keep review images and rejected attempts outside
git; approved lossless originals belong in git.

Tests: `node --test tools/art/*.test.mjs`; add `ART_INTEGRATION=1` to exercise
the installed native codecs with a tiny generated sentinel image. Wrap native
processing and contact-sheet batches in the resource guard.

The client accepts string/number token values. Prefer flat semantic keys such
as `table`, `panel`, `fg`, `accent`, `on-accent`, `rule`, `type-ui` and
`type-display`: they become CSS `--table`, `--panel`, `--fg`, `--accent`,
`--on-accent`, `--rule`, `--type-ui` and `--type-display`. Nested groups also
work and flatten with hyphens: `{ "colours": { "ink": "#222" } }` becomes
`--colours-ink`, not `--ink`. The templates supply no Tailwind binding or full
required token set: bind the game's semantic utilities to its chosen names.
Tooltip components read `--tooltip-bg`, `--tooltip-fg`, `--tooltip-rule`; rules
components read `--rules-bg`, `--rules-fg`, `--rules-rule`. Alias those to
`--panel`, `--fg`, `--rule` in the app's CSS if using the supplied theme keys.

Rejected reviews' `promptAmend` is automatically reused by the next generation;
`--amend` explicitly replaces it for that attempt, including an empty string
to clear it.
