#!/usr/bin/env node
// Renders SVG files into one labelled contact sheet with a real browser, so
// CSS, custom properties, filters and fonts render as they will in the app.
//
//   python3 tools/heavy.py run --kind browser -- node tools/chrome/svg-render.mjs \
//     --in web/src/lib/icons/svg --sizes 16,24,48,128 --bg '#f4ecdc,#1c1915' \
//     --cols 6 --out /tmp/sheet.png --meta /tmp/sheet.json
//
// Flags (`--flag value` or `--flag=value`):
//   --in X        SVG files or directories (searched recursively); repeat it or
//                 separate with commas
//   --sizes L     icon box sizes in CSS px (default 16,24,48,128)
//   --bg L        one band per background colour (default #f4ecdc,#1c1915)
//   --fg L        text colour (currentColor) per band; default: dark ink on a
//                 light hex background, light ink on a dark one
//   --cols N      files per row (default: up to 6)
//   --dpr N       device pixel ratio (default 1, the true small-size raster; use 2
//                 for a closer look)
//   --out PATH    the PNG to write (required)
//   --meta PATH   also write JSON: per file its viewBox, size attributes, element
//                 and shape counts, bytes, the colours it uses, and warnings
//   --force       launch Chrome without the heavy.py browser lock
//
// The SVGs are inlined (not loaded as <img>), so currentColor and var(--i1)
// resolve from the band. Each copy gets its ids prefixed, so url(#id)
// references never collide. For quick single-icon iterations use
// tools/art/render-fast.sh instead; it needs no browser.

import fs from 'node:fs';
import path from 'node:path';
import { parseArgs } from 'node:util';
import { CDP, evaluate, openPage } from './cdp.mjs';
import { isMain, launch, printHeader, reportAndExit } from './launch.mjs';

const list = (s) =>
  String(s)
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean);

const escapeHtml = (s) =>
  String(s).replace(
    /[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]
  );

/**
 * Expands files and directories into a sorted, de-duplicated list of
 * {file, label}. A file found in a directory is labelled by its path inside
 * it, so two icons with the same name in different folders stay apart.
 */
