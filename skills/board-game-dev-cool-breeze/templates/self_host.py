#!/usr/bin/env python3
"""Copy to the project root; adapt tools/project.json, then read docs/self-hosting.md.

Local Caddy and tmux hosting. Run this script on the machine that will serve
the game. No implicit remote target, container, global install or root command.
"""
from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import http.client
import json
import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
PROJECT = json.loads(Path(os.environ.get('BGD_PROJECT_CONFIG', ROOT / 'tools/project.json')).read_text())
NAME = PROJECT['name']
if not re.fullmatch(r'[a-z][a-z0-9-]*', NAME):
    raise ValueError('project name must be a lowercase slug')
HOSTING = PROJECT['hosting']
STATE = ROOT / '.self-host'
CONFIG_FILE = STATE / 'config.json'
BIN = STATE / 'bin' / NAME
SERVER_DIR = ROOT / HOSTING['server_dir']
WEB_DIR = ROOT / HOSTING['web_dir']
STATIC_DIR = ROOT / HOSTING['static_dir']
GO_TOOLCHAIN = 'go1.26.3'  # Pin this and Makefile.template together, with server/go.mod.
CADDYFILE = Path(os.environ.get('BGD_CADDYFILE', Path.home() / 'Caddyfile')).expanduser()
CADDY_DEFAULT_ADMIN = 'localhost:2019'  # Caddy's standard local admin listener.
CADDY_LOAD_TIMEOUT = 10.0
CADDY_PROBE_TIMEOUT = 2.0
CADDY_RECHECK_DELAY = 1.0
ADAPTED_TEXT_HIDE = './Caddyfile'
BEGIN = f'# BEGIN {NAME} self_host.py'
END = f'# END {NAME} self_host.py'
SESSIONS = tuple(f'{NAME}-{suffix}' for suffix in ('server', 'dev-server', 'dev-web'))
PROXY_ENV_NAMES = (
    'ALL_PROXY', 'all_proxy', 'HTTP_PROXY', 'http_proxy', 'HTTPS_PROXY',
    'https_proxy', 'NO_PROXY', 'no_proxy', 'npm_config_proxy', 'npm_config_https_proxy'
)


@dataclass(frozen=True)
class Site:
    scheme: str
    host: str
    port: int | None = None

    @property
    def authority(self):
        host = f'[{self.host}]' if ':' in self.host else self.host
        return f'{host}:{self.port}' if self.port else host

    @property
    def origin(self):
        return f'{self.scheme}://{self.authority}'

    @property
    def opposite_origin(self):
        # The opposite scheme uses its standard port, avoiding a plaintext
        # and TLS listener fighting over an explicitly chosen port.
        host = f'[{self.host}]' if ':' in self.host else self.host
        return f'{"http" if self.scheme == "https" else "https"}://{host}'


def parse_site_url(value: str) -> Site:
    u = urlparse(value)
    if (u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password
            or u.path not in ('', '/') or u.query or u.fragment
            or not re.fullmatch(r'[A-Za-z0-9.:\-]+', u.hostname)):
        raise ValueError('URL must be an http(s) origin without credentials, path or query')
    port = u.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError('invalid URL port')
    return Site(u.scheme, u.hostname, port)


def default_url(env=None):
    env = os.environ if env is None else env
    domain = env.get('BGD_DEFAULT_DOMAIN')
    if not domain:
        raise ValueError('set BGD_DEFAULT_DOMAIN or pass --url (plain HTTP works)')
    host = env.get('BGD_DEFAULT_HOST') or NAME
    return parse_site_url(f'https://{host}.{domain}').origin


def run(argv, *, cwd=ROOT, check=True, capture=False, env=None):
    return subprocess.run([str(x) for x in argv], cwd=cwd, check=check, text=True,
                          capture_output=capture, env=env)


def tmux_env_args(env=None):
    source = os.environ if env is None else env
    return [item for key, value in source.items() if value and
            (key in PROXY_ENV_NAMES or key in ('PATH', 'GOTOOLCHAIN', 'BGD_SERVER', 'PORT', 'HOST', 'GOMEMLIMIT'))
            for item in ('-e', f'{key}={value}')]


