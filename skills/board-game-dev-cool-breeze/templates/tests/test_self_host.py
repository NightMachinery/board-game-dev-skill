"""Standalone hosting contract tests; never start a server or edit a home file."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hosting_template', ROOT / 'self_host.py')
host = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = host
spec.loader.exec_module(host)


class HostingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        state = self.root / '.self-host'
        state.mkdir()
        config = dict(host.HOSTING, static='caddy', static_dir='build')
        for key, value in {'ROOT': self.root, 'STATE': state, 'CONFIG_FILE': state / 'config.json',
                           'CADDYFILE': self.root / 'Caddyfile', 'STATIC_DIR': self.root / 'build',
                           'BIN': state / 'bin/game', 'SERVER_DIR': self.root / 'server',
                           'WEB_DIR': self.root / 'web', 'HOSTING': config}.items():
            p = patch.object(host, key, value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_default_url_from_env_only(self):
        with self.assertRaisesRegex(ValueError, 'BGD_DEFAULT_DOMAIN'):
            host.default_url({})
        self.assertEqual(host.default_url({'BGD_DEFAULT_DOMAIN': 'example.test', 'BGD_DEFAULT_HOST': 'sample'}),
                         'https://sample.example.test')

    def test_reject_url_injection_and_credentials(self):
        for url in ('ftp://example.test', 'https://user:pass@example.test', 'https://example.test/path',
                    'https://example.test/?x=1', 'https://example.test#x', 'https://example.test/{uri}',
                    'https://example.test:99999', 'http://bad host'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                host.parse_site_url(url)

    def test_static_prod_and_explicit_scheme_redirects(self):
        ports = {'server': 42111, 'dev': 42112}
        for scheme, other in (('https', 'http'), ('http', 'https')):
            text = host.render_caddy_block(host.parse_site_url(f'{scheme}://example.test'), 'prod', ports)
            self.assertIn(f'{other}://example.test {{\n    redir {scheme}://example.test{{uri}} permanent', text)
            self.assertIn('file_server', text)
            self.assertIn('try_files {path} /200.html', text)
            self.assertIn('reverse_proxy localhost:42111', text)
            self.assertNotIn('localhost:42112', text)

    def test_dev_proxies_frontend_and_keeps_backend_matcher(self):
        text = host.render_caddy_block(host.parse_site_url('http://example.test'), 'dev', {'server': 1, 'dev': 2})
        self.assertIn('@backend path /api /api/* /ws /health', text)
        self.assertIn('reverse_proxy localhost:2', text)
        self.assertNotIn('file_server', text)

    def test_custom_url_port_does_not_collide_with_opposite_scheme(self):
        self.assertEqual(host.parse_site_url('http://example.test:42115').opposite_origin, 'https://example.test')

    def test_markers_preserve_other_sites_and_refuse_malformed_blocks(self):
        original = 'other.example.test {\n respond "ok"\n}\n'
        block = f'{host.BEGIN}\nnew\n{host.END}\n'
        result = host.replace_block(original, block)
        self.assertTrue(result.startswith(original))
        self.assertEqual(host.replace_block(result, block), result)
        for invalid in (host.BEGIN, host.END, f'{host.END}\n{host.BEGIN}', block + block):
            with self.assertRaises(RuntimeError):
                host.replace_block(invalid, block)

    def test_allocate_unique_ports_and_scan_when_taken(self):
        self.assertEqual(host.allocate_ports({'server': 42111, 'dev': 42111}, lambda x: x != 42111),
                         {'server': 42112, 'dev': 42113})
        with self.assertRaises(RuntimeError):
            host.allocate_ports({'server': 65535, 'dev': 65535}, lambda _: False)

    def test_proxy_values_optional_and_tmux_gets_explicit_environment(self):
        self.assertEqual(host.tmux_env_args({}), [])
        self.assertEqual(host.tmux_env_args({'HTTPS_PROXY': 'http://proxy.invalid', 'SECRET': 'hidden'}),
                         ['-e', 'HTTPS_PROXY=http://proxy.invalid'])
        with patch.object(host, 'run') as run:
            host.tmuxnew('sample-server', ['binary', 'a b'], env={'GOTOOLCHAIN': host.GO_TOOLCHAIN})
        self.assertEqual(run.call_args_list[0].args[0][:2], ['tmux', 'kill-session'])
        args = run.call_args_list[1].args[0]
        self.assertEqual(args[:3], ['tmux', 'new', '-d'])
        self.assertIn(f'GOTOOLCHAIN={host.GO_TOOLCHAIN}', args)
        self.assertIn("'a b'", args[-1])

    def test_build_and_check_before_stop_then_swap_and_start(self):
        for command in ('setup', 'redeploy'):
            events = []
            candidate = Mock()
            with self.subTest(command=command), patch.object(host, 'build', side_effect=lambda **kw: events.append('build') or candidate), \
                 patch.object(host, 'check_candidate', side_effect=lambda *a: events.append('check')), \
                 patch.object(host, 'stop_sessions', side_effect=lambda: events.append('stop')), \
                 patch.object(host, 'install_candidate', side_effect=lambda *a: events.append('swap')), \
                 patch.object(host, 'port_free', return_value=True), \
                 patch.object(host, 'allocate_ports', return_value={'server': 42111, 'dev': 42112}), \
                 patch.object(host, 'start_components', side_effect=lambda *a: events.append('start')), \
                 patch.object(host, 'apply_caddy'):
                host.STATIC_DIR.mkdir(exist_ok=True)
                (host.STATIC_DIR / '200.html').write_text('html')
                host.deploy(command, 'http://example.test')
                self.assertEqual(events, ['build', 'check', 'stop', 'swap', 'start'])
                self.assertEqual(json.loads(host.CONFIG_FILE.read_text())['ports']['server'], 42111)

    def test_failed_build_or_candidate_check_keeps_old_server_and_files(self):
        host.BIN.parent.mkdir(parents=True)
        host.BIN.write_text('old binary')
        host.STATIC_DIR.mkdir()
        (host.STATIC_DIR / '200.html').write_text('old html')
        for command in ('setup', 'redeploy'):
            for stage in ('build', 'check_candidate'):
                with self.subTest(command=command, stage=stage), patch.object(host, 'build') as build, \
                     patch.object(host, 'check_candidate') as check, patch.object(host, 'stop_sessions') as stop, \
                     patch.object(host, 'install_candidate') as swap, patch.object(host, 'start_components') as start:
                    (build if stage == 'build' else check).side_effect = RuntimeError('candidate failed')
                    with self.assertRaisesRegex(RuntimeError, 'candidate failed'):
                        host.deploy(command, 'http://example.test')
                    stop.assert_not_called(); swap.assert_not_called(); start.assert_not_called()
                    self.assertEqual(host.BIN.read_text(), 'old binary')
                    self.assertEqual((host.STATIC_DIR / '200.html').read_text(), 'old html')

    def test_start_and_dev_start_still_stop_both_modes_first(self):
        for command in ('start', 'dev-start'):
            events = []
            with self.subTest(command=command), patch.object(host, 'build') as build, \
                 patch.object(host, 'build_server', side_effect=lambda: events.append('build-server')), \
                 patch.object(host, 'stop_sessions', side_effect=lambda: events.append('stop')), \
                 patch.object(host, 'port_free', return_value=True), \
                 patch.object(host, 'start_components', side_effect=lambda *a: events.append('start')), \
                 patch.object(host, 'apply_caddy'):
                host.STATIC_DIR.mkdir(exist_ok=True)
                (host.STATIC_DIR / '200.html').touch()
                host.deploy(command, 'http://example.test')
                self.assertEqual(events, ['stop', 'build-server', 'start'] if command == 'dev-start' else ['stop', 'start'])
                build.assert_not_called()

    def test_candidate_build_has_separate_source_dependencies_binary_and_static_output(self):
        (self.root / 'pnpm-lock.yaml').write_text('lock')
        (self.root / 'server').mkdir(); (self.root / 'web').mkdir()
        host.BIN.parent.mkdir(parents=True); host.BIN.write_text('old binary')
        host.STATIC_DIR.mkdir(); (host.STATIC_DIR / '200.html').write_text('old html')
        def guarded(kind, argv, *, cwd):
            self.assertTrue(Path(cwd).resolve().is_relative_to((host.STATE / 'candidates').resolve()))
            if argv[0] == 'pnpm' and argv[-1] == 'build':
                (Path(cwd) / 'build').mkdir()
                (Path(cwd) / 'build/200.html').write_text('new html')
            if argv[:2] == ['go', 'build']:
                binary = Path(argv[argv.index('-o') + 1]); binary.write_text('new binary'); binary.chmod(0o755)
        with patch.object(host, 'guarded', side_effect=guarded) as commands:
            candidate = host.build(install=True)
        self.assertEqual(host.BIN.read_text(), 'old binary')
        self.assertEqual((host.STATIC_DIR / '200.html').read_text(), 'old html')
        self.assertEqual((candidate.static / '200.html').read_text(), 'new html')
        self.assertTrue(any(c.args[0] == 'install' for c in commands.call_args_list))
        host.install_candidate(candidate)
        self.assertEqual(host.BIN.read_text(), 'new binary')
        self.assertEqual((host.STATIC_DIR / '200.html').read_text(), 'new html')
        self.assertEqual((candidate.root / 'previous-binary').read_text(), 'old binary')

    def test_candidate_check_uses_private_data_and_cleans_its_session(self):
        candidate = host.Candidate(self.root, self.root, self.root / 'new-bin', self.root / 'new-static')
        with patch.object(host, 'allocate_ports', return_value={'server': 42111, 'dev': 42112}), \
             patch.object(host, 'tmuxnew') as tmux, patch.object(host, 'wait_health', side_effect=RuntimeError('bad')), \
             patch.object(host, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'bad'):
                host.check_candidate(candidate, host.parse_site_url('http://example.test'))
        self.assertEqual(tmux.call_args.kwargs['cwd'], candidate.tree)
        self.assertEqual(tmux.call_args.kwargs['env']['BGD_DATA_DIR'], str(self.root / 'check-data'))
        self.assertEqual(run.call_args.args[0][:2], ['tmux', 'kill-session'])

    def test_embedded_production_proxies_everything_but_dev_still_uses_vite(self):
        with patch.object(host, 'HOSTING', dict(host.HOSTING, static='embedded')):
            prod = host.render_caddy_block(host.parse_site_url('http://example.test'), 'prod', {'server': 42111, 'dev': 42112})
            self.assertIn('reverse_proxy localhost:42111', prod)
            self.assertNotIn('@backend', prod); self.assertNotIn('file_server', prod)
            dev = host.render_caddy_block(host.parse_site_url('http://example.test'), 'dev', {'server': 42111, 'dev': 42112})
            self.assertIn('@backend', dev); self.assertIn('reverse_proxy localhost:42112', dev)

    def test_toolchain_comes_from_makefile_or_explicit_environment(self):
        (self.root / 'Makefile').write_text('export GOTOOLCHAIN := go1.26.3\n')
        self.assertEqual(host.go_toolchain({}), 'go1.26.3')
        self.assertEqual(host.go_toolchain({'GOTOOLCHAIN': 'go1.26.4'}), 'go1.26.4')
        with self.assertRaises(ValueError):
            host.go_toolchain({'GOTOOLCHAIN': 'auto'})

    def test_failure_stops_components_without_claiming_success(self):
        host.STATIC_DIR.mkdir()
        (host.STATIC_DIR / '200.html').touch()
        with patch.object(host, 'stop_sessions') as stop, patch.object(host, 'port_free', return_value=True), \
             patch.object(host, 'start_components'), patch.object(host, 'apply_caddy', side_effect=RuntimeError('bad')):
            with self.assertRaisesRegex(RuntimeError, 'bad'):
                host.deploy('start', 'http://example.test')
            self.assertEqual(stop.call_count, 2)
            self.assertFalse(host.CONFIG_FILE.exists())

    def test_mac_dev_listens_on_localhost(self):
        binary = self.root / 'binary'
        binary.touch()
        with patch.object(host, 'BIN', binary), patch.object(host.platform, 'system', return_value='Darwin'), \
             patch.object(host, 'tmuxnew') as tmux, patch.object(host, 'wait_health'):
            host.start_components('dev', host.parse_site_url('http://example.test'), {'server': 42111, 'dev': 42112})
            self.assertIn('localhost', tmux.call_args.args[1])
            self.assertIn('--strictPort', tmux.call_args.args[1])

    def test_caddy_load_refusal_restores_file(self):
        before = b'other.example.test { respond "ok" }\n'
        host.CADDYFILE.write_bytes(before)
        with patch.object(host, 'caddy_admin_address', return_value='localhost:2019'), \
             patch.object(host, 'check_caddy_serves'), \
             patch.object(host, 'load_through_caddy', side_effect=host.CaddyRejected('no')):
            with self.assertRaises(host.CaddyRejected):
                host.apply_caddy(host.parse_site_url('http://example.test'), 'prod', {'server': 1, 'dev': 2})
        self.assertEqual(host.CADDYFILE.read_bytes(), before)

    def test_unrelated_running_caddy_is_never_overwritten(self):
        with patch.object(host, 'check_caddy_serves', side_effect=host.CaddyMismatch('different site')):
            with self.assertRaises(host.CaddyMismatch):
                host.apply_caddy(host.parse_site_url('http://example.test'), 'prod', {'server': 1, 'dev': 2})
        self.assertFalse(host.CADDYFILE.exists())

    def test_shared_caddy_uses_its_environment_and_sorts_hide_lists(self):
        a = {'handler': 'file_server', 'hide': ['./Caddyfile', 'private']}
        b = {'handler': 'file_server', 'hide': ['private', str(host.CADDYFILE)]}
        self.assertTrue(host.same_config(host.with_config_file_hidden(a, str(host.CADDYFILE)), b))
        with patch.object(host, 'caddy_admin_request', return_value={'result': {'adapted': True}}) as request:
            self.assertEqual(host.adapt_in_caddy('localhost:2019', b'{$ENV}'), {'adapted': True})
            self.assertEqual(request.call_args.kwargs['headers']['Content-Type'], 'text/caddyfile')

    def test_build_uses_lockfile_and_pinned_toolchain(self):
        with patch.object(host, 'run') as run:
            host.guarded('build', ['go', 'build'])
            self.assertEqual(run.call_args.kwargs['env']['GOTOOLCHAIN'], host.GO_TOOLCHAIN)
            self.assertNotIn('HEAVY_NOTIFY', run.call_args.kwargs['env'])


def _free_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class FragmentModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.state = self.root / '.self-host'
        self.state.mkdir()
        self.default_top = self.home / 'Caddyfile'
        self.default_sites = self.home / '.config/caddy/managed-sites/sites.caddy'
        self.addCleanup(self.tmp.cleanup)
        config = dict(host.HOSTING, static='caddy', static_dir='build')
        for key, value in {
            'ROOT': self.root,
            'STATE': self.state,
            'CONFIG_FILE': self.state / 'config.json',
            'CADDYFILE': self.default_top,
            'CADDY_SITES': self.default_sites,
            'CADDY_LAYOUT': 'inline',
            'STATIC_DIR': self.root / 'build',
            'BIN': self.state / 'bin/game',
            'HOSTING': config,
        }.items():
            p = patch.object(host, key, value)
            p.start()
            self.addCleanup(p.stop)

    def test_caddy_config_precedence_and_validation(self):
        saved = {
            'caddy_layout': 'fragment',
            'caddyfile': str(self.root / 'saved-top.caddy'),
            'caddy_sites': str(self.root / 'saved-sites.caddy'),
        }
        cfg = host.resolve_caddy_config(saved, env={})
        self.assertEqual(cfg.layout, 'fragment')
        self.assertEqual(cfg.caddyfile, (self.root / 'saved-top.caddy').resolve())
        self.assertEqual(cfg.caddy_sites, (self.root / 'saved-sites.caddy').resolve())

        env = {
            'BGD_CADDY_LAYOUT': 'fragment',
            'BGD_CADDYFILE': str(self.root / 'env-top.caddy'),
            'BGD_CADDY_SITES': str(self.root / 'env-sites.caddy'),
        }
        cfg_env = host.resolve_caddy_config(saved, env=env)
        self.assertEqual(cfg_env.caddyfile, (self.root / 'env-top.caddy').resolve())
        self.assertEqual(cfg_env.caddy_sites, (self.root / 'env-sites.caddy').resolve())

        cfg_cli = host.resolve_caddy_config(
            saved,
            caddy_layout='fragment',
            caddyfile=str(self.root / 'cli-top.caddy'),
            caddy_sites=str(self.root / 'cli-sites.caddy'),
            env=env,
        )
        self.assertEqual(cfg_cli.caddyfile, (self.root / 'cli-top.caddy').resolve())
        self.assertEqual(cfg_cli.caddy_sites, (self.root / 'cli-sites.caddy').resolve())

        with self.assertRaisesRegex(ValueError, 'fragment'):
            host.resolve_caddy_config({}, caddy_layout='inline', caddy_sites=str(self.root / 'x.caddy'), env={})
        with self.assertRaisesRegex(ValueError, 'fragment'):
            host.resolve_caddy_config({}, env={'BGD_CADDY_SITES': str(self.root / 'x.caddy')})
        with self.assertRaisesRegex(ValueError, "must be 'inline' or 'fragment'"):
            host.resolve_caddy_config({}, caddy_layout='sidecar', env={})

    def test_dev_start_to_start_retains_fragment_mode_without_flags(self):
        top = self.root / 'top.caddy'
        sites = self.root / 'managed/sites.caddy'
        sites.parent.mkdir()
        top.write_text(f'import {sites}\n')
        ports = {'server': 41731, 'dev': 41732}
        host.STATIC_DIR.mkdir()
        (host.STATIC_DIR / '200.html').write_text('ok')

        with patch.object(host, 'build'), \
             patch.object(host, 'build_server'), \
             patch.object(host, 'allocate_ports', return_value=ports), \
             patch.object(host, 'stop_sessions'), \
             patch.object(host, 'start_components'), \
             patch.object(host, '_apply_caddy_with_config') as apply_mock:
            host.deploy('dev-start', 'https://game.example.test', caddy_layout='fragment',
                        caddyfile=str(top), caddy_sites=str(sites))
            saved = json.loads(host.CONFIG_FILE.read_text())
            self.assertEqual(saved['caddy_layout'], 'fragment')
            self.assertEqual(Path(saved['caddyfile']), top)
            self.assertEqual(Path(saved['caddy_sites']), sites)
            self.assertEqual(apply_mock.call_args.args[3].layout, 'fragment')

            host.deploy('start')
            cfg2 = apply_mock.call_args.args[3]
            self.assertEqual(cfg2.layout, 'fragment')
            self.assertEqual(cfg2.caddyfile, top)
            self.assertEqual(cfg2.caddy_sites, sites)

    def test_main_parses_caddy_flags(self):
        with patch.object(host, 'deploy') as deploy_mock, \
             patch.object(sys, 'argv', ['self_host.py', 'start', '--caddy-layout', 'fragment',
                                        '--caddyfile', '/a/Caddyfile', '--caddy-sites', '/b/sites.caddy']):
            host.main()
        deploy_mock.assert_called_once_with(
            'start',
            None,
            caddy_layout='fragment',
            caddyfile='/a/Caddyfile',
            caddy_sites='/b/sites.caddy',
        )

    def test_fragment_validation_refusals_and_symlink_top_level(self):
        top = self.root / 'Caddyfile'
        managed = self.root / 'managed-sites'
        managed.mkdir()
        sites = managed / 'sites.caddy'

        cfg = host.CaddyConfig('fragment', top, sites)
        with self.assertRaisesRegex(RuntimeError, 'not found'):
            host.validate_fragment_setup(cfg, env={})

        top.write_text('localhost {}\n')
        with self.assertRaisesRegex(RuntimeError, 'equal or resolve'):
            host.validate_fragment_setup(host.CaddyConfig('fragment', top, top), env={})

        sites.symlink_to(top)
        with self.assertRaisesRegex(RuntimeError, 'cannot be a symlink'):
            host.validate_fragment_setup(cfg, env={})
        sites.unlink()

        with self.assertRaisesRegex(RuntimeError, 'does not import'):
            host.validate_fragment_setup(cfg, env={})

        for rel in ('import managed-sites/sites.caddy\n', 'import ./managed-sites/*.caddy\n'):
            top.write_text(rel)
            with self.assertRaisesRegex(ValueError, 'relative import path'):
                host.validate_fragment_setup(cfg, env={})

        top.write_text(f'import {sites}\nimport {managed}/*.caddy\n')
        with self.assertRaisesRegex(RuntimeError, 'more than once'):
            host.validate_fragment_setup(cfg, env={})

        top.write_text(f'import {managed}/*\n')
        with self.assertRaisesRegex(ValueError, 'lock or backup files'):
            host.validate_fragment_setup(cfg, env={})

        top.write_text(f'import {managed}/*.caddy\n{host.BEGIN}\n')
        with self.assertRaisesRegex(RuntimeError, 'markers already exist'):
            host.validate_fragment_setup(cfg, env={})

        top.write_text(f'import {managed}/*.caddy\n')
        sibling = managed / 'other.caddy'
        sibling.write_text(f'{host.BEGIN}\nother.example.test {{}}\n{host.END}\n')
        with self.assertRaisesRegex(RuntimeError, 'sibling imported file'):
            host.validate_fragment_setup(cfg, env={})
        sibling.unlink()

        sites.write_text(f'{host.END}\n{host.BEGIN}\n')
        with self.assertRaisesRegex(RuntimeError, 'reversed'):
            host.validate_fragment_setup(cfg, env={})
        sites.write_text(f'{host.BEGIN}\na\n{host.END}\n{host.BEGIN}\nb\n{host.END}\n')
        with self.assertRaisesRegex(RuntimeError, 'duplicate'):
            host.validate_fragment_setup(cfg, env={})
        sites.unlink()

        real_top = self.root / 'tracked-Caddyfile'
        real_top.write_text('{\n    admin localhost:2019\n}\nimport {$HOME}/managed-sites/*.caddy\n')
        top.unlink()
        top.symlink_to(real_top)
        env = {'HOME': str(self.root)}
        with patch.dict(os.environ, env, clear=False):
            imported, resolved_matches, unresolved = host.validate_fragment_setup(cfg, env=env)
        self.assertEqual(imported, ())
        self.assertEqual((resolved_matches, unresolved), (1, 0))

    def test_pre_mutation_snapshot_and_rollback_and_unsure(self):
        top = self.root / 'Caddyfile'
        managed = self.root / 'managed-sites'
        managed.mkdir()
        sites = managed / 'sites.caddy'
        top.write_text(f'{{\n    admin 127.0.0.1:29997\n}}\nunrelated.example.test {{\n    respond "unrelated"\n}}\nimport {managed}/*.caddy\n')
        other_game = '# BEGIN othergame self-host\nother.example.test {\n    reverse_proxy localhost:41999\n}\n# END othergame self-host\n'
        sites.write_text(other_game)
        cfg = host.CaddyConfig('fragment', top, sites)
        site = host.parse_site_url('https://game.example.test')
        ports = {'server': 41731, 'dev': 41732}

        before_top_bytes = top.read_bytes()
        base_adapted = {
            'apps': {'http': {'servers': {'srv0': {'routes': [
                {'match': [{'host': ['unrelated.example.test']}], 'handle': []},
                {'match': [{'host': ['other.example.test']}], 'handle': [{'handler': 'reverse_proxy', 'upstreams': [{'dial': 'localhost:41999'}]}]},
            ]}}}}
        }
        prod_adapted = {
            'apps': {'http': {'servers': {'srv0': {'routes': [
                {'match': [{'host': ['unrelated.example.test']}], 'handle': []},
                {'match': [{'host': ['other.example.test']}], 'handle': [{'handler': 'reverse_proxy', 'upstreams': [{'dial': 'localhost:41999'}]}]},
                {'match': [{'host': ['game.example.test']}], 'handle': [
                    {'handler': 'reverse_proxy', 'upstreams': [{'dial': 'localhost:41731'}]},
                    {'handler': 'file_server', 'hide': [str(sites)]},
                ]},
            ]}}}}
        }
        dev_adapted = {
            'apps': {'http': {'servers': {'srv0': {'routes': [
                {'match': [{'host': ['unrelated.example.test']}], 'handle': []},
                {'match': [{'host': ['other.example.test']}], 'handle': [{'handler': 'reverse_proxy', 'upstreams': [{'dial': 'localhost:41999'}]}]},
                {'match': [{'host': ['game.example.test']}], 'handle': [
                    {'handler': 'reverse_proxy', 'upstreams': [{'dial': 'localhost:41731'}]},
                    {'handler': 'reverse_proxy', 'upstreams': [{'dial': 'localhost:41732'}]},
                ]},
            ]}}}}
        }
        observed_calls = []

        def fake_req(address, path, *, data=None, headers=None, timeout=10.0):
            observed_calls.append((path, sites.read_text()))
            if path == '/config/':
                return base_adapted
            if path == '/adapt':
                if host.BEGIN not in sites.read_text():
                    self.assertEqual(sites.read_text(), other_game)
                    return {'result': base_adapted}
                return {'result': prod_adapted}
            if path == '/load':
                return {}
            raise AssertionError(path)

        with patch.object(host, 'caddy_admin_request', side_effect=fake_req):
            host.apply_caddy(site, 'prod', ports, caddy_config=cfg)
        self.assertEqual(observed_calls[0][0], '/config/')
        self.assertEqual(observed_calls[1], ('/adapt', other_game))
        self.assertEqual(top.read_bytes(), before_top_bytes)

        # Unsure -> old restores exact bytes; unsure -> unknown preserves candidate & backups.
        before_old = sites.read_bytes()
        calls = {'config': 0}

        def unsure_old(address, path, *, data=None, headers=None, timeout=10.0):
            if path == '/config/':
                return prod_adapted
            if path == '/adapt':
                return {'result': dev_adapted if '41732' in sites.read_text() else prod_adapted}
            if path == '/load':
                raise host.CaddyUnsure('lost')
            raise AssertionError(path)

        with patch.object(host, 'caddy_admin_request', side_effect=unsure_old), \
             patch.object(host, 'CADDY_RECHECK_DELAY', 0):
            with self.assertRaises(host.CaddyLoadOld):
                host.apply_caddy(site, 'dev', ports, caddy_config=cfg)
        self.assertEqual(sites.read_bytes(), before_old)

        def unsure_unknown(address, path, *, data=None, headers=None, timeout=10.0):
            if path == '/config/':
                calls['config'] += 1
                return prod_adapted if calls['config'] <= 2 else {'apps': {'http': {'servers': {'drift': {}}}}}
            if path == '/adapt':
                return {'result': dev_adapted if '41732' in sites.read_text() else prod_adapted}
            if path == '/load':
                raise host.CaddyUnsure('lost')
            raise AssertionError(path)

        with patch.object(host, 'caddy_admin_request', side_effect=unsure_unknown), \
             patch.object(host, 'CADDY_RECHECK_DELAY', 0):
            with self.assertRaises(host.CaddyLoadUnknown):
                host.apply_caddy(site, 'dev', ports, caddy_config=cfg)
        self.assertIn('reverse_proxy localhost:41732', sites.read_text())
        self.assertTrue((host.STATE / 'caddy-sites.before').exists())
        self.assertTrue((host.STATE / 'caddy-sites.candidate').exists())

        # Ownership guard refuses overwrite if changed outside lock.
        sites.write_text('owned-before\n')
        with self.assertRaisesRegex(RuntimeError, 'changed outside lock'):
            host._restore_caddy_target(sites, b'owned-before\n', b'expected-written\n')

    def test_concurrent_fragment_locks_serialize_updates(self):
        top = self.root / 'Caddyfile'
        sites = self.root / 'managed-sites/sites.caddy'
        cfg = host.CaddyConfig('fragment', top, sites)
        events = []
        entered_first = threading.Event()
        release_first = threading.Event()

        def worker_one():
            with host._caddy_locks(cfg):
                events.append('one-enter')
                entered_first.set()
                release_first.wait(timeout=2)
                events.append('one-exit')

        def worker_two():
            entered_first.wait(timeout=2)
            with host._caddy_locks(cfg):
                events.append('two-enter')
                events.append('two-exit')

        t1 = threading.Thread(target=worker_one)
        t2 = threading.Thread(target=worker_two)
        t1.start()
        t2.start()
        entered_first.wait(timeout=2)
        time.sleep(0.05)
        self.assertEqual(events, ['one-enter'])
        release_first.set()
        t1.join(timeout=2)
        t2.join(timeout=2)
        self.assertEqual(events, ['one-enter', 'one-exit', 'two-enter', 'two-exit'])


@unittest.skipUnless(shutil.which('caddy'), 'caddy binary required for disposable real-Caddy tests')
class DisposableCaddyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / 'home'
        self.xdg_data = self.root / 'xdg-data'
        self.xdg_cfg = self.root / 'xdg-cfg'
        self.state = self.root / '.self-host'
        for d in (self.home, self.xdg_data, self.xdg_cfg, self.state):
            d.mkdir(parents=True)
        self.admin_port = _free_local_port()
        self.admin_addr = f'127.0.0.1:{self.admin_port}'
        self.caddy_proc = None
        self.addCleanup(self._cleanup_caddy)
        self.addCleanup(self.tmp.cleanup)
        config = dict(host.HOSTING, static='caddy', static_dir='build')
        for key, value in {
            'ROOT': self.root,
            'STATE': self.state,
            'CONFIG_FILE': self.state / 'config.json',
            'CADDYFILE': self.home / 'Caddyfile',
            'CADDY_SITES': self.home / '.config/caddy/managed-sites/sites.caddy',
            'STATIC_DIR': self.root / 'build',
            'HOSTING': config,
        }.items():
            p = patch.object(host, key, value)
            p.start()
            self.addCleanup(p.stop)
        host.STATIC_DIR.mkdir()

    def _cleanup_caddy(self):
        proc = self.caddy_proc
        self.caddy_proc = None
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                if sock.connect_ex(('127.0.0.1', self.admin_port)) != 0:
                    return
            time.sleep(0.05)

    def _start_caddy(self, caddyfile: Path, *, extra_env=None):
        env = dict(os.environ)
        env.update({'HOME': str(self.home), 'XDG_DATA_HOME': str(self.xdg_data), 'XDG_CONFIG_HOME': str(self.xdg_cfg)})
        if extra_env:
            env.update(extra_env)
        log = self.root / 'caddy.log'
        fh = log.open('w')
        self.addCleanup(fh.close)
        self.caddy_proc = subprocess.Popen(
            ['caddy', 'run', '--config', str(caddyfile), '--adapter', 'caddyfile'],
            cwd=self.home,
            env=env,
            stdout=fh,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.caddy_proc.poll() is not None:
                raise RuntimeError(f'disposable caddy exited early:\n{log.read_text()}')
            try:
                host.caddy_admin_request(self.admin_addr, '/config/')
                return
            except host.CaddyUnreachable:
                time.sleep(0.1)
        raise RuntimeError(f'disposable caddy did not start on {self.admin_addr}:\n{log.read_text()}')

    def test_real_caddy_fragment_workflow_static_prod_and_rollback(self):
        managed_dir = self.home / '.config/caddy/managed-sites'
        managed_dir.mkdir(parents=True)
        (managed_dir / 'sites.caddy.lock').write_text('{{{{ ignored lock')
        (managed_dir / 'sites.caddy.before').write_text('{{{{ ignored before')
        sites = managed_dir / 'sites.caddy'

        tracked = self.root / 'tracked-Caddyfile'
        top = self.home / 'Caddyfile'
        unrelated_port = _free_local_port()
        http_port = _free_local_port()
        https_port = _free_local_port()
        game_http = _free_local_port()
        game_srv = _free_local_port()
        game_dev = _free_local_port()

        tracked.write_text(
            f'{{\n'
            f'    admin {self.admin_addr}\n'
            f'    auto_https off\n'
            f'    http_port {http_port}\n'
            f'    https_port {https_port}\n'
            f'}}\n'
            f'http://unrelated.example.test:{unrelated_port} {{\n'
            f'    respond "{{$CADDY_ONLY_BANNER}}"\n'
            f'}}\n'
            f'import {{$HOME}}/.config/caddy/managed-sites/*.caddy\n'
        )
        top.symlink_to(tracked)
        self._start_caddy(top, extra_env={'CADDY_ONLY_BANNER': 'caddy-env-ok'})

        cfg = host.CaddyConfig('fragment', top, sites)
        caller_env = {k: v for k, v in os.environ.items() if k != 'CADDY_ONLY_BANNER'}
        caller_env['HOME'] = str(self.home)
        with patch.dict(os.environ, caller_env, clear=True):
            site = host.parse_site_url(f'http://template.example.test:{game_http}')
            host.apply_caddy(site, 'prod', {'server': game_srv, 'dev': game_dev}, caddy_config=cfg)
            self.assertIn('file_server', sites.read_text())

            before_reject = sites.read_bytes()
            orig_req = host.caddy_admin_request

            def reject_on_load(address, path, *, data=None, headers=None, timeout=10.0):
                if path == '/load':
                    raise host.CaddyRejected('simulated rejection')
                return orig_req(address, path, data=data, headers=headers, timeout=timeout)

            with patch.object(host, 'caddy_admin_request', side_effect=reject_on_load):
                with self.assertRaises(host.CaddyRejected):
                    host.apply_caddy(site, 'dev', {'server': game_srv, 'dev': game_dev}, caddy_config=cfg)
            self.assertEqual(sites.read_bytes(), before_reject)
            self.assertEqual(host.check_caddy_serves(self.admin_addr, top.read_bytes(), caddyfile=top,
                                                     known_aliases=host.known_caddy_aliases(cfg, (sites,))),
                             str(top))


if __name__ == '__main__':
    unittest.main()
