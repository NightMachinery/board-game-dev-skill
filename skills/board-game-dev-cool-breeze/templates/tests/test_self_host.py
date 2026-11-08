"""Standalone hosting contract tests; never start a server or edit a home file."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
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
        for key, value in {'STATE': self.root, 'CONFIG_FILE': self.root / 'config.json',
                           'CADDYFILE': self.root / 'Caddyfile',
                           'STATIC_DIR': self.root / 'build'}.items():
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

    def test_all_serving_commands_stop_both_modes_first_and_remember_ports(self):
        for command in ('setup', 'redeploy', 'start', 'dev-start'):
            with self.subTest(command=command), patch.object(host, 'stop_sessions') as stop, \
                 patch.object(host, 'build') as build, patch.object(host, 'build_server'), \
                 patch.object(host, 'port_free', return_value=True), \
                 patch.object(host, 'allocate_ports', return_value={'server': 42111, 'dev': 42112}), \
                 patch.object(host, 'start_components') as start, patch.object(host, 'apply_caddy') as apply:
                host.STATIC_DIR.mkdir(exist_ok=True)
                (host.STATIC_DIR / '200.html').write_text('html')
                events = []
                stop.side_effect = lambda: events.append('stop')
                start.side_effect = lambda *a: events.append('start')
                host.deploy(command, 'http://example.test')
                self.assertEqual(events, ['stop', 'start'])
                self.assertEqual(json.loads(host.CONFIG_FILE.read_text())['ports']['server'], 42111)
                self.assertEqual(build.called, command in ('setup', 'redeploy'))
                self.assertEqual(apply.call_args.args[1], 'dev' if command == 'dev-start' else 'prod')

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


if __name__ == '__main__':
    unittest.main()
