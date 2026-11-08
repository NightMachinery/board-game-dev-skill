// Flatten ordered inheritance into a single index. Missing art is explicit null.
import fs from 'node:fs/promises';
import path from 'node:path';
import { themeGraph, subjectsFor, manifestFor, paths, hash, main, writeJSON } from './lib.mjs';
import { pathToFileURL } from 'node:url';
export async function buildIndex(id) {
  const theme = await themeGraph(id), subjects = await subjectsFor(theme), own = new Map();
  async function load(node) {
    if (own.has(node.id)) return;
    const m = await manifestFor(node.id), assets = {};
    for (const [key, a] of Object.entries(m.assets)) {
      if (a.status !== 'approved' || !a.outputs?.length) continue;
      const sizes = {};
      for (const output of a.outputs) {
        const bytes = await fs.readFile(path.join(paths(node.id).shipped, output.file));
        const digest = hash(bytes).slice(0, 12);
        if (digest !== output.hash) throw new Error(`derived asset changed: ${node.id}/${key}`);
        sizes[output.size] = { url: `/art/${node.id}/${output.file}?v=${digest}`, w: output.w, h: output.h };
      }
      assets[key] = { sourceTheme: node.id, sizes };
    }
    own.set(node.id, assets);
    for (const parent of node.parents) await load(parent);
  }
  await load(theme);
  function resolve(node, key) {
    if (own.get(node.id)[key]) return own.get(node.id)[key];
    for (const parent of node.parents) { const found = resolve(parent, key); if (found) return found; }
    return null;
  }
  return { id, name: theme.name, mode: theme.mode, tokens: theme.tokens,
    assets: Object.fromEntries(Object.keys(subjects).sort().map((key) => [key, resolve(theme, key)])) };
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href)
  await main(async ({ theme, check }) => {
    const index = await buildIndex(theme), p = paths(theme).index;
    if (check) {
      if (JSON.stringify(index, null, 2) + '\n' !== await fs.readFile(p, 'utf8')) throw new Error('index is out of date');
    } else await writeJSON(p, index);
  });
