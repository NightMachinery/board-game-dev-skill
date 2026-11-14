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
import fnmatch
import glob
import hashlib
import http.client
import json
import os
import platform
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import time
import tempfile
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
def go_toolchain(env=None):
    """The Makefile is the pin source; an explicit environment pin overrides it."""
    env = os.environ if env is None else env
    value = env.get('GOTOOLCHAIN')
    if not value:
        makefile = ROOT / 'Makefile'
        if not makefile.exists():
            makefile = ROOT / 'Makefile.template'  # Standalone template tests.
        match = re.search(r'^export\s+GOTOOLCHAIN\s*:?=\s*(\S+)', makefile.read_text(), re.M)
        value = match.group(1) if match else ''
    if not re.fullmatch(r'go[0-9]+\.[0-9]+\.[0-9]+', value):
        raise ValueError('export an exact GOTOOLCHAIN pin in Makefile or environment')
    return value


GO_TOOLCHAIN = go_toolchain()
CADDY_LAYOUT_CHOICES = ('inline', 'fragment')
_DEFAULT_CADDY_LAYOUT = 'inline'
_DEFAULT_CADDYFILE = Path.home() / 'Caddyfile'
_DEFAULT_CADDY_SITES = Path.home() / '.config' / 'caddy' / 'managed-sites' / 'sites.caddy'
CADDY_LAYOUT = os.environ.get('BGD_CADDY_LAYOUT') or _DEFAULT_CADDY_LAYOUT
CADDYFILE = Path(os.environ.get('BGD_CADDYFILE') or _DEFAULT_CADDYFILE).expanduser()
CADDY_SITES = Path(os.environ.get('BGD_CADDY_SITES') or _DEFAULT_CADDY_SITES).expanduser()
CADDY_LOCK_DIR: Path | None = None
_INITIAL_CADDY_LAYOUT = CADDY_LAYOUT
_INITIAL_CADDYFILE = CADDYFILE
_INITIAL_CADDY_SITES = CADDY_SITES
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
            (key in PROXY_ENV_NAMES or key in ('PATH', 'GOTOOLCHAIN', 'BGD_SERVER', 'PORT', 'HOST', 'GOMEMLIMIT', 'BGD_STATIC_DIR', 'BGD_DATA_DIR'))
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
        return (text.rstrip() + '\n\n' + block) if text.strip() else block
    a = text.index(BEGIN)
    b = text.index(END) + len(END)
    if b < a:
        raise RuntimeError('reversed managed Caddy markers')
    return text[:a] + block.rstrip('\n') + text[b:]


def render_caddy_block(site, mode, ports):
    if mode not in ('prod', 'dev'):
        raise ValueError('unknown mode')
    static = HOSTING.get('static', 'caddy')
    if static not in ('caddy', 'embedded'):
        raise ValueError('hosting.static must be caddy or embedded')
    if mode == 'prod' and static == 'embedded':
        body = f"    reverse_proxy localhost:{ports['server']}"
    else:
        frontend = (f'\t\treverse_proxy localhost:{ports["dev"]}' if mode == 'dev' else
                    f'\t\troot * {json.dumps(str(STATIC_DIR))}\n'
                    '\t\theader Cache-Control "no-cache"\n'
                    '\t\ttry_files {path} /200.html\n\t\tfile_server')
        body = f'''    @backend path /api /api/* /ws /health
    handle @backend {{
        reverse_proxy localhost:{ports['server']}
    }}
    handle {{
{frontend}
    }}'''
    return f'''{BEGIN}
{site.opposite_origin} {{
    redir {site.origin}{{uri}} permanent
}}
{site.origin} {{
    encode zstd gzip
{body}
}}
{END}
'''


def guarded(kind, argv, *, cwd=ROOT):
    env = os.environ.copy()
    env.pop('HEAVY_NOTIFY', None)  # Build steps must finish before switching modes.
    env['GOTOOLCHAIN'] = GO_TOOLCHAIN
    run([sys.executable, ROOT / 'tools/heavy.py', 'run', '--kind', kind, '--wait', '3600', '--',
         *argv], cwd=cwd, env=env)


@dataclass(frozen=True)
class Candidate:
    root: Path
    tree: Path
    binary: Path
    static: Path


def project_path(tree, configured):
    """Resolve build paths inside the candidate, never into the live checkout."""
    relative = Path(configured)
    result = (tree / relative).resolve()
    if relative.is_absolute() or not result.is_relative_to(tree.resolve()):
        raise ValueError('hosting source/build paths must stay inside the project')
    return result


def build(install=False):
    """Build only in a separate source tree, leaving all live paths untouched."""
    STATE.mkdir(exist_ok=True)
    candidates = STATE / 'candidates'
    candidates.mkdir(exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='release-', dir=candidates))
    tree = staging / 'source'
    excluded = {STATE.resolve(), STATIC_DIR.resolve(), (ROOT / 'server/bin').resolve()}
    def ignore(directory, names):
        return [name for name in names if name in
                ('.git', '.self-host', 'node_modules', '.svelte-kit', '__pycache__', '.cache')
                or (Path(directory) / name).resolve() in excluded]
    # Copy symlink targets rather than retaining links back into the live tree.
    shutil.copytree(ROOT, tree, ignore=ignore)
    if not (tree / 'pnpm-lock.yaml').is_file():
        raise RuntimeError('a committed root pnpm-lock.yaml is required')
    server = project_path(tree, HOSTING['server_dir'])
    web = project_path(tree, HOSTING['web_dir'])
    static = project_path(tree, HOSTING['static_dir'])
    if install:
        guarded('install', ['pnpm', 'install', '--frozen-lockfile'], cwd=tree)
        guarded('install', ['go', 'mod', 'download'], cwd=server)
    guarded('build', ['pnpm', '--dir', str(web), 'build'], cwd=tree)
    if not (static / '200.html').is_file():
        raise RuntimeError('candidate requires adapter-static fallback 200.html')
    if HOSTING.get('static', 'caddy') == 'embedded' and HOSTING.get('embed_dir'):
        destination = project_path(tree, HOSTING['embed_dir'])
        if destination == static or destination.is_relative_to(static) or static.is_relative_to(destination):
            raise ValueError('embed_dir must be separate from the static build directory')
        if destination.exists():
            shutil.rmtree(destination)  # Only the newly copied candidate's embed output.
        shutil.copytree(static, destination)
    binary = staging / NAME
    build_server(output=binary, cwd=server)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError('candidate binary missing or not executable')
    return Candidate(staging, tree, binary, static)