def tmuxnew(session, argv, *, cwd=ROOT, env=None):
    # Kill then create, never silently attach to an old deployment.
    run(['tmux', 'kill-session', '-t', session], check=False, capture=True)
    STATE.mkdir(exist_ok=True)
    log = STATE / f'{session}.log'
    command = f'exec {shlex.join([str(x) for x in argv])} >{shlex.quote(str(log))} 2>&1'
    run(['tmux', 'new', '-d', '-s', session, '-c', str(cwd),
         *tmux_env_args(os.environ | (env or {})), command])


def stop_sessions():
    for session in SESSIONS:
        run(['tmux', 'kill-session', '-t', session], check=False, capture=True)


def port_free(port):
    # Bind both families so a wildcard IPv6 listener cannot be overlooked.
    for family, host in ((socket.AF_INET, '127.0.0.1'), (socket.AF_INET6, '::1')):
        try:
            with socket.socket(family) as sock:
                if family == socket.AF_INET6:
                    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                sock.bind((host, port))
        except OSError as e:
            if family == socket.AF_INET6 and e.errno in (errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL):
                continue
            return False
    return True


def allocate_ports(preferred, is_free=port_free):
    chosen = {}
    for key in ('server', 'dev'):
        start = int(preferred[key])
        if not 1024 <= start <= 65535:
            raise ValueError('component ports must be in 1024..65535')
        for candidate in list(range(start, min(start + 200, 65536))):
            if candidate not in chosen.values() and is_free(candidate):
                chosen[key] = candidate
                break
        else:
            raise RuntimeError(f'no free {key} port near {start}')
    return chosen


def replace_block(text, block):
    if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
        raise RuntimeError('duplicate or unmatched managed Caddy markers')
    if BEGIN not in text:
        return text.rstrip() + '\n\n' + block
    a = text.index(BEGIN)
    b = text.index(END) + len(END)
    if b < a:
        raise RuntimeError('reversed managed Caddy markers')
    return text[:a] + block.rstrip('\n') + text[b:]


def render_caddy_block(site, mode, ports):
    if mode not in ('prod', 'dev'):
        raise ValueError('unknown mode')
    # handle preserves /api and /ws prefixes. Static output is adapter-static SPA
    # output with fallback 200.html; a different router can change try_files.
    frontend = (f'\t\treverse_proxy localhost:{ports["dev"]}' if mode == 'dev' else
                f'\t\troot * {json.dumps(str(STATIC_DIR))}\n'
                '\t\theader Cache-Control "no-cache"\n'
                '\t\ttry_files {path} /200.html\n\t\tfile_server')
    return f'''{BEGIN}
{site.opposite_origin} {{
    redir {site.origin}{{uri}} permanent
}}
{site.origin} {{
    encode zstd gzip
    @backend path /api /api/* /ws /health
    handle @backend {{
        reverse_proxy localhost:{ports['server']}
    }}
    handle {{
{frontend}
    }}
}}
{END}
'''


def guarded(kind, argv, *, cwd=ROOT):
    env = os.environ.copy()
    env.pop('HEAVY_NOTIFY', None)  # Build steps must finish before switching modes.
    env['GOTOOLCHAIN'] = GO_TOOLCHAIN
    run([sys.executable, ROOT / 'tools/heavy.py', 'run', '--kind', kind, '--wait', '3600', '--',
         *argv], cwd=cwd, env=env)


def build(install=False):
    if not (ROOT / 'pnpm-lock.yaml').is_file():
        raise RuntimeError('a committed root pnpm-lock.yaml is required')
    if install:
        guarded('install', ['pnpm', 'install', '--frozen-lockfile'])
        guarded('install', ['go', 'mod', 'download'], cwd=SERVER_DIR)
    guarded('build', ['pnpm', '--dir', str(WEB_DIR), 'build'])
    if not (STATIC_DIR / '200.html').is_file():
        raise RuntimeError('configure adapter-static with fallback 200.html')
    build_server()


def build_server():
    BIN.parent.mkdir(parents=True, exist_ok=True)
    candidate = BIN.with_suffix('.new')
    guarded('build', ['go', 'build', '-trimpath', '-o', str(candidate), HOSTING['server_package']], cwd=SERVER_DIR)
    candidate.replace(BIN)


