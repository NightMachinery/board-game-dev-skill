# Adopt the tools

These templates provide tools, agreements and client helpers. They do not bundle
a server module, runnable SvelteKit app, root package/workspace and lockfile,
CI configuration, end-to-end project, game rules or protocol generator.

Use this order to make the first quick gate runnable:

1. Create the game repository and private run directory. Write the owner's
   agreed scope and rules, then implement the server module skeleton: Go entry
   point, health route, pure engine and test packages. Create `server/go.mod`.
2. Scaffold a Svelte 5/SvelteKit app in `web/` with adapter-static and
   `fallback: '200.html'`. Create the root pnpm package/workspace, pin Node/pnpm,
   declare the web dependencies plus root Playwright, and generate and commit
   `pnpm-lock.yaml`. Add the chosen licences and self-hosted fonts.
3. Copy `tools/`, `tests/`, `self_host.py` and `docs/` to the root. Rename
   `Makefile.template` and `AGENTS.md.template`; merge `.gitignore.template`.
   Adapt the agreement and assign one coordinator for shared files. Edit
   `tools/project.json`: name, shared private run directory, ports, hosting
   layout/static-serving choice and art kinds. Keep browser/codex/light kinds.
4. Set the exact Go pin in the Makefile, the single source read by self_host.py;
   keep `server/go.mod` compatible. Copy `web/src/lib/` and the rules page into
   the app. Set the identity storage prefix to the project name. Connect the
   translator, theme aliases, complete rules sections and layout overlays.
5. Choose one launch theme and copy it into `themes/`, including every parent
   it inherits. Set `default_theme`; `my-theme` is a placeholder. Add game
   content in `art/subjects.json`. See [art tools](tools/art/README.md).
6. Supply real `web` scripts `test`, `check`, `lint`, `build` and `dev`.
   Configure Vitest to find the copied tests and Svelte/TypeScript checks.
   Implement the protocol generator and adapt `gen`/`gen-check` and `GEN_DIR`.
   Adapt the Go package and every Makefile command to actual project paths.
   Do not leave absent steps silently succeeding.
7. Run `make install` once, or `make install-offline` when the lockfile's
   dependencies are already cached. Then run `make verify-quick` through the
   resource guard. This is the first complete quick gate; fix real failures.
8. Add CI to run that gate with the pinned tools and relevant full/race tests.
   Create `e2e/` with Playwright config, a controlled test server, test scripts
   and a `shots` project before running `make e2e`, `make shots` or
   `make verify-full`. Those projects are not supplied by this template. From
   the first playable game, add the committed game driver and its routine
   games (one per mode, phone size) to `make e2e`, and run `make e2e` in CI on
   every push; the wider set reads `E2E_FULL=1`. See the skill's testing
   reference, "The game driver".
9. Configure the local/dev URL and hosting layout, run the hosting adoption
   check and use its printed frontend URL for screenshots. Production
   deployment requires the owner's explicit deployment authority.

Standalone tool checks from this directory require Python 3 and Node 22+:

```sh
python3 -m unittest
node --test tools/chrome/*.test.mjs tools/art/art.test.mjs
```

Run checks through the existing machine's guard during real development.
`ART_INTEGRATION=1` adds installed ImageMagick/cwebp/avifenc checks. Standalone
checks never start a browser, contact an LLM or edit a home Caddyfile. Web tests
need the adopted project's Vitest and Svelte/TypeScript dependencies.

Read [the guard](tools/README.md), [browser tools](tools/chrome/README.md),
[web helpers](web/README.md) and [hosting](docs/self-hosting.md) when adopting
those parts. Fill scope, paths, providers and reporting destinations in the
worker/reviewer `briefs/`; keep filled briefs private.
