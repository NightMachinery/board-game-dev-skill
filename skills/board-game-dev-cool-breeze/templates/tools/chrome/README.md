# Throwaway browser tools

Copy this directory plus `tools/config.mjs`, `tools/project.json` and `heavy.py`. Requires Node 22+ (built-in WebSocket). Install `playwright` in the project root and run `pnpm exec playwright install chromium --no-shell`. Alternatively point `CHROME_BIN` at a separate Chrome for Testing executable. Never use a daily browser or its profile.

`launch.mjs` starts a headless browser with a unique temporary profile, reads its own DevTools endpoint from stderr, refuses a busy port and closes its process group and helpers on exit. `project.json` defines the port; `CHROME_PORT=0` asks Chromium for a free one. `CHROME_CDP` may attach only to another testing browser started with these tools; attached browsers remain their caller's responsibility.

Run all browser work inside the guard:

```sh
python3 tools/heavy.py run --kind browser -- node tools/chrome/shot.mjs --origin "$BGD_ORIGIN" --url / --vp 390x844@2 --probe --out /tmp/page.png
python3 tools/heavy.py run --kind browser -- node tools/chrome/svg-render.mjs --in art/vector --sizes 16,24,48,128 --out /tmp/icons.png
```

`shot.mjs --help` lists flags. `--origin` or `BGD_ORIGIN` changes the target; `--storage` seeds test-only localStorage before scripts run. `--token` and `--name` match the identity helper's project prefix. `--selector` captures a component; `--vision` checks colour deficiencies; `--no-autofocus` prevents gallery jumps. `--probe` returns bounds, overflow, tap sizes, covered controls and console/request errors. It never dumps localStorage. Inspect captured images as well as the probe: geometry cannot judge visual quality.

Use `cdp.mjs` and `probePage` to write game-specific walkthroughs separately. No game policy or tutorial walker ships here. One game uses one colour theme; colour-scheme emulation is a browser diagnostic only.

Standalone tests (no browser or npm packages needed): `node --test tools/chrome/*.test.mjs`.

Use the frontend URL printed by `self_host.py` as `--origin` or `BGD_ORIGIN`.
Without an explicit origin the tool reads `.self-host/config.json`'s remembered
URL. It never assumes the Go backend serves pages. Hosting may scan away from
configured component ports; the actual ports persist in that same state file.
For a separate controlled test frontend, always pass its actual origin. The
probe reports the page URL it inspected.
