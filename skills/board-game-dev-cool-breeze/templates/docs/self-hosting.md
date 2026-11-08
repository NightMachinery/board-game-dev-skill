# Caddy and tmux hosting

Copy `self_host.py`, `tools/heavy.py`, `tools/project.json` and this document
into the game. Add `.self-host/` to the project's gitignore before running.
Install Go, Node, pnpm, tmux and Caddy on the host; no Docker or root command
is used. The Makefile's exported `GOTOOLCHAIN` is the single pin source; `self_host.py`
reads it, with an explicit exact-version environment override when needed. Commit `pnpm-lock.yaml` at the project root.

Adapt `hosting` in `tools/project.json`: Go package, backend CLI arguments,
health path, source directories and static output. `hosting.static` chooses
`caddy` (default) or `embedded`. Arguments support `{server_port}`, `{origin}`,
`{static_dir}` and `{data_dir}`. The backend must bind loopback and return HTTP
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

`setup` and `redeploy` copy source to a private `.self-host/candidates/` tree,
install frozen dependencies there, build a candidate binary and static output,
and health-check the candidate on a free port before stopping either live mode.
The probe runs in its own tmux session with disposable data. Only a successful
candidate causes both modes to stop, the binary/static paths to swap, and the
new instance to start. A failed install, build or candidate check leaves the old
processes, binary and served static directory untouched. Previous files remain
beside the candidate for recovery; a partial file swap restores them. Candidate
sources/backups use disk space; track their retention in the private run ledger.

`start` serves the existing build; `dev-start` rebuilds Go and switches Caddy to
Vite. These two commands still stop production and development first. Use `dev-start` on a local development
machine unless the owner requests production. Uncommon component ports come
from project config, scan forward when occupied and persist after success.
`--strictPort` makes a Vite port race fail visibly. macOS Vite binds localhost.

With `hosting.static: "caddy"`, Caddy serves the static files and proxies only
backend routes. With `"embedded"`, Caddy proxies every production request to
Go, which serves the build itself. Both choices use Vite for development.
For Go embedding, optionally set `hosting.embed_dir` to the repo-relative
`go:embed` input directory and `hosting.server_build_args` to build flags
(such as an embed build tag). The candidate build copies its static output
there before compiling Go. The server can alternatively serve the directory
from `BGD_STATIC_DIR` or a `{static_dir}` CLI argument. Use `{data_dir}` or
`BGD_DATA_DIR` for storage: these point to disposable data during candidate
checks and `.self-host/data` when serving. Never hardcode a live database path
in candidate CLI flags. All source/build directories must be project-relative.

Build isolation and an HTTP health probe do not implement application-specific
stored-game compatibility scans, stopped-writer backups, migrations or automatic
service rollback after a startup failure. Add those for the game's durable-data
contract before claiming production upgrade safety. This template preserves
previous files, cleans failed new processes and reports startup failure.

The block in `~/Caddyfile`
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

After finishing and committing work, update the adopted game's local/dev
instance inside tmux session `<repo-name>-setup`, wait 120 seconds, then inspect
its logs. Use `python3 self_host.py dev-start` for a local development instance;
use `redeploy` for a local built instance. Confirm the remembered URL belongs
to that local/dev instance. Production redeployment requires deployment authority
explicitly granted by the owner; this post-commit rule does not grant it.
Keep the setup session distinct from component sessions. Do not deploy while
testing the template or from an isolated worker checkout.

All assets and fonts must be local, all changing URLs content-hashed by the
build/index generator. No remote CDN, captcha or external font dependency.
Apply one selected theme pack at a time; a dark pack is an explicit theme
choice, never an OS-triggered mode switch.

Standalone tests: `python3 -m unittest`. They mock subprocesses and Caddy and
never edit the user's Caddyfile or start a service. Actual deployment remains
an adoption check on the configured host.
