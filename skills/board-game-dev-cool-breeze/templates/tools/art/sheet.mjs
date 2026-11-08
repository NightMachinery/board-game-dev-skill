// Private contact sheet: labels include id, attempt and approval fingerprint.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { manifestFor, paths, run, main } from './lib.mjs';
await main(async ({ theme, out }) => {
  if (!out) throw new Error('--out PATH is required; keep contact sheets outside the repo');
  const scratch = await fs.mkdtemp(path.join(os.tmpdir(), 'bgd-sheet-'));
  try {
    const m = await manifestFor(theme), files = [];
    for (const [id, a] of Object.entries(m.assets)) {
      if (!a.attempt) continue;
      const file = path.join(scratch, `${files.length}.png`);
      await run('magick', [path.join(paths(theme).raw, id, `${a.attempt}.png`), '-thumbnail', '220x160',
        '-background', 'white', '-fill', 'black', '-gravity', 'south', '-splice', '0x40',
        '-pointsize', '12', '-annotate', '0', `${id} #${a.attempt}\n${a.fingerprint.slice(0, 12)}`, file]);
      files.push(file);
    }
    if (!files.length) throw new Error('no generated attempts');
    await fs.mkdir(path.dirname(path.resolve(out)), { recursive: true });
    await run('magick', ['montage', ...files, '-tile', '4x', '-geometry', '+8+8', out]);
  } finally { await fs.rm(scratch, { recursive: true, force: true }); }
});