def build_server(*, output=None, cwd=None):
    destination = Path(output) if output is not None else BIN
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidate = destination.with_suffix('.new')
    guarded('build', ['go', 'build', '-trimpath', *HOSTING.get('server_build_args', []),
                     '-o', str(candidate), HOSTING['server_package']], cwd=cwd or SERVER_DIR)
    candidate.replace(destination)


def install_candidate(candidate):
    """Swap after successful validation and stop. Restore files if a swap fails."""
    BIN.parent.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.parent.mkdir(parents=True, exist_ok=True)
    previous_bin = candidate.root / 'previous-binary'
    previous_static = candidate.root / 'previous-static'
    had_bin, had_static = BIN.exists(), STATIC_DIR.exists()
    installed_bin = installed_static = False
    try:
        if had_bin:
            BIN.replace(previous_bin)
        if had_static:
            STATIC_DIR.replace(previous_static)
        candidate.binary.replace(BIN)
        installed_bin = True
        candidate.static.replace(STATIC_DIR)
        installed_static = True
    except BaseException:
        if installed_static:
            STATIC_DIR.replace(candidate.static)
        if installed_bin:
            BIN.replace(candidate.binary)
        if previous_static.exists():
            previous_static.replace(STATIC_DIR)
        if previous_bin.exists():
            previous_bin.replace(BIN)
        raise


def server_args(ports, site, static, data):
    return [str(x).format(server_port=ports['server'], origin=site.origin,
                          static_dir=static, data_dir=data) for x in HOSTING['server_args']]


def check_candidate(candidate, site):
    """Probe the new binary on an unused port with private disposable data."""
    ports = allocate_ports({k: PROJECT['ports'][k] for k in ('server', 'dev')})
    session = f'{NAME}-candidate'
    data = candidate.root / 'check-data'
    data.mkdir(exist_ok=True)
    try:
        tmuxnew(session, [str(candidate.binary), *server_args(ports, site, candidate.static, data)],
                cwd=candidate.tree, env={'GOTOOLCHAIN': GO_TOOLCHAIN,
                'BGD_STATIC_DIR': str(candidate.static), 'BGD_DATA_DIR': str(data)})
        wait_health(ports['server'], HOSTING['health_path'])
        if HOSTING.get('static', 'caddy') == 'embedded':
            wait_health(ports['server'], '/')
        run(['tmux', 'has-session', '-t', session])
    finally:
        run(['tmux', 'kill-session', '-t', session], check=False, capture=True)


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
    data = STATE / 'data'
    data.mkdir(exist_ok=True)
    args = server_args(ports, site, STATIC_DIR, data)
    session = SESSIONS[0] if mode == 'prod' else SESSIONS[1]
    tmuxnew(session, [str(BIN), *args], env={'GOTOOLCHAIN': GO_TOOLCHAIN,
            'BGD_STATIC_DIR': str(STATIC_DIR), 'BGD_DATA_DIR': str(data)})
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


def deploy(command, url=None, *, caddy_layout=None, caddyfile=None, caddy_sites=None):
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
    caddy_config = resolve_caddy_config(previous, caddy_layout=caddy_layout,
                                        caddyfile=caddyfile, caddy_sites=caddy_sites)
    site = parse_site_url(url or previous.get('url') or default_url())
    mode = 'dev' if command == 'dev-start' else 'prod'
    # Refuse an unrelated shared Caddy before stopping the game.
    imported_files = validate_fragment_setup(caddy_config)[0] if caddy_config.layout == 'fragment' else ()
    if caddy_config.caddyfile.exists():
        address = caddy_admin_address(caddy_config.caddyfile)
        if address is None:
            raise RuntimeError('this template needs a local TCP Caddy admin listener')
        try:
            check_caddy_serves(
                address,
                caddy_config.caddyfile.read_bytes(),
                caddyfile=caddy_config.caddyfile,
                known_aliases=known_caddy_aliases(caddy_config, imported_files),
            )
        except CaddyUnreachable:
            pass
    caddy_stamp = proxy_stamp(caddy_config)
    candidate = None
    if command in ('setup', 'redeploy'):
        candidate = build(install=True)
        check_candidate(candidate, site)
    if proxy_stamp(caddy_config) != caddy_stamp:
        raise RuntimeError('proxy config drift')
    # No stopping or live path mutation happens before the candidate passes.
    stop_sessions()
    if candidate is not None:
        install_candidate(candidate)
    elif mode == 'dev':
        build_server()
    # tmux kill-session can return before listener teardown completes.
    preferred = previous.get('ports', {k: PROJECT['ports'][k] for k in ('server', 'dev')})
    until = time.monotonic() + 3
    while time.monotonic() < until and not all(port_free(int(v)) for v in preferred.values()):
        time.sleep(.1)
    ports = allocate_ports(preferred)
    if mode == 'prod' and not (STATIC_DIR / '200.html').is_file():
        raise RuntimeError('static build is missing; run setup')
    try:
        start_components(mode, site, ports)
        apply_caddy(site, mode, ports, caddy_config=caddy_config)
    except BaseException:
        stop_sessions()
        raise
    STATE.mkdir(exist_ok=True)
    temp = CONFIG_FILE.with_suffix('.tmp')
    temp.write_text(json.dumps({'url': site.origin, 'mode': mode, 'ports': ports,
                                **caddy_config.to_saved()}, indent=2) + '\n')
    temp.replace(CONFIG_FILE)
    print(f'Serving {site.origin}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('setup', 'redeploy', 'start', 'stop', 'dev-start', 'status'))
    parser.add_argument('--url', help='public or intranet http(s) origin, remembered locally')
    parser.add_argument('--caddy-layout', choices=CADDY_LAYOUT_CHOICES,
                        help='Caddy edit layout: inline block in --caddyfile or imported --caddy-sites fragment')
    parser.add_argument('--caddyfile', help='path to full top-level Caddyfile')
    parser.add_argument('--caddy-sites', help='path to managed Caddy sites fragment (requires fragment layout)')
    args = parser.parse_args()
    try:
        with deployment_lock():
            deploy(args.command, args.url,
                   caddy_layout=args.caddy_layout, caddyfile=args.caddyfile, caddy_sites=args.caddy_sites)
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


class CaddyLoadOld(RuntimeError):
    """An uncertain /load reply resolved to the unchanged previous config."""


class CaddyLoadUnknown(RuntimeError):
    """An uncertain /load reply left Caddy's running state unknown."""


@dataclass(frozen=True)
class CaddyConfig:
    layout: str
    caddyfile: Path
    caddy_sites: Path

    @property
    def target_file(self) -> Path:
        return self.caddy_sites if self.layout == 'fragment' else self.caddyfile

    def to_saved(self) -> dict[str, str]:
        data = {'caddy_layout': self.layout, 'caddyfile': str(self.caddyfile)}
        if self.layout == 'fragment':
            data['caddy_sites'] = str(self.caddy_sites)
        return data


@dataclass(frozen=True)
class _ImportDirective:
    pattern: str
    args: tuple[str, ...]
    line_no: int


_CADDY_PLACEHOLDER_RE = re.compile(r'\{\$([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}')
_SNIPPET_DEF_RE = re.compile(r'^\(([^)]+)\)$')


def abs_user_path(value: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(value))))


