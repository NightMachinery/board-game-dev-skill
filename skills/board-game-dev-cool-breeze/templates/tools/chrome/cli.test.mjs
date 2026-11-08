import { envName } from '../config.mjs';
// No browser is launched: invalid arguments must fail before launch().
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const shot = fileURLToPath(new URL('./shot.mjs', import.meta.url));
function run(args, stack = '0') {
  return spawnSync(process.execPath, [shot, ...args], {
    encoding: 'utf8',
    env: { ...process.env, [envName('STACK')]: stack },
    timeout: 10_000
  });
}

for (const [args, message] of [
  [[], /nothing to do: pass --out PATH, --probe, or both/],
  [['--unknown'], /Unknown option '--unknown'/],
  [['--probe', '--vp', 'bad'], /--vp/],
  [['--probe', '--theme', 'unknown-theme'], /--theme/],
  [['--probe', '--storage', 'bad'], /--storage: not JSON/],
  [['--probe', '--token', 'bad'], /--token: expected/]
]) {
  test(`usage error is brief: ${JSON.stringify(args)}`, () => {
    const result = run(args);
    assert.equal(result.status, 1, result.stderr);
    assert.match(result.stderr, message);
    assert.equal(result.stdout, '');
    assert.doesNotMatch(result.stderr, /\n\s+at /);
    assert.equal(result.stderr.trim().split('\n').length, 1);
  });
}

test('BGD_STACK=1 restores the diagnostic stack', () => {
  const result = run([], '1');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Error: nothing to do/);
  assert.match(result.stderr, /\n\s+at /);
});

test('--help succeeds without launching a browser', () => {
  const result = run(['--help']);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Screenshot and DOM probe/);
  assert.equal(result.stderr, '');
});
