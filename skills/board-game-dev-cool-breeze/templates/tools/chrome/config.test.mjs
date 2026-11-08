// Configured dependency resolution without starting any browser.
import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

test('an adopter can keep Playwright in a workspace package and retain its environment namespace', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'bgd-chrome-config-'));
  try {
    await fs.mkdir(path.join(tmp, 'tools/chrome'), { recursive: true });
    for (const file of ['launch.mjs', 'cdp.mjs'])
      await fs.copyFile(new URL(file, import.meta.url), path.join(tmp, 'tools/chrome', file));
    await fs.copyFile(new URL('../config.mjs', import.meta.url), path.join(tmp, 'tools/config.mjs'));
    await fs.writeFile(path.join(tmp, 'package.json'), '{"type":"module"}');
    const pkg = path.join(tmp, 'e2e/node_modules/@playwright/test');
    await fs.mkdir(pkg, { recursive: true });
    await fs.writeFile(path.join(tmp, 'e2e/package.json'), '{}');
    await fs.writeFile(path.join(pkg, 'index.js'), 'module.exports = { chromium: { executablePath: () => process.execPath } };');
    await fs.writeFile(path.join(tmp, 'tools/project.json'), JSON.stringify({ name: 'fixture',
      env_prefix: 'EXISTING_', run_dir_env: 'EXISTING_RUN_DIR', run_dir: '~/private-state',
      ports: { chrome: 42119 }, chrome: { playwright_package: 'e2e/package.json', playwright_module: '@playwright/test' } }));
    const env = { ...process.env }; delete env.BGD_PROJECT_CONFIG; delete env.CHROME_BIN;
    const code = "import { findChrome, DEFAULT_PORT } from './tools/chrome/launch.mjs'; " +
      "import { envName } from './tools/config.mjs'; console.log(JSON.stringify([findChrome(), DEFAULT_PORT, envName('HEAVY_KIND')]));";
    const result = JSON.parse(execFileSync(process.execPath, ['--input-type=module', '-e', code], { cwd: tmp, env, encoding: 'utf8' }));
    assert.deepEqual(result, [process.execPath, 42119, 'EXISTING_HEAVY_KIND']);
    env.CHROME_BIN = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
    assert.throws(() => execFileSync(process.execPath, ['--input-type=module', '-e', code], { cwd: tmp, env, encoding: 'utf8', stdio: 'pipe' }), /never an everyday browser/);
  } finally { await fs.rm(tmp, { recursive: true, force: true }); }
});
