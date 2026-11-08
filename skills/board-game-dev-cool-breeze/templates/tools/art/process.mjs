// Lossless originals, budgeted AVIF derivatives. --out keeps previews private.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { manifestFor, paths, assetAt, run, rgba, hash, writeJSON, main } from './lib.mjs';
await main(async ({ theme, id, src, out }) => {
  const m = await manifestFor(theme), a = assetAt(m, id), p = paths(theme);
  if (!out && a.status !== 'approved') throw new Error('shipping requires an explicit approval');
  if (src && !out && path.resolve(src) !== path.resolve(p.originals, `${id}.webp`))
    throw new Error('shipping --src must be the committed original; use --out for a raw preview');
  src ??= path.join(p.raw, id, `${out ? a.attempt : a.approvedAttempt}.png`);
  const scratch = await fs.mkdtemp(path.join(os.tmpdir(), 'bgd-process-'));
  try {
    const original = path.join(scratch, 'original.webp');
    if (src.endsWith('.webp')) await fs.copyFile(src, original);
    else await run('cwebp', ['-quiet', '-lossless', '-exact', '-z', '9', src, '-o', original]);
    if (!(await rgba(src)).equals(await rgba(original))) throw new Error('lossless original changed RGBA pixels');
    const outputs = [];
    for (const size of a.spec.sizes) {
      if (!/^[a-z][a-z0-9-]*$/.test(size.name) || ![size.w, size.h, size.budget].every((x) => Number.isInteger(x) && x > 0))
        throw new Error('invalid size/budget configuration');
      const png = path.join(scratch, `${size.name}.png`), avif = path.join(scratch, `${size.name}.avif`);
      await run('magick', [original, '-resize', `${size.w}x${size.h}^`, '-gravity', 'center', '-extent', `${size.w}x${size.h}`, png]);
      let bytes;
      for (const quality of [55, 45, 35]) {
        await run('avifenc', ['-q', String(quality), '--speed', '6', png, avif]);
        bytes = await fs.readFile(avif); if (bytes.length <= size.budget) break;
      }
      if (bytes.length > size.budget) throw new Error(`AVIF exceeds budget: ${id}/${size.name}`);
      outputs.push({ size: size.name, w: size.w, h: size.h, bytes: bytes.length,
        file: `${id}@${size.name}.avif`, hash: hash(bytes).slice(0, 12), scratch: avif });
    }
    const originalDest = path.join(out ?? p.originals, `${id}.webp`);
    await fs.mkdir(path.dirname(originalDest), { recursive: true });
    await fs.copyFile(original, originalDest);
    for (const item of outputs) {
      const dest = path.join(out ? path.join(out, 'shipped') : p.shipped, item.file);
      await fs.mkdir(path.dirname(dest), { recursive: true }); await fs.copyFile(item.scratch, dest);
      delete item.scratch;
    }
    if (!out) { a.outputs = outputs; await writeJSON(p.manifest, m); }
    console.log(JSON.stringify({ id, outputs }));
  } finally { await fs.rm(scratch, { recursive: true, force: true }); }
});
