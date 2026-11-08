# Adopt the tools

Copy this directory's tools, tests, self_host.py and docs into the game root.
Rename `Makefile.template` and `AGENTS.md.template`; merge `.gitignore.template`.
Copy web helpers into the Svelte app. These are tools and agreements, not a
complete game: implement the pure engine, room actor, protocol and client first.

Edit `tools/project.json`: project name, common private run directory, ports,
hosting layout and art kinds. Keep `browser`, `codex` and `light` kinds. Set the
client identity storage prefix to match the project name. Pin Go consistently
in Makefile, self_host.py and server/go.mod. Adapt package scripts and the
protocol generator targets to the new project; do not leave placeholder tasks
silently succeeding. Keep one coordinator for single-writer files.

The default theme id is a placeholder. Copy one or more supplied theme packs
into `themes/` and choose `default_theme`. `art/subjects.json` is the game's
content map; reusable themes describe style and optional overrides. See
[art tools](tools/art/README.md) for the exact theme schema and review gate.

Quick standalone checks from this directory need Python 3 and Node 22+:

```sh
python3 -m unittest
node --test tools/chrome/cli.test.mjs tools/art/art.test.mjs
```

Run checks through the existing machine's guard during real development.
`ART_INTEGRATION=1` additionally runs installed ImageMagick/cwebp/avifenc.
Web tests need the adopted project's Vitest and Svelte/TypeScript checks.
No standalone test starts a browser, contacts an LLM or edits a home Caddyfile.

Read [the guard](tools/README.md), [browser tools](tools/chrome/README.md),
[web helpers](web/README.md) and [hosting](docs/self-hosting.md) when adopting
those parts. Worker and review briefs live in `briefs/`; fill their paths,
scope and reporting destination before using them. Keep filled briefs private.
