# Caddy and tmux hosting

Copy `self_host.py`, `tools/heavy.py`, `tools/project.json` and this document
into the game. Add `.self-host/` to the project's gitignore before running.
Install Go, Node, pnpm, tmux and Caddy on the host; no Docker or root command
is used. The build pins `GOTOOLCHAIN` to the constant in `self_host.py` and
the Makefile. Commit `pnpm-lock.yaml` at the project root.

Adapt `hosting` in `tools/project.json`: Go package, backend CLI arguments,
health path, source directories and static output. Arguments support
`{server_port}` and `{origin}`. The backend must bind loopback and return HTTP
200 from its health endpoint. Configure SvelteKit adapter-static with
`fallback: '200.html'`; the client owns page navigation, Go owns room state.
Configure Vite's `/ws`, `/api` and `/health` proxy from `BGD_SERVER`, including
WebSocket forwarding. This template rebuilds Go when entering development;
restart `dev-start` after backend edits. Client edits use Vite's hot reload.

Set `BGD_DEFAULT_DOMAIN`; the default is
`https://<project-name>.<BGD_DEFAULT_DOMAIN>`. `BGD_DEFAULT_HOST` overrides the
short project label. These variables never name a remote deployment machine.
Alternatively pass `--url http://your-intranet-name` or an HTTPS origin.
The URL is remembered in private `.self-host/config.json`. Configure DNS and
network access for that URL separately. Run on the actual serving host, so
port checks inspect the right machine. Remote shipping is deliberately omitted.

```sh
python3 self_host.py setup --url http://localhost
python3 self_host.py dev-start
python3 self_host.py status
python3 self_host.py redeploy
python3 self_host.py stop
python3 self_host.py start
```

`setup` stops both modes, installs frozen dependencies, builds and starts.
`redeploy` does the same rebuild and restart. `start` serves the existing
production build; `dev-start` rebuilds Go and switches Caddy to Vite. Both
stop production and development first. Use `dev-start` on a local development
machine unless the owner requests production. Uncommon component ports come
from project config, scan forward when occupied and persist after success.
`--strictPort` makes a Vite port race fail visibly. macOS Vite binds localhost.

Caddy itself serves the production static files and proxies only backend
routes. Development proxies the frontend to Vite. The block in `~/Caddyfile`
has an explicit redirect from the opposite scheme to the chosen URL. For a
custom URL port, the opposite scheme uses its normal port. HTTPS needs working
certificate provisioning, or a locally trusted intranet certificate. Plain
HTTP requires neither and the clipboard helper works there too.

`BGD_CADDYFILE` chooses a different shared file. Only this game's marked
block is replaced. A file lock serializes shared edits. A running Caddy
adapts before/after text using its own environment; the script verifies that
its current configuration matches the original file before loading anything.
A rejected change restores the file. A missing or mismatched file never
replaces another Caddy's sites. A new Caddy starts in `<project>-caddy` tmux;
an existing shared Caddy stays in its owner's session. The template requires
a local TCP admin listener. It leaves shared Caddy running on `stop`, while
stopping this game's backend and client development processes.

Every managed process uses kill-session followed by `tmux new -d -s`, with
explicit `-e VAR=value` for present proxy and runtime variables. Proxy settings
are optional and never stored in config or logs. Logs are `.self-host/*.log`.
The final URL prints only after components and Caddy are ready. No remote
target, credential, hostname or proxy address belongs in committed files.

After finishing and committing work, launch `python3 self_host.py redeploy`
inside tmux session `<repo-name>-setup`, wait 120 seconds, then inspect that
session's logs. Do this only for the actual adopted game, never while testing
the template. Keep the setup session distinct from component sessions.

All assets and fonts must be local, all changing URLs content-hashed by the
build/index generator. No remote CDN, captcha or external font dependency.
Apply one selected theme pack at a time; a dark pack is an explicit theme
choice, never an OS-triggered mode switch.

Standalone tests: `python3 -m unittest`. They mock subprocesses and Caddy and
never edit the user's Caddyfile or start a service. Actual deployment remains
an adoption check on the configured host.
