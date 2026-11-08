import { envName } from '../config.mjs';
import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { frontendOrigin } from './origin.mjs';
test('uses explicit frontend environment or remembered served URL, never backend defaults', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bgd-origin-'));
  try {
    const file = path.join(dir, 'config.json');
    assert.throws(() => frontendOrigin({}, file, null), /served frontend URL/);
    fs.writeFileSync(file, JSON.stringify({ url: 'http://example.test:42117', ports: { server: 42118, dev: 42119 } }));
    assert.equal(frontendOrigin({}, file, null), 'http://example.test:42117');
    assert.equal(frontendOrigin({ [envName('ORIGIN')]: 'https://other.test' }, file), 'https://other.test');
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('an explicit project frontend default is used only without remembered serving config', () => {
  assert.equal(frontendOrigin({}, '/nonexistent/project-config.json', 'http://localhost:42117/path'), 'http://localhost:42117');
});
