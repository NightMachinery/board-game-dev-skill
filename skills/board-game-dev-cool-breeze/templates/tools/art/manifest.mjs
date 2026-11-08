// Rebuild per-theme progress from game subjects plus inherited theme overrides.
import fs from 'node:fs/promises';
import { themeGraph, subjectsFor, manifestFor, paths, project, hash, idPattern, writeJSON, main } from './lib.mjs';
await main(async ({ theme: id, check }) => {
  const theme = await themeGraph(id), subjects = await subjectsFor(theme), old = await manifestFor(id);
  const styleHash = hash(await fs.readFile(theme.style)), assets = {};
  for (const key of Object.keys(subjects).sort()) {
    if (!idPattern.test(key)) throw new Error(`invalid asset id: ${key}`);
    const spec = project.art.kinds[key.split('/')[0]], subject = subjects[key];
    if (!spec || !subject.subject) throw new Error(`missing kind or subject: ${key}`);
    const fingerprint = hash(JSON.stringify({ spec, subject, styleHash }));
    const prior = old.assets[key];
    // A changed subject/style/config requires a fresh review and never reuses
    // an approval. Keep attempt numbering so old costly generations survive.
    assets[key] = { id: key, ...subject, spec, fingerprint,
      attempt: prior?.attempt ?? 0, status: 'todo',
      ...(prior?.fingerprint === fingerprint ? prior : {}) };
  }
  for (const [key, prior] of Object.entries(old.assets))
    if (!assets[key] && prior.status === 'approved') throw new Error(`refusing to drop approved asset: ${key}`);
  const manifest = { theme: id, assets };
  if (check) {
    if (JSON.stringify(manifest) !== JSON.stringify(old)) throw new Error('manifest is out of date');
  } else await writeJSON(paths(id).manifest, manifest);
});
