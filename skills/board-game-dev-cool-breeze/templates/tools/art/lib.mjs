// Copy tools/project.json and themes/<id>/theme.json. See README.md for adoption.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { createHash } from 'node:crypto';
import { project, runDir } from '../config.mjs';
export { project, runDir };
export const root = path.resolve(process.env.BGD_ART_ROOT ?? fileURLToPath(new URL('../../', import.meta.url)));
export const idPattern = /^[a-z][a-z0-9-]*\/[a-z0-9][a-z0-9-]*$/;
export const themePattern = /^[a-z][a-z0-9-]*$/;
export const hash = (data) => createHash('sha256').update(data).digest('hex');
export async function readJSON(file, fallback) {
  try { return JSON.parse(await fs.readFile(file, 'utf8')); }
  catch (e) { if (e.code === 'ENOENT' && fallback !== undefined) return fallback; throw e; }
}
export async function writeJSON(file, value) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const temp = `${file}.${process.pid}.tmp`;
  await fs.writeFile(temp, JSON.stringify(value, null, 2) + '\n');
  await fs.rename(temp, file);
}
export function paths(theme) {
  if (!themePattern.test(theme)) throw new Error('invalid theme id');
  return {
    dir: path.join(root, project.themes_dir, theme),
    manifest: path.join(root, 'art/manifests', `${theme}.json`),
    raw: path.join(runDir, 'art-work', theme, 'raw'),
    originals: path.join(root, 'art/originals', theme),
    shipped: path.join(root, 'web/static/art', theme),
    index: path.join(root, 'web/src/lib/art', `${theme}.gen.json`)
  };
}
// First parent wins; the child overrides it. Nested interface token groups merge.
export function merge(...objects) {
  const out = Object.create(null);
  for (const obj of objects) for (const [key, value] of Object.entries(obj ?? {})) {
    if (['__proto__', 'constructor', 'prototype'].includes(key)) throw new Error('unsafe object key');
    out[key] = value && typeof value === 'object' && !Array.isArray(value)
      ? merge(out[key], value) : value;
  }
  return out;
}
export async function themeGraph(id, stack = [], memo = new Map()) {
  if (stack.includes(id)) throw new Error(`theme inheritance cycle: ${[...stack, id].join(' -> ')}`);
  if (memo.has(id)) return memo.get(id);
  const p = paths(id), raw = await readJSON(path.join(p.dir, 'theme.json'));
  if (raw.id !== id || !raw.name || !['light', 'dark'].includes(raw.mode) ||
      !Array.isArray(raw.inherits) || !raw.inherits.every((x) => typeof x === 'string' && themePattern.test(x)) ||
      !raw.tokens || typeof raw.tokens !== 'object' || !raw.artDirection)
    throw new Error(`invalid theme manifest: ${id}`);
  const style = path.resolve(p.dir, raw.artDirection);
  if (!style.startsWith(p.dir + path.sep)) throw new Error('artDirection must stay inside its theme');
  const parents = [];
  for (const parent of raw.inherits) parents.push(await themeGraph(parent, [...stack, id], memo));
  const ownSubjects = await readJSON(path.join(p.dir, 'subjects.json'), {});
  const node = { ...raw, style, parents,
    tokens: merge(...parents.toReversed().map((x) => x.tokens), raw.tokens),
    overrides: merge(...parents.toReversed().map((x) => x.overrides), ownSubjects) };
  memo.set(id, node);
  return node;
}
export async function subjectsFor(theme) {
  return merge(await readJSON(path.join(root, 'art/subjects.json'), {}), theme.overrides);
}
export async function manifestFor(id) {
  const m = await readJSON(paths(id).manifest, { theme: id, assets: {} });
  if (m.theme !== id) throw new Error('manifest belongs to a different theme');
  return m;
}
export function assetAt(manifest, id) {
  if (!idPattern.test(id) || !manifest.assets[id]) throw new Error(`unknown asset: ${id}`);
  return manifest.assets[id];
}
export const run = promisify(execFile);
export async function rgba(file) {
  return (await run('magick', [file, '-alpha', 'on', '-depth', '16', 'rgba:-'],
    { encoding: 'buffer', maxBuffer: 128 * 1024 * 1024 })).stdout;
}
export function cliArgs() {
  const args = { theme: project.default_theme };
  const allowed = new Set(['theme', 'id', 'src', 'out', 'review', 'amend', 'check', 'dry-run', 'help']);
  for (let i = 2; i < process.argv.length; i++) {
    const k = process.argv[i].replace(/^--/, '');
    if (!allowed.has(k) || !process.argv[i].startsWith('--')) throw new Error(`unknown argument: ${process.argv[i]}`);
    if (['check', 'dry-run', 'help'].includes(k)) args[k] = true;
    else { if (process.argv[i + 1] === undefined || process.argv[i + 1].startsWith('--')) throw new Error(`missing --${k} value`); args[k] = process.argv[++i]; }
  }
  return args;
}
export async function main(fn) {
  try { const args = cliArgs(); if (args.help) { console.log('See tools/art/README.md. Flags: --theme ID --id kind/slug --out PATH --check --dry-run'); return; } await fn(args); }
  catch (e) { console.error(e.message); process.exitCode = 1; }
}