export function collectSvgs(inputs) {
  const out = new Map(); // file -> label
  for (const item of inputs) {
    const stat = fs.statSync(item, { throwIfNoEntry: false });
    if (!stat) throw new Error(`--in: ${item} does not exist`);
    if (stat.isDirectory()) {
      for (const rel of fs.readdirSync(item, { recursive: true }).map(String).sort()) {
        if (rel.toLowerCase().endsWith('.svg')) out.set(path.join(item, rel), rel.slice(0, -4));
      }
    } else if (!out.has(item)) {
      out.set(item, path.basename(item, path.extname(item)));
    }
  }
  return [...out]
    .map(([file, label]) => ({ file, label }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** Picks an ink colour for a background: dark on light hex colours, light on dark ones. */
function inkFor(bg) {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})(?:[0-9a-f]{2})?$/i.exec(bg);
  if (!m) return '#2a2118';
  const hex = m[1].length === 3 ? [...m[1]].map((c) => c + c).join('') : m[1];
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const lin = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return lum > 0.35 ? '#2a2118' : '#f4ecdc';
}

/** Cleans one SVG source for inlining and reads its root attributes. */
export function prepareSvg(source) {
  const warnings = [];
  let s = source
    .replace(/<\?xml[\s\S]*?\?>/g, '')
    .replace(/<!DOCTYPE[\s\S]*?>/gi, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .trim();
  if (/<script[\s>]/i.test(s)) {
    warnings.push('contains <script> (removed for rendering)');
    s = s.replace(/<script[\s\S]*?<\/script>/gi, '');
  }
  const root = /<svg\b[^>]*>/i.exec(s);
  if (!root) throw new Error('no <svg> element');
  const attr = (name) =>
    new RegExp(`\\s${name}\\s*=\\s*["']([^"']*)["']`, 'i').exec(root[0])?.[1] ?? null;
  const viewBox = attr('viewBox');
  const width = attr('width');
  const height = attr('height');
  if (!viewBox) {
    warnings.push('no viewBox');
    const w = parseFloat(width ?? '');
    const h = parseFloat(height ?? '');
    if (w > 0 && h > 0) s = s.replace(/<svg\b/i, `<svg viewBox="0 0 ${w} ${h}"`);
  }
  for (const [tag, why] of [
    ['text', '<text> (glyphs depend on fonts)'],
    ['image', '<image> (raster inside a vector)'],
    ['filter', '<filter>'],
    ['foreignObject', '<foreignObject>']
  ]) {
    if (new RegExp(`<${tag}[\\s>/]`, 'i').test(s)) warnings.push(`contains ${why}`);
  }
  return { markup: s, viewBox, width, height, warnings };
}

// Prefix of the ids in each inlined copy: ID_PREFIX<band>-<file>-<size>-<id>.
const ID_PREFIX = 'svgr';

/** Prefixes every id and its references (url(#x), href="#x") in one copy. */
function prefixIds(markup, prefix) {
  return markup
    .replace(/\sid\s*=\s*(["'])([^"']+)\1/g, (_, q, id) => ` id=${q}${prefix}${id}${q}`)
    .replace(/url\(\s*(['"]?)#([^'")]+)\1\s*\)/g, (_, q, id) => `url(#${prefix}${id})`)
    .replace(
      /((?:xlink:)?href\s*=\s*)(["'])#([^"']+)\2/g,
      (_, a, q, id) => `${a}${q}#${prefix}${id}${q}`
    );
}

function buildSheet({ files, svgs, sizes, bands, cols, title }) {
  const cells = (band, bi) =>
    files
      .map((file, fi) => {
        const boxes = sizes
          .map(
            (size, si) =>
              `<div class="box" style="width:${size}px;height:${size}px">${prefixIds(svgs[fi].markup, `${ID_PREFIX}${bi}-${fi}-${si}-`)}</div>`
          )
          .join('');
        const label = escapeHtml(file.label);
        return `<div class="cell" data-file="${fi}"><div class="row">${boxes}</div><div class="label">${label}</div></div>`;
      })
      .join('');
  const sections = bands
    .map(
      (band, bi) =>
        `<section class="band" style="background:${escapeHtml(band.bg)};color:${escapeHtml(band.fg)}">` +
        `<div class="head">${escapeHtml(title)} | bg ${escapeHtml(band.bg)} | ink ${escapeHtml(band.fg)} | sizes ${sizes.join(', ')} px</div>` +
        `<div class="grid">${cells(band, bi)}</div></section>`
    )
    .join('');
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    html, body { margin: 0; }
    body { display: inline-block; background: #808080; }
    .band { padding: 12px 16px 16px; font: 11px/1.35 ui-monospace, Menlo, Consolas, monospace; }
    .head { margin-bottom: 10px; opacity: 0.75; white-space: nowrap; }
    .grid { display: grid; grid-template-columns: repeat(${cols}, max-content); gap: 14px 22px; align-items: end; }
    .cell { display: flex; flex-direction: column; gap: 5px; }
    .row { display: flex; align-items: flex-end; gap: 10px; }
    .box { flex: none; outline: 1px solid color-mix(in srgb, currentColor 14%, transparent); }
    .box > svg { display: block; width: 100%; height: 100%; }
    .label { max-width: ${sizes.reduce((a, b) => a + b + 10, 0)}px; overflow-wrap: anywhere; }
  </style></head><body>${sections}</body></html>`;
}

/** Runs in the page: element, shape and colour counts of each file's first copy. */
function measure() {
  const shapes = 'path,circle,ellipse,rect,line,polyline,polygon';
  const paint = ['fill', 'stroke', 'stop-color', 'color'];
  const out = [];
  for (const cell of document.querySelectorAll('.band:first-of-type .cell')) {
    const svg = cell.querySelector('svg');
    const colors = new Set();
    for (const el of [svg, ...svg.querySelectorAll('*')]) {
      for (const p of paint) {
        for (const v of [el.getAttribute(p), el.style?.getPropertyValue(p)]) {
          // Report url(#id) as written in the file, without the copy's id prefix.
          if (v && v !== 'none') colors.add(v.trim().replace(/#svgr\d+-\d+-\d+-/g, '#'));
        }
      }
    }
    out.push({
      index: Number(cell.dataset.file),
      elements: svg.querySelectorAll('*').length,
      shapes: svg.querySelectorAll(shapes).length,
      colors: [...colors].sort()
    });
  }
  const r = document.body.getBoundingClientRect();
  return { cells: out, width: Math.ceil(r.width), height: Math.ceil(r.height) };
}

async function main() {
  const { values: o } = parseArgs({
    options: {
      in: { type: 'string', multiple: true, default: [] },
      sizes: { type: 'string', default: '16,24,48,128' },
      bg: { type: 'string', default: '#f4ecdc,#1c1915' },
      fg: { type: 'string' },
      cols: { type: 'string' },
      dpr: { type: 'string', default: '1' },
      out: { type: 'string' },
      meta: { type: 'string' },
      title: { type: 'string' },
      force: { type: 'boolean', default: false },
      help: { type: 'boolean', short: 'h', default: false }
    }
  });
  if (o.help) {
    printHeader(import.meta.url);
    return;
  }
  if (!o.out) throw new Error('--out PATH is required');
  const files = collectSvgs(o.in.flatMap(list));
  if (files.length === 0) throw new Error('no SVG files given (--in)');
  const sizes = list(o.sizes).map(Number);
  if (sizes.some((n) => !(n > 0))) throw new Error(`--sizes: bad list ${o.sizes}`);
  const bgs = list(o.bg);
  const fgs = o.fg ? list(o.fg) : [];
  const bands = bgs.map((bg, i) => ({ bg, fg: fgs[i] ?? inkFor(bg) }));
  const cols = Math.max(1, Number(o.cols ?? Math.min(files.length, 6)) || 1);
  const dpr = Number(o.dpr);
  if (!(dpr > 0)) throw new Error(`--dpr: bad value ${o.dpr}`);

  const svgs = files.map(({ file }) => {
    const source = fs.readFileSync(file, 'utf8');
    try {
      return { ...prepareSvg(source), bytes: Buffer.byteLength(source) };
    } catch (err) {
      throw new Error(`${file}: ${err.message}`);
    }
  });
  const title = o.title ?? `${files.length} SVG${files.length === 1 ? '' : 's'}`;
  const html = buildSheet({ files, svgs, sizes, bands, cols, title });

  const chrome = await launch({ force: o.force });
  let browser = null;
  let page = null;
  try {
    browser = await CDP.connect(chrome.wsUrl);
    page = await openPage(browser);
    await page.send('Page.enable');
    // Lay out on a very wide viewport, so the shrink-to-fit sheet never wraps.
    await page.send('Emulation.setDeviceMetricsOverride', {
      width: 10_000,
      height: 1_000,
      deviceScaleFactor: dpr,
      mobile: false
    });
    const { frameTree } = await page.send('Page.getFrameTree');
    await page.send('Page.setDocumentContent', { frameId: frameTree.frame.id, html });
    await evaluate(page, async () => {
      await document.fonts.ready;
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    });
    const m = await evaluate(page, measure);
    if (m.height * dpr > 16_384 || m.width * dpr > 16_384) {
      console.error(
        `svg-render: the sheet is ${m.width}x${m.height} CSS px; Chrome may clip past 16384 device px`
      );
    }
    await page.send('Emulation.setDeviceMetricsOverride', {
      width: m.width,
      height: m.height,
      deviceScaleFactor: dpr,
      mobile: false
    });
    const { data } = await page.send('Page.captureScreenshot', {
      format: 'png',
      fromSurface: true,
      clip: { x: 0, y: 0, width: m.width, height: m.height, scale: 1 }
    });
    fs.mkdirSync(path.dirname(path.resolve(o.out)), { recursive: true });
    fs.writeFileSync(o.out, Buffer.from(data, 'base64'));
    console.error(
      `saved ${o.out} (${m.width * dpr}x${m.height * dpr} px: ${files.length} files, ` +
        `sizes ${sizes.join(',')}, ${bands.length} background${bands.length === 1 ? '' : 's'}, dpr ${dpr})`
    );

    if (o.meta) {
      const byIndex = new Map(m.cells.map((c) => [c.index, c]));
      const meta = {
        sheet: o.out,
        sizes,
        backgrounds: bands,
        cols,
        dpr,
        files: files.map(({ file, label }, i) => ({
          file,
          label,
          bytes: svgs[i].bytes,
          viewBox: svgs[i].viewBox,
          width: svgs[i].width,
          height: svgs[i].height,
          elements: byIndex.get(i)?.elements ?? null,
          shapes: byIndex.get(i)?.shapes ?? null,
          colors: byIndex.get(i)?.colors ?? [],
          warnings: svgs[i].warnings
        }))
      };
      fs.mkdirSync(path.dirname(path.resolve(o.meta)), { recursive: true });
      fs.writeFileSync(o.meta, `${JSON.stringify(meta, null, 2)}\n`);
      console.error(`saved ${o.meta}`);
    }
  } finally {
    await page?.close();
    browser?.close();
    await chrome.close();
  }
}

if (isMain(import.meta.url)) main().catch(reportAndExit);