def wait_health(port, path, timeout=30):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    until = time.monotonic() + timeout
    last = None
    while time.monotonic() < until:
        try:
            with opener.open(f'http://127.0.0.1:{port}{path}', timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last = exc
        time.sleep(.2)
    raise RuntimeError(f'component did not become healthy on port {port}: {last}')


def start_components(mode, site, ports):
    if not BIN.is_file():
        raise RuntimeError('run setup or redeploy to build the backend first')
    server_args = [str(x).format(server_port=ports['server'], origin=site.origin)
                   for x in HOSTING['server_args']]
    session = SESSIONS[0] if mode == 'prod' else SESSIONS[1]
    tmuxnew(session, [str(BIN), *server_args], env={'GOTOOLCHAIN': GO_TOOLCHAIN})
    wait_health(ports['server'], HOSTING['health_path'])
    if mode == 'dev':
        host = 'localhost' if platform.system() == 'Darwin' else '0.0.0.0'
        tmuxnew(SESSIONS[2], ['pnpm', '--dir', str(WEB_DIR), 'dev', '--host', host,
                '--port', str(ports['dev']), '--strictPort'],
                env={'BGD_SERVER': f'http://127.0.0.1:{ports["server"]}'})
        wait_health(ports['dev'], '/')


@contextlib.contextmanager
def deployment_lock():
    STATE.mkdir(exist_ok=True)
    with (STATE / 'deploy.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('another hosting command is running') from None
        yield


def deploy(command, url=None):
    previous = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    if command == 'status':
        print(json.dumps(previous, indent=2))
        for session in SESSIONS:
            result = run(['tmux', 'has-session', '-t', session], check=False, capture=True)
            print(f'{session}: {"running" if result.returncode == 0 else "stopped"}')
        return
    if command == 'stop':
        stop_sessions()
        return
    site = parse_site_url(url or previous.get('url') or default_url())
    mode = 'dev' if command == 'dev-start' else 'prod'
    # Refuse an unrelated shared Caddy before stopping the game.
    if CADDYFILE.exists():
        address = caddy_admin_address()
        if address is None:
            raise RuntimeError('this template needs a local TCP Caddy admin listener')
        try:
            check_caddy_serves(address, CADDYFILE.read_bytes())
        except CaddyUnreachable:
            pass
    stop_sessions()  # Both modes stop first, including setup and redeploy.
    # tmux kill-session can return before listener teardown completes.
    preferred = previous.get('ports', {k: PROJECT['ports'][k] for k in ('server', 'dev')})
    until = time.monotonic() + 3
    while time.monotonic() < until and not all(port_free(int(v)) for v in preferred.values()):
        time.sleep(.1)
    ports = allocate_ports(preferred)
    if command in ('setup', 'redeploy'):
        build(install=True)
    elif mode == 'dev':
        build_server()
    if mode == 'prod' and not (STATIC_DIR / '200.html').is_file():
        raise RuntimeError('static build is missing; run setup')
    try:
        start_components(mode, site, ports)
        apply_caddy(site, mode, ports)
    except BaseException:
        stop_sessions()
        raise
    STATE.mkdir(exist_ok=True)
    temp = CONFIG_FILE.with_suffix('.tmp')
    temp.write_text(json.dumps({'url': site.origin, 'mode': mode, 'ports': ports}, indent=2) + '\n')
    temp.replace(CONFIG_FILE)
    print(f'Serving {site.origin}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('setup', 'redeploy', 'start', 'stop', 'dev-start', 'status'))
    parser.add_argument('--url', help='public or intranet http(s) origin, remembered locally')
    args = parser.parse_args()
    try:
        with deployment_lock():
            deploy(args.command, args.url)
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError,
            CaddyUnreachable, CaddyRejected, CaddyUnsure, CaddyMismatch) as exc:
        print(f'self-host: {exc}', file=sys.stderr)
        return 1
    return 0


# Caddy adaptation helpers and apply_caddy follow. Keep them independent of
# the project: a shared Caddy must keep its other sites and launcher environment.


class CaddyUnreachable(Exception):
    """No Caddy answered on the admin address."""


# Connect failures that mean no Caddy listens there. A name like localhost
# can resolve to an address this host cannot use (::1 without IPv6), and
# Python reports the error from the last address it tried, which is then
# not ECONNREFUSED.
NOTHING_LISTENS = frozenset(
    {errno.ECONNREFUSED, errno.EADDRNOTAVAIL, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EINVAL, errno.EAFNOSUPPORT}
)


class CaddyRejected(Exception):
    """The running Caddy refused a request (an error status), changing nothing."""


class CaddyUnsure(Exception):
    """A request reached Caddy but its reply was lost (a reset, a timeout), so
    Caddy may or may not have acted on it."""


class CaddyMismatch(Exception):
    """The Caddy on the admin address does not serve the Caddyfile as it stood
    before our edit, so loading the edited file there is not safe."""


def admin_listen_address(listen: str) -> str | None:
    """host:port for an admin listen address; None for a Unix socket or an
    address that is still a {$VAR} placeholder."""
    if listen.startswith("tcp/"):
        listen = listen[len("tcp/") :]
    return None if "/" in listen or "{" in listen else listen


def scanned_admin_address(text: str) -> str | None:
    """The admin address the global options block of Caddyfile text names,
    read as plain text: Caddy's default when the block names none, None for
    `admin off`, a Unix socket or a placeholder.

    Only for a file that does not adapt in this shell's environment (a
    {$VAR} placeholder the shell lacks can make an option invalid here)
    while the running Caddy, which has the variable, may still load it.
    """
    depth = 0
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if depth == 0:
            if line != "{":
                return CADDY_DEFAULT_ADMIN
            depth = 1
            continue
        tokens = line.split()
        if depth == 1 and tokens[0] == "admin":
            argument = tokens[1] if len(tokens) > 1 and tokens[1] != "{" else None
            if argument is None:
                return CADDY_DEFAULT_ADMIN
            return None if argument == "off" else admin_listen_address(argument)
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            return CADDY_DEFAULT_ADMIN
    return CADDY_DEFAULT_ADMIN


def caddy_admin_address() -> str | None:
    """The host:port of the admin API the Caddyfile's own global options
    name, or Caddy's default when they name none: the Caddy that `caddy
    reload` would talk to. None when the file turns the admin API off or
    puts it on a Unix socket.

    `caddy adapt` reads the file the way Caddy does. When it fails here,
    which an unset {$VAR} can cause, the global options block is read as
    text instead (scanned_admin_address), so the file still goes to the
    running Caddy, which adapts it with its own environment.
    """
    adapted = subprocess.run(
        ["caddy", "adapt", "--config", str(CADDYFILE), "--adapter", "caddyfile"],
        text=True,
        capture_output=True,
        check=False,
    )
    admin = None
    if adapted.returncode == 0:
        try:
            config = json.loads(adapted.stdout)
            admin = config.get("admin") or {} if isinstance(config, dict) else None
        except ValueError:
            admin = None
    if not isinstance(admin, dict):
        return scanned_admin_address(CADDYFILE.read_text() if CADDYFILE.exists() else "")
    if admin.get("disabled"):
        return None
    return admin_listen_address(str(admin.get("listen") or CADDY_DEFAULT_ADMIN))


def caddy_admin_opener() -> urllib.request.OpenerDirector:
    """An opener that never goes through a proxy: the admin API is local,
    and a host's https_proxy or http_proxy must not catch these requests."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def caddy_admin_request(
    address: str,
    path: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = CADDY_LOAD_TIMEOUT,
) -> object:
    """One request to the admin API on address (a POST when data is given),
    with the reply parsed as JSON (None for an empty reply).

    Raises CaddyRejected with Caddy's reason for an error status,
    CaddyUnreachable when the connection is refused (no Caddy listens), and
    CaddyUnsure for any other transport failure.
    """
    request = urllib.request.Request(
        f"http://{address}{path}", data=data, method="POST" if data is not None else "GET", headers=headers or {}
    )
    try:
        with caddy_admin_opener().open(request, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        with exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
        raise CaddyRejected(detail or f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        # urllib wraps what fails while connecting and sending; a connect
        # failure means nothing reached a Caddy.
        if isinstance(exc.reason, OSError) and exc.reason.errno in NOTHING_LISTENS:
            raise CaddyUnreachable(str(exc.reason)) from exc
        raise CaddyUnsure(str(exc.reason)) from exc
    except ConnectionRefusedError as exc:
        raise CaddyUnreachable(str(exc)) from exc
    except (OSError, http.client.HTTPException) as exc:
        raise CaddyUnsure(str(exc) or type(exc).__name__) from exc
    return json.loads(body) if body.strip() else None


def adapt_in_caddy(address: str, text: bytes) -> object:
    """Caddyfile text as the running Caddy adapts it to JSON (/adapt), with
    Caddy's own environment. Loads nothing."""
    reply = caddy_admin_request(address, "/adapt", data=text, headers={"Content-Type": "text/caddyfile"})
    if not isinstance(reply, dict) or "result" not in reply:
        raise CaddyRejected("Caddy's /adapt gave no result")
    return reply["result"]


def hide_paths_for_adapted_text(adapted: object, running: object, found: set[str]) -> set[str]:
    """The values running has wherever adapted has ADAPTED_TEXT_HIDE in a
    file_server's hide list: the path the running Caddy hides its config
    file by."""
    if isinstance(adapted, dict) and isinstance(running, dict):
        if adapted.get("handler") == "file_server":
            ours, theirs = adapted.get("hide"), running.get("hide")
            # Caddy orders the config files in a hide list differently from
            # one version to the next, so match them as sets.
            if isinstance(ours, list) and isinstance(theirs, list) and ADAPTED_TEXT_HIDE in ours:
                found.update(t for t in set(map(str, theirs)) - set(map(str, ours)))
        for key in adapted.keys() & running.keys():
            hide_paths_for_adapted_text(adapted[key], running[key], found)
    elif isinstance(adapted, list) and isinstance(running, list) and len(adapted) == len(running):
        for ours, theirs in zip(adapted, running):
            hide_paths_for_adapted_text(ours, theirs, found)
    return found


def with_config_file_hidden(config: object, path: str) -> object:
    """config with ADAPTED_TEXT_HIDE in every file_server's hide list
    replaced by path, as `caddy reload --config` would have hidden the file."""
    if isinstance(config, list):
        return [with_config_file_hidden(item, path) for item in config]
    if not isinstance(config, dict):
        return config
    out = {key: with_config_file_hidden(value, path) for key, value in config.items()}
    if config.get("handler") == "file_server" and isinstance(config.get("hide"), list):
        out["hide"] = [path if item == ADAPTED_TEXT_HIDE else item for item in config["hide"]]
    return out


def with_hide_lists_sorted(config: object) -> object:
    """config with every file_server hide list sorted, for comparing configs
    whose hide lists hold the same paths in another order."""
    if isinstance(config, list):
        return [with_hide_lists_sorted(item) for item in config]
    if not isinstance(config, dict):
        return config
    out = {key: with_hide_lists_sorted(value) for key, value in config.items()}
    if config.get("handler") == "file_server" and isinstance(config.get("hide"), list):
        out["hide"] = sorted(config["hide"], key=str)
    return out


def same_config(a: object, b: object) -> bool:
    return with_hide_lists_sorted(a) == with_hide_lists_sorted(b)


def check_caddy_serves(address: str, before: bytes | None) -> str:
    """Raise CaddyMismatch unless the running Caddy on address serves the
    Caddyfile text before (None for a file not created yet, which needs a
    Caddy with no config). Loads nothing. Returns the path the running
    Caddy hides its config file by (see load_through_caddy)."""
    running = caddy_admin_request(address, "/config/")
    if before is None:
        if running not in (None, {}):
            raise CaddyMismatch(f"{CADDYFILE} is new, but the Caddy on {address} already serves a config")
        return str(CADDYFILE)
    adapted = adapt_in_caddy(address, before)
    found = hide_paths_for_adapted_text(adapted, running, set())
    hide_path = next(iter(found)) if len(found) == 1 else str(CADDYFILE)
    if len(found) > 1 or not same_config(with_config_file_hidden(adapted, hide_path), running):
        raise CaddyMismatch(
            f"the Caddy on {address} does not serve {CADDYFILE} as it stands: the path may be wrong "
            "(check --caddyfile), another Caddy may own that admin address, the file may import relative "
            "paths, or it may hold edits Caddy has not loaded yet (reload Caddy with it first)"
        )
    return hide_path


def load_through_caddy(address: str, before: bytes | None) -> None:
    """Have the running Caddy on address load the edited Caddyfile, but only
    if it is the Caddy that serves the file as it stood before the edit.

    Caddy adapts both versions itself (/adapt), so a {$VAR} placeholder in
    the shared file resolves from Caddy's environment, as it did when Caddy
    started, whatever the shell running this script exports. Adapted text
    hides the config file by a relative stand-in (ADAPTED_TEXT_HIDE), so the
    path Caddy really hides it by is read from the running config and put
    back. The unedited version must then equal the running config (hide
    lists compared as sets; check_caddy_serves).
    If it does not, the file is not what this Caddy serves: a wrong path,
    another Caddy on the address, imports that resolve differently here, or
    edits not loaded yet. Then this raises CaddyMismatch before loading
    anything. The edited version, with the same hide path, goes to /load as
    JSON, which Caddy applies only if all of it provisions. When the reply
    to that is lost, the running config shows whether the load took.
    """
    hide_path = check_caddy_serves(address, before)
    edited = with_config_file_hidden(adapt_in_caddy(address, CADDYFILE.read_bytes()), hide_path)
    try:
        caddy_admin_request(
            address,
            "/load",
            data=json.dumps(edited).encode(),
            headers={"Content-Type": "application/json", "Cache-Control": "must-revalidate"},
        )
    except CaddyUnsure as exc:
        # Caddy restarts its admin listener after a load, so a lost reply
        # may follow a load that took: look at what Caddy runs now. Any
        # failure here is an unknown outcome, never a reason to treat Caddy
        # as down or as having refused.
        time.sleep(CADDY_RECHECK_DELAY)
        try:
            now = caddy_admin_request(address, "/config/")
        except (CaddyUnreachable, CaddyRejected, CaddyUnsure, ValueError) as again:
            raise RuntimeError(
                f"the reply to the load was lost ({exc}), and Caddy could not be asked whether it took ({again})"
            ) from again
        if not same_config(now, edited):
            raise RuntimeError(f"the reply to the load was lost ({exc}), and Caddy does not run the edited config") from exc


def apply_caddy(site, mode, ports):
    # Serialize edits to a shared Caddyfile across different game repositories.
    CADDYFILE.parent.mkdir(parents=True, exist_ok=True)
    with CADDYFILE.with_name(CADDYFILE.name + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        before = CADDYFILE.read_bytes() if CADDYFILE.exists() else None
        address = caddy_admin_address() if before is not None else CADDY_DEFAULT_ADMIN
        if address is None:
            raise RuntimeError('a local TCP Caddy admin listener is required')
        running = True
        try:
            check_caddy_serves(address, before)
        except CaddyUnreachable:
            running = False
        text = replace_block(before.decode() if before is not None else '', render_caddy_block(site, mode, ports))
        if before is not None:
            STATE.mkdir(exist_ok=True)
            (STATE / 'Caddyfile.before').write_bytes(before)
        CADDYFILE.write_text(text)
        try:
            if running:
                load_through_caddy(address, before)
            else:
                run(['caddy', 'validate', '--config', CADDYFILE, '--adapter', 'caddyfile'])
                tmuxnew(f'{NAME}-caddy', ['caddy', 'run', '--config', CADDYFILE, '--adapter', 'caddyfile'])
                deadline = time.monotonic() + 10
                while True:
                    try:
                        check_caddy_serves(address, CADDYFILE.read_bytes())
                        break
                    except CaddyUnreachable:
                        if time.monotonic() >= deadline:
                            raise RuntimeError('Caddy failed to start; read its tmux log') from None
                        time.sleep(.2)
        except BaseException:
            if before is None:
                CADDYFILE.unlink(missing_ok=True)
            else:
                CADDYFILE.write_bytes(before)
            raise


if __name__ == '__main__':
    raise SystemExit(main())


