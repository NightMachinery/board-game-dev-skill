// Standalone, no npm install. ART_INTEGRATION=1 additionally checks native codecs.
import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
const scratch = await fs.mkdtemp(path.join(os.tmpdir(), 'bgd-art-test-'));
process.env.BGD_ART_ROOT = scratch;
process.env.BGD_RUN_DIR = path.join(scratch, 'private');
const { writeJSON, paths, themeGraph, subjectsFor, hash, project } = await import('./lib.mjs');
const { buildIndex } = await import('./index.mjs');
test.after(() => fs.rm(scratch, { recursive: true, force: true }));
async function theme(id, inherits = [], extras = {}) {
  await writeJSON(path.join(paths(id).dir, 'theme.json'), { id, name: id, mode: 'light', inherits,
    tokens: { colours: { paper: '#fff' } }, artDirection: 'style.md', ...extras });
  await fs.writeFile(path.join(paths(id).dir, 'style.md'), '## Style prefix (verbatim)\n> Paint clearly.\n\n## Kind templates\n**card**: "{subject} in {accent}."\n');
}
async function asset(themeId, id, content) {
  const bytes = Buffer.from(content), file = `${id}@main.avif`;
  await fs.mkdir(path.dirname(path.join(paths(themeId).shipped, file)), { recursive: true });
  await fs.writeFile(path.join(paths(themeId).shipped, file), bytes);
  await writeJSON(paths(themeId).manifest, { theme: themeId, assets: { [id]: { status: 'approved',
    outputs: [{ file, size: 'main', w: 8, h: 8, hash: hash(bytes).slice(0, 12) }] } } });
}
await writeJSON(path.join(scratch, 'art/subjects.json'), { 'card/sample': { subject: 'a tree' }, 'card/missing': { subject: 'a bridge' } });
test('first parent wins, child overrides, missing asset is a placeholder', async () => {
  await theme('first'); await theme('second'); await theme('child', ['first', 'second'], { mode: 'dark' });
  await asset('first', 'card/sample', 'first'); await asset('second', 'card/sample', 'second');
  const index = await buildIndex('child');
  assert.equal(index.mode, 'dark'); assert.equal(index.assets['card/sample'].sourceTheme, 'first');
  assert.equal(index.assets['card/missing'], null);
  assert.match(index.assets['card/sample'].sizes.main.url, /^\/art\/first\/.*\?v=[a-f0-9]{12}$/);
  await asset('child', 'card/sample', 'own');
  assert.equal((await buildIndex('child')).assets['card/sample'].sourceTheme, 'child');
  assert.equal((await buildIndex('second')).assets['card/sample'].sourceTheme, 'second');
});
test('inherited subjects override the game in parent order; child wins', async () => {
  await theme('subjects-first'); await theme('subjects-second'); await theme('subjects-child', ['subjects-first', 'subjects-second']);
  await writeJSON(path.join(paths('subjects-first').dir, 'subjects.json'), { 'card/sample': { subject: 'first parent' } });
  await writeJSON(path.join(paths('subjects-second').dir, 'subjects.json'), { 'card/sample': { subject: 'second parent' } });
  let subjects = await subjectsFor(await themeGraph('subjects-child'));
  assert.equal(subjects['card/sample'].subject, 'first parent'); assert.equal(subjects['card/missing'].subject, 'a bridge');
  await writeJSON(path.join(paths('subjects-child').dir, 'subjects.json'), { 'card/sample': { subject: 'child' } });
  subjects = await subjectsFor(await themeGraph('subjects-child')); assert.equal(subjects['card/sample'].subject, 'child');
});
test('cycle refusal and invalid mode/path', async () => {
  await theme('cycle-a', ['cycle-b']); await theme('cycle-b', ['cycle-a']);
  await assert.rejects(buildIndex('cycle-a'), /cycle/);
  await theme('bad-mode', [], { mode: 'auto' }); await assert.rejects(buildIndex('bad-mode'), /invalid theme/);
  await theme('bad-path', [], { artDirection: '../style.md' }); await assert.rejects(buildIndex('bad-path'), /inside its theme/);
});
test('indices reject changed shipped bytes and omit unapproved own attempts', async () => {
  await theme('tampered'); await asset('tampered', 'card/sample', 'original');
  await fs.writeFile(path.join(paths('tampered').shipped, 'card/sample@main.avif'), 'changed');
  await assert.rejects(buildIndex('tampered'), /changed/);
  await theme('unreviewed', ['second']);
  await writeJSON(paths('unreviewed').manifest, { theme: 'unreviewed', assets: { 'card/sample': { status: 'generated' } } });
  assert.equal((await buildIndex('unreviewed')).assets['card/sample'].sourceTheme, 'second');
});
test('native lossless processing and approval gate', { skip: !process.env.ART_INTEGRATION }, async () => {
  await theme('codec');
  // A tiny inert generated PNG, never an image-generation call.
  const raw = path.join(paths('codec').raw, 'card/sample/1.png');
  await fs.mkdir(path.dirname(raw), { recursive: true });
  execFileSync('magick', ['-size', '24x16', 'xc:#3c6a46', raw]);
  const spec = { gen: '24x16', sizes: [{ name: 'main', w: 12, h: 8, budget: 20000 }] };
  const a = { id: 'card/sample', status: 'generated', attempt: 1, fingerprint: 'fixture', spec };
  await writeJSON(paths('codec').manifest, { theme: 'codec', assets: { 'card/sample': a } });
  const call = (script, ...args) => execFileSync(process.execPath, [new URL(script, import.meta.url).pathname, '--theme', 'codec', ...args], { env: process.env, encoding: 'utf8' });
  assert.throws(() => call('process.mjs', '--id', 'card/sample'), /shipping requires/);
  const review = path.join(scratch, 'review.json');
  await writeJSON(review, [{ id: 'card/sample', attempt: 1, status: 'approved', fingerprint: 'fixture', reviewer: 'reviewer', reasons: 'Shape checked.' }]);
  call('apply-review.mjs', '--review', review); call('process.mjs', '--id', 'card/sample');
  assert.equal((await buildIndex('codec')).assets['card/sample'].sourceTheme, 'codec');
  call('gate.mjs');
});
