// Generate exactly one bitmap through the real Codex binary. Never parallelize.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { themeGraph, manifestFor, paths, assetAt, run, writeJSON, main, root } from './lib.mjs';
async function snapshot(dir) {
  try { return (await fs.readdir(dir, { recursive: true })).filter((x) => x.endsWith('.png')); }
  catch (e) { if (e.code === 'ENOENT') return []; throw e; }
}
await main(async (args) => {
  if (!args['dry-run'] && process.env.BGD_HEAVY_KIND !== 'codex') {
    const child = spawnSync('python3', [path.join(root, 'tools/heavy.py'), 'run', '--kind', 'codex', '--wait', '3600', '--', process.execPath,
      fileURLToPath(import.meta.url), ...process.argv.slice(2)], { stdio: 'inherit', env: process.env });
    process.exitCode = child.status ?? 1; return;
  }
  const theme = await themeGraph(args.theme), m = await manifestFor(args.theme), a = assetAt(m, args.id);
  if (a.status === 'approved') throw new Error('approved art cannot be regenerated; create a new override');
  const style = await fs.readFile(theme.style, 'utf8');
  const prefixBlock = style.split('## Style prefix (verbatim)')[1]?.split(/\n## /)[0];
  const prefix = prefixBlock?.split('\n').filter((x) => x.startsWith('> ')).map((x) => x.slice(2)).join(' ');
  const kind = args.id.split('/')[0];
  const template = new RegExp(`\\*\\*${kind}\\*\\*:\\s*"([^"]+)"`).exec(style)?.[1];
  if (!prefix || !template) throw new Error('style needs a quoted prefix and a kind template');
  const prompt = `${prefix} ${template.replaceAll('{subject}', a.subject).replaceAll('{accent}', a.accent ?? '')} ${args.amend ?? ''}`;
  const instruction = `Call image_gen exactly once: ${prompt}. Size ${a.spec.gen}. Do nothing else. Reply DONE.`;
  if (args['dry-run']) { console.log(instruction); return; }
  const bin = process.env.CODEX_BIN;
  if (!bin || !path.isAbsolute(bin)) throw new Error('set CODEX_BIN to the absolute path of the real Codex CLI binary');
  const images = path.join(process.env.CODEX_HOME ?? path.join(os.homedir(), '.codex'), 'generated_images');
  const before = new Set(await snapshot(images));
  const scratch = await fs.mkdtemp(path.join(os.tmpdir(), 'bgd-art-'));
  await run(bin, ['exec', '--ephemeral', '--skip-git-repo-check', '-s', 'read-only', '-C', scratch,
    '--enable', 'image_generation', '-o', path.join(scratch, 'last.txt'), instruction],
    { timeout: 360_000, maxBuffer: 8 * 1024 * 1024 });
  const fresh = (await snapshot(images)).filter((x) => !before.has(x));
  if (fresh.length !== 1) throw new Error(`expected exactly one new PNG, found ${fresh.length}; inspect ${scratch}`);
  const src = path.join(images, fresh[0]);
  const dimensions = (await run('magick', ['identify', '-format', '%w %h', src])).stdout.trim().split(' ').map(Number);
  const [w, h] = a.spec.gen.split('x').map(Number), [aw, ah] = dimensions;
  if (aw < w || ah < h || Math.abs(aw / ah - w / h) > 0.02) throw new Error('generated image has the wrong shape/size');
  const attempt = a.attempt + 1, dest = path.join(paths(args.theme).raw, args.id, `${attempt}.png`);
  await fs.mkdir(path.dirname(dest), { recursive: true });
  await fs.copyFile(src, dest, fs.constants.COPYFILE_EXCL);
  Object.assign(a, { attempt, status: 'generated', promptAmend: args.amend ?? '' });
  delete a.outputs; delete a.approvedAttempt;
  await writeJSON(paths(args.theme).manifest, m);
  console.log(dest);
});
