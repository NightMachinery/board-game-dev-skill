// Review/shipping gate. Visual inspection is still required before approval.
import { manifestFor, main } from './lib.mjs';
import { buildIndex } from './index.mjs';
await main(async ({ theme }) => {
  const m = await manifestFor(theme);
  for (const [id, a] of Object.entries(m.assets)) {
    if (a.status !== 'approved') continue;
    if (!a.review || a.review.fingerprint !== a.fingerprint ||
        a.review.attempt !== a.approvedAttempt || !a.outputs?.length)
      throw new Error(`approval or processed files missing: ${id}`);
    for (const size of a.spec.sizes) {
      const output = a.outputs.find((x) => x.size === size.name);
      if (!output || output.bytes > size.budget) throw new Error(`missing size or over budget: ${id}/${size.name}`);
    }
  }
  await buildIndex(theme); // Also checks cycles, inherited files and hashes.
  console.log('art gate passed');
});