def resolve_caddy_config(previous=None, *, caddy_layout=None, caddyfile=None, caddy_sites=None, env=None) -> CaddyConfig:
    env = os.environ if env is None else env
    prev = previous or {}
    if caddy_layout is not None:
        layout = caddy_layout
    elif env.get('BGD_CADDY_LAYOUT'):
        layout = env['BGD_CADDY_LAYOUT']
    elif prev.get('caddy_layout'):
        layout = prev['caddy_layout']
    else:
        layout = CADDY_LAYOUT
    if layout not in CADDY_LAYOUT_CHOICES:
        raise ValueError("caddy layout must be 'inline' or 'fragment'")

    if (caddy_sites is not None or env.get('BGD_CADDY_SITES')) and layout != 'fragment':
        raise ValueError('--caddy-sites and BGD_CADDY_SITES require --caddy-layout fragment')

    if caddyfile is not None:
        top = abs_user_path(caddyfile)
    elif env.get('BGD_CADDYFILE'):
        top = abs_user_path(env['BGD_CADDYFILE'])
    elif prev.get('caddyfile'):
        top = abs_user_path(prev['caddyfile'])
    else:
        top = abs_user_path(CADDYFILE)

    if caddy_sites is not None:
        sites = abs_user_path(caddy_sites)
    elif env.get('BGD_CADDY_SITES'):
        sites = abs_user_path(env['BGD_CADDY_SITES'])
    elif prev.get('caddy_sites'):
        sites = abs_user_path(prev['caddy_sites'])
    else:
        sites = abs_user_path(CADDY_SITES)

    return CaddyConfig(layout=layout, caddyfile=top, caddy_sites=sites)


