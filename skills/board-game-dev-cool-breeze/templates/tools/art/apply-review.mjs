// Explicit human/agent review records authorize only the named attempt.
import fs from 'node:fs/promises';
import path from 'node:path';
import { manifestFor, paths, assetAt, readJSON, writeJSON, main } from './lib.mjs';
await main(async ({ theme, review }) => {
  const m = await manifestFor(theme), decisions = await readJSON(review);
  if (!Array.isArray(decisions)) throw new Error('review must be a JSON array');
  for (const d of decisions) {
    const a = assetAt(m, d.id);
    if (!['approved', 'rejected'].includes(d.status) || !d.reviewer || !d.reasons ||
        !Number.isInteger(d.attempt) || d.attempt < 1 || d.attempt > a.attempt ||
        d.fingerprint !== a.fingerprint) throw new Error(`invalid/stale review: ${d.id}`);
    await fs.access(path.join(paths(theme).raw, d.id, `${d.attempt}.png`));
    Object.assign(a, { status: d.status, review: d });
    if (d.status === 'approved') a.approvedAttempt = d.attempt;
    else { delete a.approvedAttempt; delete a.outputs; a.promptAmend = d.amend ?? ''; }
  }
  await writeJSON(paths(theme).manifest, m);
});
