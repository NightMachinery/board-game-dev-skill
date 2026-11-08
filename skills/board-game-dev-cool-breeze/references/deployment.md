# Deployment and self-hosting

`templates/self_host.py` implements the owner's hosting contract ([requirements.md](requirements.md),
"Self-hosting and intranet use") on the serving host itself. Once production runs on a small or
shared host, add a `ship` step: build once on the development machine from a fixed commit, copy that
one artifact to each host in turn, check it, and keep a rollback. The template leaves `ship` out
because it needs private target details, which belong in gitignored config.

A redeploy, in order: build once from a fixed commit; run a read-only compatibility scan of stored
rooms against the candidate; stop the writer; scan again; back up room data; swap the binary and
static build; start; check `/health` reports the expected build; run the production smoke suite
from a stated vantage point. On failure, restart the old binary with its old configuration.

## Lessons

Each lesson is a rule and its reason. The label says how strong the evidence was: *seen once* (one concrete finding), *seen repeatedly* (recurring failures or independent checks across subsystems), or *owner decision* (an accepted preference, which a new owner may change).

- **10.01** Provide a small self-hosting command set for setup, start, stop, redeploy, development and status, with clear documentation. Prefer a lightweight local runtime and process supervisor appropriate to the host rather than adding services the product does not need. *(owner decision)*

- **10.02** Make lifecycle commands idempotent and mutually exclusive, stopping either previous run mode before starting another. Persist locally chosen ports and configuration so repeat deployments do not depend on remembered shell commands. *(seen repeatedly)*

- **10.03** Serve fonts and required assets locally, derive socket scheme from the current page and provide clipboard fallbacks on plain HTTP. Intranet play must not depend on a public font CDN, authentication service or secure-context-only convenience API. *(owner decision)*

- **10.04** Build a self-contained release on the development or build machine and ship a target-compatible binary to small hosts. Compiling on a shared production host consumes scarce memory, disk and toolchain headroom. *(seen repeatedly)*

- **10.05** For a multi-host release, build once from a fixed source state and deploy the same artifact sequentially. Per-host rebuilds allowed a mid-release commit to produce different reported versions. *(seen repeatedly)*

- **10.06** Keep deployment targets, credentials, machine details and remembered flags in ignored or external configuration. Generic scripts can remain public without publishing an operator's infrastructure map. *(seen repeatedly)*

- **10.07** Pass proxy and required runtime environment explicitly without hardcoding it into scripts. Test boot commands in a minimal environment because interactive shells and supervisors often load different paths and variables. *(seen repeatedly)*

- **10.08** Treat reverse-proxy configuration as a shared resource: back it up, prove the running baseline matches, adapt the intended edit, then load only that change. A wrong configuration path can replace unrelated live sites. *(seen repeatedly)*

- **10.09** Resolve configuration placeholders in the service's actual environment and account for file-path-sensitive adaptation. A configuration valid in the running service can fail or mean something different in an SSH command's environment. *(seen once)*

- **10.10** Run a read-only candidate compatibility scan before stopping production, and repeat it after shutdown before swapping binaries. The second pass closes races with active moves and prevents silently archiving in-progress games. *(seen repeatedly)*

- **10.11** Back up room data only after the writer stops, retain bounded backups and preserve a rollback path. Deploy failure should restart the old binary with its prior configuration rather than leave a half-installed release. *(seen repeatedly)*

- **10.12** Preserve unknown future records and distinguish unsupported data, invalid replay and harmless diagnostic hash refresh. A generic redeploy must not “repair” data it does not understand. *(seen repeatedly)*

- **10.13** Gate new creation separately from loading and continuing supported stored games. A disabled feature should not make existing rooms impossible to resume or archive. *(seen repeatedly)*

- **10.14** Put a generated content hash in every changing asset URL and revalidate stable entry documents. Cache headers alone cannot guarantee that an intermediary or service worker will deliver a changed script promptly. *(seen repeatedly)*

- **10.15** Keep live API and WebSocket paths outside offline caches, and bound runtime art and audio caches. An installable shell can work offline without pretending that server-authoritative gameplay does. *(seen repeatedly)*

- **10.16** Verify the public health endpoint's expected build version and run a bounded real-UI smoke after deployment. Report the probe's vantage point and surface persistent TLS or routing errors instead of hiding them in retry loops. *(seen repeatedly)*

- **10.17** Derive production capacity from measured worst relevant tables, spectators, slow clients and mixed workloads on the target host. A laptop strength benchmark or historical cheaper bot cannot justify new concurrent-room limits. *(seen repeatedly)*

- **10.18** Once deployment authority is granted, deploy ready gated work without asking for the same permission after every change. Keep feature-release readiness and any temporary play-session deployment freeze as explicit independent constraints. *(owner decision)*

- **10.19** Support explicit HTTP and HTTPS hosting policy, including redirects or a deliberate dual-scheme exception, and print the final served URL. In restricted networks the usual secure-only assumptions may prevent players from reaching an otherwise healthy game. *(owner decision)*