def _tokenize_caddyfile_line(raw: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    n = len(raw)
    while i < n:
        while i < n and raw[i].isspace():
            i += 1
        if i >= n or raw[i] == '#':
            break
        if raw[i] == '"':
            i += 1
            buf = []
            while i < n:
                ch = raw[i]
                if ch == '\\' and i + 1 < n:
                    buf.append(raw[i + 1])
                    i += 2
                elif ch == '"':
                    i += 1
                    break
                else:
                    buf.append(ch)
                    i += 1
            tokens.append(''.join(buf))
        elif raw[i] == '`':
            i += 1
            end = raw.find('`', i)
            if end == -1:
                tokens.append(raw[i:])
                break
            tokens.append(raw[i:end])
            i = end + 1
        else:
            start = i
            while i < n and not raw[i].isspace():
                i += 1
            tokens.append(raw[start:i])
    return tokens


def scan_top_level_imports(text: str) -> tuple[list[_ImportDirective], set[str]]:
    """Extract top-level `import` directives and `(snippet)` names without a full parser."""
    imports: list[_ImportDirective] = []
    snippets: set[str] = set()
    depth = 0
    for line_no, raw in enumerate(text.splitlines(), 1):
        tokens = _tokenize_caddyfile_line(raw)
        if not tokens:
            continue
        if depth == 0:
            snippet_match = _SNIPPET_DEF_RE.match(tokens[0])
            if snippet_match and len(tokens) == 2 and tokens[1] == '{':
                snippets.add(snippet_match.group(1))
            elif tokens[0] == 'import' and len(tokens) >= 2:
                imports.append(_ImportDirective(tokens[1], tuple(tokens[2:]), line_no))
        for tok in tokens:
            if tok == '{':
                depth += 1
            elif tok == '}':
                depth -= 1
                if depth < 0:
                    raise ValueError(f'unmatched closing brace in Caddyfile line {line_no}')
    return imports, snippets


def _expand_caddy_placeholders(pattern: str, env: dict[str, str] | os._Environ) -> tuple[str | None, bool]:
    """Expand {$VAR} and {$VAR:default} from env. Returns (expanded_or_none, resolved_bool)."""
    unresolved = False

    def repl(match: re.Match[str]) -> str:
        nonlocal unresolved
        name, default = match.group(1), match.group(2)
        value = env.get(name)
        if value:
            return value
        if default is not None:
            return default
        unresolved = True
        return match.group(0)

    expanded = _CADDY_PLACEHOLDER_RE.sub(repl, pattern)
    return (None, False) if unresolved else (expanded, True)


def _has_glob_magic(path_text: str) -> bool:
    return any(ch in path_text for ch in '*?[')


def _dir_matches(dir_pattern: str, target_dir: Path) -> bool:
    norm_pat = os.path.normpath(dir_pattern)
    norm_target = os.path.normpath(str(target_dir))
    if not _has_glob_magic(norm_pat):
        if norm_pat == norm_target:
            return True
        return Path(norm_pat).resolve() == target_dir.resolve()
    return fnmatch.fnmatchcase(norm_target, norm_pat) or fnmatch.fnmatchcase(str(target_dir.resolve()), norm_pat)


def _pattern_matches_target(expanded: str, target: Path) -> bool:
    norm_exp = os.path.normpath(expanded)
    if not _has_glob_magic(norm_exp):
        if norm_exp == os.path.normpath(str(target)):
            return True
        return Path(norm_exp).resolve() == target.resolve()
    dir_part, name_pat = os.path.split(norm_exp)
    if not dir_part:
        return False
    return _dir_matches(dir_part, target.parent) and fnmatch.fnmatchcase(target.name, name_pat)


def _check_unsafe_glob(dir_part: str, name_pat: str, target: Path, raw_pattern: str, *, check_dir: bool) -> None:
    if not _has_glob_magic(name_pat):
        return
    if check_dir and not _dir_matches(dir_part, target.parent):
        return
    for unsafe_name in (target.name + '.lock', target.name + '.before', target.name + '.candidate', 'Caddyfile.before'):
        if unsafe_name == 'Caddyfile.before' and check_dir:
            continue
        if fnmatch.fnmatchcase(unsafe_name, name_pat):
            raise ValueError(
                f'import pattern {raw_pattern!r} would also ingest lock or backup files; '
                'use *.caddy or an explicit file path'
            )


def _collect_matched_files(expanded: str) -> list[Path]:
    norm_exp = os.path.normpath(expanded)
    if _has_glob_magic(norm_exp):
        return sorted(abs_user_path(p) for p in glob.glob(norm_exp) if os.path.isfile(p))
    candidate = abs_user_path(norm_exp)
    return [candidate] if candidate.is_file() else []


def validate_fragment_setup(caddy_config: CaddyConfig, *, env=None) -> tuple[tuple[Path, ...], int, int]:
    """Validate fragment-mode paths, top-level single import, and marker hygiene.

    Supported top-level import boundary: literal absolute paths or patterns
    whose {$VAR} placeholders (such as {$HOME}) resolve completely in the
    caller's environment. Unresolved top-level import placeholders and relative
    import paths are rejected before any mutation because exact-once inclusion
    and sibling import membership cannot otherwise be proved.
    """
    env = os.environ if env is None else env
    top = caddy_config.caddyfile
    sites = caddy_config.caddy_sites
    if sites.is_symlink():
        raise RuntimeError(f'managed Caddy fragment cannot be a symlink: {sites}')
    if abs_user_path(sites) == abs_user_path(top) or sites.resolve() == top.resolve():
        raise RuntimeError('managed Caddy fragment cannot equal or resolve to top-level Caddyfile')
    if not top.exists() or not top.is_file():
        raise RuntimeError(f'top-level Caddyfile not found for fragment mode: {top}')
    top_text = top.read_text()
    if BEGIN in top_text or END in top_text:
        raise RuntimeError(
            f'managed Caddy markers already exist in top-level {top}; remove or migrate them before using fragment mode'
        )

    imports, snippets = scan_top_level_imports(top_text)
    resolved_matches = 0
    imported_files: list[Path] = []
    seen_imported: set[Path] = set()

    for imp in imports:
        pat = imp.pattern
        is_snippet = (not imp.args and pat in snippets and '/' not in pat and '\\' not in pat
                      and not _has_glob_magic(pat) and not pat.endswith('.caddy') and '{$' not in pat)
        if is_snippet:
            continue
        expanded, resolved = _expand_caddy_placeholders(pat, env)
        if not resolved:
            raise ValueError(
                f'unresolved environment placeholder in top-level Caddyfile import {pat!r} is not supported; '
                'ensure the variable is set identically for both caller and Caddy or use an absolute path'
            )
        assert expanded is not None
        if not os.path.isabs(expanded):
            raise ValueError(f'relative import path in Caddyfile is not supported: {pat}')
        dir_part, name_pat = os.path.split(os.path.normpath(expanded))
        _check_unsafe_glob(dir_part, name_pat, sites, pat, check_dir=True)
        if _pattern_matches_target(expanded, sites):
            if imp.args:
                raise ValueError(f'import of managed fragment {sites} must not pass arguments')
            resolved_matches += 1
        for matched in _collect_matched_files(expanded):
            if matched not in seen_imported:
                seen_imported.add(matched)
                imported_files.append(matched)
            if matched.resolve() != sites.resolve():
                sibling_text = matched.read_text()
                if BEGIN in sibling_text or END in sibling_text:
                    raise RuntimeError(
                        f'duplicate managed Caddy markers found in sibling imported file {matched}'
                    )

    if resolved_matches > 1:
        raise RuntimeError(f'{top} imports {sites} more than once')
    if resolved_matches == 0:
        raise RuntimeError(f'{top} does not import {sites}')

    if sites.exists():
        sites_text = sites.read_text()
        if sites_text.count(BEGIN) != sites_text.count(END) or sites_text.count(BEGIN) > 1:
            raise RuntimeError('duplicate or unmatched managed Caddy markers')
        if BEGIN in sites_text and sites_text.index(END) < sites_text.index(BEGIN):
            raise RuntimeError('reversed managed Caddy markers')

    return tuple(sorted(imported_files)), resolved_matches, 0


def _file_digest_entry(path: Path, *, allow_symlink: bool) -> list[object] | None:
    if not allow_symlink and path.is_symlink():
        raise RuntimeError('release symlinks require explicit adoption')
    if not path.exists():
        return None
    st = path.stat()
    return [str(path), str(path.resolve()), st.st_mode, hashlib.sha256(path.read_bytes()).hexdigest()]


def proxy_stamp(caddy_config: CaddyConfig | None = None, *, env=None):
    """Fingerprint top-level Caddyfile, managed fragment, and statically resolved imports."""
    cfg = resolve_caddy_config() if caddy_config is None else caddy_config
    if cfg.layout == 'inline':
        return ('inline', str(cfg.caddyfile), _file_digest_entry(cfg.caddyfile, allow_symlink=False))
    imported_files, _, _ = validate_fragment_setup(cfg, env=env)
    payload = {
        'layout': 'fragment',
        'top': _file_digest_entry(cfg.caddyfile, allow_symlink=True),
        'sites': _file_digest_entry(cfg.caddy_sites, allow_symlink=False),
        'imports': [_file_digest_entry(p, allow_symlink=True) for p in imported_files],
    }
    return ('fragment', hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())


def known_caddy_aliases(caddy_config: CaddyConfig, imported_files: tuple[Path, ...] = ()) -> dict[str, str]:
    """Map known Caddy config/import paths and their resolved counterparts to canonical paths."""
    aliases: dict[str, str] = {}
    for path in (caddy_config.caddyfile, caddy_config.caddy_sites, *imported_files):
        canonical = str(path.resolve())
        aliases[str(path)] = canonical
        aliases[os.path.normpath(str(path))] = canonical
        aliases[canonical] = canonical
    return aliases


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


def caddy_admin_address(caddyfile: Path | None = None) -> str | None:
    """The host:port of the admin API the Caddyfile's own global options
    name, or Caddy's default when they name none: the Caddy that `caddy
    reload` would talk to. None when the file turns the admin API off or
    puts it on a Unix socket.

    `caddy adapt` reads the file the way Caddy does. When it fails here,
    which an unset {$VAR} can cause, the global options block is read as
    text instead (scanned_admin_address), so the file still goes to the
    running Caddy, which adapts it with its own environment.
    """
    target = CADDYFILE if caddyfile is None else caddyfile
    adapted = subprocess.run(
        ["caddy", "adapt", "--config", str(target), "--adapter", "caddyfile"],
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
        return scanned_admin_address(target.read_text() if target.exists() else "")
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


def _with_known_hide_aliases(config: object, aliases: dict[str, str] | None) -> object:
    if not aliases:
        return config
    if isinstance(config, list):
        return [_with_known_hide_aliases(item, aliases) for item in config]
    if not isinstance(config, dict):
        return config
    out = {key: _with_known_hide_aliases(value, aliases) for key, value in config.items()}
    if config.get("handler") == "file_server" and isinstance(config.get("hide"), list):
        out["hide"] = [aliases.get(str(item), item) for item in config["hide"]]
    return out


def same_config(a: object, b: object) -> bool:
    return with_hide_lists_sorted(a) == with_hide_lists_sorted(b)


def _same_config_with_aliases(a: object, b: object, aliases: dict[str, str] | None = None) -> bool:
    if not aliases:
        return same_config(a, b)
    return same_config(_with_known_hide_aliases(a, aliases), _with_known_hide_aliases(b, aliases))


def _check_caddy_serves_snapshot(
    address: str,
    before: bytes | None,
    *,
    caddyfile: Path | None = None,
    known_aliases: dict[str, str] | None = None,
) -> tuple[str, object, object]:
    target = CADDYFILE if caddyfile is None else caddyfile
    running = caddy_admin_request(address, "/config/")
    if before is None:
        if running not in (None, {}):
            raise CaddyMismatch(f"{target} is new, but the Caddy on {address} already serves a config")
        return str(target), None, running
    adapted = adapt_in_caddy(address, before)
    found = hide_paths_for_adapted_text(adapted, running, set())
    hide_path = next(iter(found)) if len(found) == 1 else str(target)
    adapted_hidden = with_config_file_hidden(adapted, hide_path)
    if len(found) > 1 or not _same_config_with_aliases(adapted_hidden, running, known_aliases):
        raise CaddyMismatch(
            f"the Caddy on {address} does not serve {target} as it stands: the path may be wrong "
            "(check --caddyfile), another Caddy may own that admin address, the file may import relative "
            "paths, or it may hold edits Caddy has not loaded yet (reload Caddy with it first)"
        )
    return hide_path, adapted_hidden, running


def check_caddy_serves(
    address: str,
    before: bytes | None,
    *,
    caddyfile: Path | None = None,
    known_aliases: dict[str, str] | None = None,
    _snapshot_out: dict[str, object] | None = None,
) -> str:
    """Raise CaddyMismatch unless the running Caddy on address serves the
    Caddyfile text before (None for a file not created yet, which needs a
    Caddy with no config). Loads nothing. Returns the path the running
    Caddy hides its config file by (see load_through_caddy)."""
    hide_path, adapted_hidden, _ = _check_caddy_serves_snapshot(
        address, before, caddyfile=caddyfile, known_aliases=known_aliases
    )
    if _snapshot_out is not None:
        _snapshot_out['adapted'] = adapted_hidden
    return hide_path


def _collect_handlers(obj: object, dials: set[str], hide_files: set[str]) -> None:
    if isinstance(obj, list):
        for item in obj:
            _collect_handlers(item, dials, hide_files)
        return
    if not isinstance(obj, dict):
        return
    handler = obj.get("handler")
    if handler == "reverse_proxy":
        for upstream in obj.get("upstreams") or ():
            if isinstance(upstream, dict) and upstream.get("dial"):
                dials.add(str(upstream["dial"]))
    elif handler == "file_server":
        for item in obj.get("hide") or ():
            hide_files.add(str(item))
    for value in obj.values():
        _collect_handlers(value, dials, hide_files)


def verify_fragment_in_adapted(adapted: object, site: Site, mode: str, ports: dict[str, int], caddy_sites: Path) -> None:
    """Confirm the adapted full Caddy JSON actually contains this game's rendered routes."""
    if not isinstance(adapted, dict):
        raise CaddyMismatch(f"adapted Caddy configuration is invalid for {caddy_sites}")
    servers = (adapted.get("apps") or {}).get("http", {}).get("servers") or {}
    host_names = {site.host, f"[{site.host}]"}
    dials: set[str] = set()
    hide_files: set[str] = set()
    matched_host = False
    for server in servers.values():
        if not isinstance(server, dict):
            continue
        for route in server.get("routes") or ():
            if not isinstance(route, dict):
                continue
            matches = route.get("match") or ()
            if any(isinstance(m, dict) and any(h in host_names for h in (m.get("host") or ())) for m in matches):
                matched_host = True
                _collect_handlers(route.get("handle"), dials, hide_files)
    expected_dials = {f"localhost:{ports['server']}"}
    if mode == 'dev':
        expected_dials.add(f"localhost:{ports['dev']}")
    if not matched_host or not expected_dials.issubset(dials):
        raise CaddyMismatch(
            f"adapted top-level Caddyfile did not include {site.origin} from managed fragment {caddy_sites}"
        )
    if mode == 'prod' and HOSTING.get('static', 'caddy') == 'caddy':
        accepted_hides = {str(caddy_sites), str(caddy_sites.resolve()), os.path.normpath(str(caddy_sites))}
        if not ((hide_files & accepted_hides) or any(abs_user_path(h).resolve() == caddy_sites.resolve() for h in hide_files)):
            raise CaddyMismatch(
                f"adapted top-level Caddyfile did not serve static files from managed fragment {caddy_sites}"
            )


def load_through_caddy(
    address: str,
    before: bytes | None,
    *,
    caddyfile: Path | None = None,
    before_adapted: object = None,
    hide_path: str | None = None,
    known_aliases: dict[str, str] | None = None,
    verify_candidate=None,
    verify_source=None,
) -> None:
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
    target = CADDYFILE if caddyfile is None else caddyfile
    if hide_path is None:
        hide_path, before_adapted, _ = _check_caddy_serves_snapshot(
            address, before, caddyfile=target, known_aliases=known_aliases
        )
    elif before_adapted is not None:
        current_running = caddy_admin_request(address, "/config/")
        if not _same_config_with_aliases(before_adapted, current_running, known_aliases):
            raise CaddyMismatch(
                f"the Caddy on {address} changed before loading {target}"
            )
    if verify_source is not None:
        verify_source()
    edited = with_config_file_hidden(adapt_in_caddy(address, target.read_bytes()), hide_path)
    if verify_candidate is not None:
        verify_candidate(edited)
    if verify_source is not None:
        verify_source()
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
            raise CaddyLoadUnknown(
                f"the reply to the load was lost ({exc}), and Caddy could not be asked whether it took ({again})"
            ) from again
        if _same_config_with_aliases(now, edited, known_aliases):
            return
        if before_adapted is not None and _same_config_with_aliases(now, before_adapted, known_aliases):
            raise CaddyLoadOld(
                f"the reply to the load was lost ({exc}), and Caddy still runs the previous config"
            ) from exc
        raise CaddyLoadUnknown(
            f"the reply to the load was lost ({exc}), and Caddy runs an unexpected config"
        ) from exc


def _caddy_lock_dir(env=None) -> Path:
    source = os.environ if env is None else env
    if CADDY_LOCK_DIR is not None:
        raw = abs_user_path(CADDY_LOCK_DIR)
    elif source.get('BGD_CADDY_LOCK_DIR'):
        raw = abs_user_path(source['BGD_CADDY_LOCK_DIR'])
    elif source.get('XDG_STATE_HOME'):
        raw = abs_user_path(source['XDG_STATE_HOME']) / 'bgd-self-host' / 'caddy-locks'
    else:
        home = Path(source['HOME']) if source.get('HOME') else Path.home()
        raw = abs_user_path(home / '.local' / 'state' / 'bgd-self-host' / 'caddy-locks')
    if raw.is_symlink():
        raise RuntimeError(f'Caddy lock directory cannot be a symlink: {raw}')
    raw.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = raw.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise RuntimeError(f'unsafe Caddy lock directory ownership or type: {raw}')
    if stat.S_IMODE(info.st_mode) != 0o700:
        os.chmod(raw, 0o700)
        info = raw.lstat()
        if stat.S_IMODE(info.st_mode) != 0o700:
            raise RuntimeError(f'unsafe Caddy lock directory permissions: {raw}')
    return raw.resolve()


@contextlib.contextmanager
def _caddy_locks(caddy_config: CaddyConfig):
    """Serialize cooperating self_host.py callers across layouts and aliases.

    Uses a private per-user lock directory independent of the top Caddyfile's
    parent so fragment mode works with a read-only top directory, plus the
    legacy sibling `<Caddyfile>.lock` in inline mode. Multi-lock acquisition
    always follows sorted canonical path order to avoid deadlock. Assumes
    cooperating callers use these locks; uncoordinated external edits are
    detected by source-stamp rechecks.
    """
    lock_dir = _caddy_lock_dir()
    top_canonical = caddy_config.caddyfile.resolve()
    top_digest = hashlib.sha256(str(top_canonical).encode()).hexdigest()[:24]
    paths: set[Path] = {lock_dir / f'caddy-{top_digest}.lock'}
    if caddy_config.layout == 'inline':
        caddy_config.caddyfile.parent.mkdir(parents=True, exist_ok=True)
        legacy_parent = Path(os.path.realpath(caddy_config.caddyfile.parent))
        paths.add(legacy_parent / (caddy_config.caddyfile.name + '.lock'))
    else:
        sites_canonical = caddy_config.caddy_sites.resolve()
        sites_digest = hashlib.sha256(str(sites_canonical).encode()).hexdigest()[:24]
        paths.add(lock_dir / f'caddy-{sites_digest}.lock')
    lock_paths = sorted(paths, key=str)
    with contextlib.ExitStack() as stack:
        for lock_path in lock_paths:
            if lock_path.is_symlink():
                raise RuntimeError(f'Caddy lock file cannot be a symlink: {lock_path}')
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            fh = stack.enter_context(os.fdopen(fd, 'r+'))
            fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def _capture_file_state(path: Path, *, allow_symlink: bool) -> dict[str, object] | None:
    if not allow_symlink and path.is_symlink():
        raise RuntimeError(f'managed Caddy file cannot be a symlink: {path}')
    try:
        lst = path.lstat()
    except FileNotFoundError:
        return None
    if not allow_symlink and stat.S_ISLNK(lst.st_mode):
        raise RuntimeError(f'managed Caddy file cannot be a symlink: {path}')
    st = path.stat()
    if not stat.S_ISREG(st.st_mode):
        raise RuntimeError(f'managed Caddy path is not a regular file: {path}')
    data = path.read_bytes()
    return {
        'path': str(path),
        'resolved': str(path.resolve()),
        'is_symlink': stat.S_ISLNK(lst.st_mode),
        'lstat_id': (lst.st_dev, lst.st_ino),
        'stat_id': (st.st_dev, st.st_ino),
        'mode': stat.S_IMODE(st.st_mode),
        'sha256': hashlib.sha256(data).hexdigest(),
        'bytes': data,
    }


def _file_identity_digest(state: dict[str, object] | None) -> tuple | None:
    if state is None:
        return None
    return (
        state['resolved'],
        state['is_symlink'],
        state['lstat_id'],
        state['stat_id'],
        state['mode'],
        state['sha256'],
    )


def _capture_caddy_source_snapshot(cfg: CaddyConfig) -> dict[str, object]:
    if cfg.layout == 'inline':
        target_state = _capture_file_state(cfg.caddyfile, allow_symlink=False)
        return {
            'layout': 'inline',
            'top': target_state,
            'target': target_state,
            'imported': (),
            'imported_paths': (),
            'siblings': {},
        }
    imported_files, _, _ = validate_fragment_setup(cfg)
    top_state = _capture_file_state(cfg.caddyfile, allow_symlink=True)
    target_state = _capture_file_state(cfg.caddy_sites, allow_symlink=False)
    target_resolved = str(cfg.caddy_sites.resolve())
    siblings = {}
    for p in imported_files:
        p_resolved = str(p.resolve())
        if p_resolved != target_resolved:
            siblings[p_resolved] = _file_identity_digest(_capture_file_state(p, allow_symlink=True))
    return {
        'layout': 'fragment',
        'top': top_state,
        'target': target_state,
        'imported': tuple(str(p.resolve()) for p in imported_files),
        'imported_paths': imported_files,
        'siblings': siblings,
    }


def _verify_baseline_source(cfg: CaddyConfig, baseline: dict[str, object]) -> None:
    current = _capture_caddy_source_snapshot(cfg)
    if _file_identity_digest(current['top']) != _file_identity_digest(baseline['top']):
        raise RuntimeError(f'top-level Caddyfile changed outside lock before write: {cfg.caddyfile}')
    if _file_identity_digest(current['target']) != _file_identity_digest(baseline['target']):
        raise RuntimeError(f'owned Caddy target changed outside lock before write: {cfg.target_file}')
    if current['siblings'] != baseline['siblings'] or current['imported'] != baseline['imported']:
        raise RuntimeError('imported Caddy files changed outside lock before write')


def _write_owned_target(target: Path, data: bytes, *, expected_state: dict[str, object] | None) -> dict[str, object]:
    if target.is_symlink():
        raise RuntimeError(f'owned Caddy target cannot be a symlink: {target}')
    target.parent.mkdir(parents=True, exist_ok=True)
    if expected_state is None:
        if target.exists():
            raise RuntimeError(f'owned Caddy target appeared outside lock: {target}')
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        try:
            with os.fdopen(fd, 'wb') as fh:
                fh.write(data)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
    else:
        mode = int(expected_state['mode'])
        fd, tmp_name = tempfile.mkstemp(prefix=f'.{target.name}.', suffix='.tmp', dir=target.parent)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, 'wb') as fh:
                fh.write(data)
            os.chmod(tmp_path, mode)
            current = _capture_file_state(target, allow_symlink=False)
            if _file_identity_digest(current) != _file_identity_digest(expected_state):
                raise RuntimeError(f'owned Caddy target changed outside lock before write: {target}')
            os.replace(tmp_path, target)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
    written_state = _capture_file_state(target, allow_symlink=False)
    if written_state is None or written_state['bytes'] != data:
        raise RuntimeError(f'failed to verify written Caddy target: {target}')
    return written_state


def _verify_post_write_source(cfg: CaddyConfig, baseline: dict[str, object], written_state: dict[str, object]) -> None:
    target = cfg.target_file
    current_target = _capture_file_state(target, allow_symlink=False)
    if _file_identity_digest(current_target) != _file_identity_digest(written_state):
        raise RuntimeError(f'owned Caddy target changed outside lock before load: {target}')
    if cfg.layout == 'fragment':
        imported_files, _, _ = validate_fragment_setup(cfg)
        current_top = _capture_file_state(cfg.caddyfile, allow_symlink=True)
        if _file_identity_digest(current_top) != _file_identity_digest(baseline['top']):
            raise RuntimeError(f'top-level Caddyfile changed outside lock before load: {cfg.caddyfile}')
        target_resolved = str(cfg.caddy_sites.resolve())
        current_siblings = {}
        for p in imported_files:
            p_resolved = str(p.resolve())
            if p_resolved != target_resolved:
                current_siblings[p_resolved] = _file_identity_digest(_capture_file_state(p, allow_symlink=True))
        if current_siblings != baseline['siblings']:
            raise RuntimeError('imported Caddy sibling files changed outside lock before load')


def _restore_caddy_target(
    target: Path,
    before_bytes: bytes | None,
    expected_written: bytes,
    *,
    expected_state: dict[str, object] | None = None,
) -> None:
    if target.is_symlink():
        raise RuntimeError(f'owned Caddy target became a symlink outside lock; refusing overwrite: {target}')
    if not target.exists():
        raise RuntimeError(f'owned Caddy target disappeared before rollback: {target}')
    if expected_state is not None:
        current = _capture_file_state(target, allow_symlink=False)
        if _file_identity_digest(current) != _file_identity_digest(expected_state):
            raise RuntimeError(f'owned Caddy target changed outside lock; refusing overwrite: {target}')
    elif target.read_bytes() != expected_written:
        raise RuntimeError(f'owned Caddy target changed outside lock; refusing overwrite: {target}')
    if before_bytes is None:
        target.unlink()
    else:
        _write_owned_target(target, before_bytes, expected_state=expected_state)


def _verify_runtime_restored(
    address: str,
    before_top: bytes | None,
    before_adapted: object | None,
    caddy_config: CaddyConfig,
    known_aliases: dict[str, str],
) -> None:
    if before_adapted is not None:
        now = caddy_admin_request(address, "/config/")
        if not _same_config_with_aliases(now, before_adapted, known_aliases):
            raise CaddyMismatch(f"running Caddy on {address} does not match pre-edit config after rollback")
    else:
        check_caddy_serves(address, before_top, caddyfile=caddy_config.caddyfile, known_aliases=known_aliases)


def apply_caddy(site, mode, ports, *, caddy_config: CaddyConfig | None = None):
    cfg = resolve_caddy_config() if caddy_config is None else caddy_config
    with _caddy_locks(cfg):
        baseline = _capture_caddy_source_snapshot(cfg)
        imported_files = baseline['imported_paths']
        aliases = known_caddy_aliases(cfg, imported_files)
        target = cfg.target_file
        before_top = baseline['top']['bytes'] if baseline['top'] is not None else None
        before_target = baseline['target']['bytes'] if baseline['target'] is not None else None
        address = (
            caddy_admin_address(cfg.caddyfile)
            if (cfg.layout == 'fragment' or before_top is not None)
            else CADDY_DEFAULT_ADMIN
        )
        if address is None:
            raise RuntimeError('a local TCP Caddy admin listener is required')
        running = True
        hide_path = None
        snapshot_out: dict[str, object] = {}
        try:
            # Capture pre-mutation adapted JSON BEFORE modifying target or imports.
            hide_path = check_caddy_serves(
                address,
                before_top,
                caddyfile=cfg.caddyfile,
                known_aliases=aliases,
                _snapshot_out=snapshot_out,
            )
        except CaddyUnreachable:
            running = False
        before_adapted = snapshot_out.get('adapted')
        _verify_baseline_source(cfg, baseline)
        text = replace_block(before_target.decode() if before_target is not None else '', render_caddy_block(site, mode, ports))
        written_bytes = text.encode()
        STATE.mkdir(exist_ok=True)
        if cfg.layout == 'inline':
            if before_target is not None:
                (STATE / 'Caddyfile.before').write_bytes(before_target)
            else:
                (STATE / 'Caddyfile.before').unlink(missing_ok=True)
            (STATE / 'Caddyfile.candidate').write_bytes(written_bytes)
        else:
            if before_top is not None:
                (STATE / 'caddy-top.before').write_bytes(before_top)
            if before_target is not None:
                (STATE / 'caddy-sites.before').write_bytes(before_target)
            else:
                (STATE / 'caddy-sites.before').unlink(missing_ok=True)
            (STATE / 'caddy-sites.candidate').write_bytes(written_bytes)
        written_state = _write_owned_target(target, written_bytes, expected_state=baseline['target'])
        try:
            if running:
                verify_cb = (
                    (lambda edited: verify_fragment_in_adapted(edited, site, mode, ports, cfg.caddy_sites))
                    if cfg.layout == 'fragment' else None
                )
                load_through_caddy(
                    address,
                    before_top,
                    caddyfile=cfg.caddyfile,
                    before_adapted=before_adapted,
                    hide_path=hide_path,
                    known_aliases=aliases,
                    verify_candidate=verify_cb,
                    verify_source=lambda: _verify_post_write_source(cfg, baseline, written_state),
                )
            else:
                _verify_post_write_source(cfg, baseline, written_state)
                run(['caddy', 'validate', '--config', cfg.caddyfile, '--adapter', 'caddyfile'])
                _verify_post_write_source(cfg, baseline, written_state)
                tmuxnew(f'{NAME}-caddy', ['caddy', 'run', '--config', cfg.caddyfile, '--adapter', 'caddyfile'])
                deadline = time.monotonic() + 10
                while True:
                    try:
                        check_caddy_serves(address, cfg.caddyfile.read_bytes(), caddyfile=cfg.caddyfile, known_aliases=aliases)
                        break
                    except CaddyUnreachable:
                        if time.monotonic() >= deadline:
                            raise RuntimeError('Caddy failed to start; read its tmux log') from None
                        time.sleep(.2)
        except BaseException as exc:
            if isinstance(exc, CaddyLoadUnknown):
                raise
            try:
                _restore_caddy_target(target, before_target, written_bytes, expected_state=written_state)
            except BaseException as restore_exc:
                raise RuntimeError(
                    f'{exc}; target rollback failed ({restore_exc}); backups preserved in {STATE}'
                ) from exc
            if running:
                try:
                    _verify_runtime_restored(address, before_top, before_adapted, cfg, aliases)
                except BaseException as verify_exc:
                    raise RuntimeError(
                        f'{exc}; restored {target}, but runtime verification failed ({verify_exc}); '
                        f'backups preserved in {STATE}'
                    ) from exc
            if isinstance(exc, CaddyLoadOld):
                raise CaddyLoadOld(
                    f'{exc}; restored {target} and verified previous config still running'
                ) from exc
            raise


if __name__ == '__main__':
    raise SystemExit(main())


