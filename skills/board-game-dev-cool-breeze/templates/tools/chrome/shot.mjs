#!/usr/bin/env node
// Screenshot and DOM probe for one page of the running app, over CDP.
//
//   python3 tools/heavy.py run --kind browser -- node tools/chrome/shot.mjs \
//     --url /play/ABCD --token my-gameShotTokenA00000A --name Ana --vp 390x844@3 \
//     --probe --out x.png
//
// Flags (`--flag value` or `--flag=value`):
//   --origin URL     app origin (default $BGD_ORIGIN or http://127.0.0.1:41731)
//   --url PATH       page to open, relative to --origin (default /); a full URL also works
//   --token T        written to localStorage my-game:token before the page loads; it
//                    must be 22 base64url characters ending in A, Q, g or w, or
//                    the app replaces it (so the script refuses any other value)
//   --name N         written to localStorage my-game:name
//   --storage JSON   a JSON object of localStorage keys to write before the page
//                    loads, such as '{"my-game:settings":{"animationSpeed":"off"}}': a
//                    string value is written as it is, any other value as its
//                    JSON. Repeatable; later keys win, and --token, --name and
//                    --name win over the same key here
//   --scheme S       light | dark: the emulated OS colour scheme (what "system" follows)
//   --vp V           WxH[@dpr] or a preset: mobile (390x844@2), desktop (1280x800@1);
//                    default 390x844@2. A short side under 600 px also emulates a phone
//                    (mobile viewport and touch).
//   --motion M       reduce (default) | no-preference: prefers-reduced-motion
//   --wait-ready     wait for [data-ready] on <html>, at most 2.5 s (else a fixed settle)
//   --settle MS      the fixed settle without --wait-ready (default 800)
//   --probe          print a JSON report on stdout (see README.md)
//   --out PATH       write a PNG of the viewport; --full captures the whole page
//   --selector CSS   with --out: scroll the first element matching CSS into view,
//                    wait for layout, and capture only its bounding box (plus
//                    --pad); fails when nothing matches or the match has no size.
//                    An element taller than the viewport grows the emulated
//                    viewport's height (not its width) until it fits.
//   --pad PX         the margin kept around the --selector box (default 8)
//   --vision V       greyscale | deuteranopia | protanopia | tritanopia: render as
//                    seen with that colour vision. The three deficiencies use
//                    Chrome's own emulation (Emulation.setEmulatedVisionDeficiency);
//                    greyscale is a grayscale(1) filter on <html>.
//   --no-autofocus   keep autofocus from scrolling the page: focus() is made to
//                    pass preventScroll, the autofocus property is ignored, and the
//                    active element is blurred before the probe and the capture
//   --force          launch Chrome without the heavy.py browser lock
//
// Identity works as in the app: the token and name (and any
// --storage keys) go into localStorage on the page's origin before any of
// its scripts run, so the app starts as that player with those settings.
// The token must have the real shape, the base64url form of 16 bytes: 22
// characters of A-Z, a-z, 0-9, - and _, the last of which only carries two
// bits and so is A, Q, g or w (web/src/lib/session/identity.ts
// isValidToken). The client replaces any other stored value with a fresh
// token, and the page would open as a stranger, so --token refuses it.
// Each run uses a fresh browser context, so nothing carries over between
// runs.

import fs from 'node:fs';
import { probePage } from './probe.mjs';
import path from 'node:path';
import { parseArgs } from 'node:util';
import { CDP, evaluate, openPage, sleep } from './cdp.mjs';
import { isMain, launch, printHeader, reportAndExit } from './launch.mjs';

const PRESETS = { mobile: '390x844@2', desktop: '1280x800@1' };
import { project, storagePrefix } from '../config.mjs';

/** The token shape the client keeps (identity.ts isValidToken). */
export const TOKEN_RE = /^[A-Za-z0-9_-]{21}[AQgw]$/;
/** --vision values: greyscale is a CSS filter, the rest Chrome's emulation. */
const VISIONS = ['greyscale', 'deuteranopia', 'protanopia', 'tritanopia'];

// Installed before any page script with --no-autofocus. An autofocused
// field (the name prompt's input) otherwise scrolls its scrolling container
// to itself, which moves /dev/gallery off its top and leaves a --full
// capture blank. Scripted focus keeps working, it just never scrolls, and
// the autofocus property (which Svelte sets) is ignored, so the browser's
// own autofocus never fires either.
const NO_AUTOFOCUS = `(() => {
  const focus = HTMLElement.prototype.focus;
  HTMLElement.prototype.focus = function (options) {
    return focus.call(this, { ...options, preventScroll: true });
  };
  const svgFocus = SVGElement.prototype.focus;
  if (svgFocus) {
    SVGElement.prototype.focus = function (options) {
      return svgFocus.call(this, { ...options, preventScroll: true });
    };
  }
  Object.defineProperty(HTMLElement.prototype, 'autofocus', {
    configurable: true,
    get() { return false; },
    set() {}
  });
})();`;
/** The tallest viewport --selector grows to, in CSS px. */
const MAX_GROWN_HEIGHT = 12_000;

/**
 * Parses the --storage values into [key, value] pairs, in order: each is a
 * JSON object whose string values are kept as they are and whose other
 * values are stored as their JSON (localStorage holds strings only).
 */
export function parseStorage(specs) {
  const pairs = [];
  for (const spec of specs) {
    let obj;
    try {
      obj = JSON.parse(spec);
    } catch (e) {
      throw new Error(`--storage: not JSON (${e.message}): ${spec}`);
    }
    if (obj === null || typeof obj !== 'object' || Array.isArray(obj))
      throw new Error(`--storage: expected a JSON object of key to value, got ${spec}`);
    for (const [k, v] of Object.entries(obj)) {
      if (v === undefined || v === null)
        throw new Error(`--storage: ${k} has no value; leave the key out instead`);
      pairs.push([k, typeof v === 'string' ? v : JSON.stringify(v)]);
    }
  }
  return pairs;
}

export function parseViewport(spec) {
  const m = /^(\d+)x(\d+)(?:@(\d+(?:\.\d+)?))?$/.exec(PRESETS[spec] ?? spec);
  if (!m) throw new Error(`--vp: expected WxH[@dpr], mobile or desktop, got ${spec}`);
  const width = Number(m[1]);
  const height = Number(m[2]);
  const dpr = Number(m[3] ?? 1);
  if (width < 1 || height < 1 || dpr <= 0) throw new Error(`--vp: bad size ${spec}`);
  return { width, height, dpr, mobile: Math.min(width, height) < 600 };
}

/** Navigates and waits for the load event of a cross-document navigation. */
async function navigate(page, url, timeoutMs = 15_000) {
  const loaded = page.waitFor('Page.loadEventFired', { timeoutMs });
  loaded.catch(() => {}); // a same-document navigation never fires it
  const r = await page.send('Page.navigate', { url });
  if (r.errorText) throw new Error(`navigate ${url}: ${r.errorText}`);
  if (r.loaderId) await loaded;
}

/**
 * Runs in the page: scrolls the first match of `selector` into view, waits
 * two frames for layout, and returns its box in viewport CSS px, or an error
 * string. Keep it self-contained.
 */
async function locate(selector, pad) {
  let el;
  try {
    el = document.querySelector(selector);
  } catch (e) {
    return { error: `--selector: not a valid CSS selector: ${selector} (${e.message})` };
  }
  if (!el) return { error: `--selector: nothing on the page matches ${selector}` };
  // scroll-margin keeps the pad visible above the element, in the window
  // and in any scrolling ancestor alike.
  const margin = el.style.scrollMarginTop;
  el.style.scrollMarginTop = `${pad}px`;
  el.scrollIntoView({ block: 'start', inline: 'nearest' });
  el.style.scrollMarginTop = margin;
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  const r = el.getBoundingClientRect();
  if (r.width < 1 || r.height < 1)
    return { error: `--selector: ${selector} matched an element with no size (hidden?)` };
  const count = document.querySelectorAll(selector).length;
  return { x: r.left, y: r.top, width: r.width, height: r.height, count };
}

async function main() {
  const { values: o } = parseArgs({
    options: {
      origin: { type: 'string', default: process.env.BGD_ORIGIN ?? `http://127.0.0.1:${project.ports.server}` },
      url: { type: 'string', default: '/' },
      token: { type: 'string' },
      name: { type: 'string' },
      storage: { type: 'string', multiple: true, default: [] },
      scheme: { type: 'string' },
      vp: { type: 'string', default: '390x844@2' },
      motion: { type: 'string', default: 'reduce' },
      'wait-ready': { type: 'boolean', default: false },
      settle: { type: 'string', default: '800' },
      probe: { type: 'boolean', default: false },
      out: { type: 'string' },
      full: { type: 'boolean', default: false },
      selector: { type: 'string' },
      pad: { type: 'string', default: '8' },
      vision: { type: 'string' },
      'no-autofocus': { type: 'boolean', default: false },
      force: { type: 'boolean', default: false },
      help: { type: 'boolean', short: 'h', default: false }
    }
  });
  if (o.help) {
    printHeader(import.meta.url);
    return;
  }
  if (!o.probe && !o.out) throw new Error('nothing to do: pass --out PATH, --probe, or both');
  if (o.selector !== undefined && !o.out) throw new Error('--selector needs --out PATH');
  if (o.selector !== undefined && o.full) throw new Error('--selector and --full do not mix');
  if (o.selector !== undefined && !o.selector.trim()) throw new Error('--selector: empty');
  const pad = Number(o.pad);
  if (!Number.isFinite(pad) || pad < 0)
    throw new Error(`--pad: expected a number >= 0, got ${o.pad}`);
  if (o.token !== undefined && !TOKEN_RE.test(o.token))
    throw new Error(
      `--token: expected 22 base64url characters ending in A, Q, g or w (the client replaces anything else), got ${o.token}`
    );
  if (o.scheme && !['light', 'dark'].includes(o.scheme)) throw new Error('--scheme: light or dark');
  if (!['reduce', 'no-preference'].includes(o.motion))
    throw new Error('--motion: reduce or no-preference');
  if (o.vision !== undefined && !VISIONS.includes(o.vision))
    throw new Error(`--vision: one of ${VISIONS.join(', ')}, got ${o.vision}`);
  const vp = parseViewport(o.vp);
  const extraStorage = parseStorage(o.storage);
  const target = new URL(o.url, o.origin);

  const chrome = await launch({ force: o.force });
  let browser = null;
  let page = null;
  try {
    browser = await CDP.connect(chrome.wsUrl);
    page = await openPage(browser);

    // Hygiene, reported by --probe: console errors, exceptions, failed requests.
    const errors = [];
    const failed = [];
    const urls = new Map(); // requestId -> url, for loadingFailed
    page.on('Network.requestWillBeSent', (p) => urls.set(p.requestId, p.request.url));
    page.on('Runtime.consoleAPICalled', (p) => {
      if (p.type === 'error' || p.type === 'assert') {
        errors.push(
          `console.${p.type}: ${p.args.map((a) => a.value ?? a.description ?? '').join(' ')}`
        );
      }
    });
    page.on('Runtime.exceptionThrown', (p) => {
      errors.push(
        `uncaught: ${p.exceptionDetails.exception?.description ?? p.exceptionDetails.text}`
      );
    });
    page.on('Log.entryAdded', (p) => {
      if (p.entry.level === 'error')
        errors.push(`log: ${p.entry.text} ${p.entry.url ?? ''}`.trim());
    });
    page.on('Network.responseReceived', (p) => {
      if (p.response.status >= 400) failed.push(`HTTP ${p.response.status} ${p.response.url}`);
    });
    page.on('Network.loadingFailed', (p) => {
      if (!p.canceled) failed.push(`${p.errorText} ${urls.get(p.requestId) ?? p.type}`);
    });
    await Promise.all(['Page', 'Runtime', 'Log', 'Network'].map((d) => page.send(`${d}.enable`)));

    // Viewport through metrics emulation, never by resizing a window.
    await page.send('Emulation.setDeviceMetricsOverride', {
      width: vp.width,
      height: vp.height,
      deviceScaleFactor: vp.dpr,
      mobile: vp.mobile
    });
    await page.send('Emulation.setTouchEmulationEnabled', {
      enabled: vp.mobile,
      maxTouchPoints: 5
    });
    const features = [{ name: 'prefers-reduced-motion', value: o.motion }];
    if (o.scheme) features.push({ name: 'prefers-color-scheme', value: o.scheme });
    await page.send('Emulation.setEmulatedMedia', { features });
    if (o.vision && o.vision !== 'greyscale') {
      await page.send('Emulation.setEmulatedVisionDeficiency', { type: o.vision });
    }
    if (o['no-autofocus']) {
      await page.send('Page.addScriptToEvaluateOnNewDocument', { source: NO_AUTOFOCUS });
    }

    // --storage first, so the dedicated flags win over the same key.
    const storage = [...extraStorage];
    if (o.token !== undefined) storage.push([`${storagePrefix}token`, o.token]);
    if (o.name !== undefined) storage.push([`${storagePrefix}name`, o.name]);
    // The keys are written by a new-document script, which runs on the
    // target origin before any of the page's own scripts (the theme
    // bootstrap in app.html included). So the app boots once, already
    // holding this identity, and no extra page load adds noise to the probe.
    let storageScript = null;
    if (storage.length > 0) {
      const source =
        `(() => { if (location.origin !== ${JSON.stringify(target.origin)}) return;` +
        ` try { for (const [k, v] of ${JSON.stringify(storage)}) localStorage.setItem(k, v); }` +
        ` catch (e) { console.error('shot.mjs: cannot write localStorage: ' + e); } })();`;
      ({ identifier: storageScript } = await page.send('Page.addScriptToEvaluateOnNewDocument', {
        source
      }));
    }

    await navigate(page, target.href);
    if (storageScript) {
      await page.send('Page.removeScriptToEvaluateOnNewDocument', { identifier: storageScript });
    }
    if (o['wait-ready']) {
      const deadline = Date.now() + 2_500;
      while (Date.now() < deadline) {
        if (await evaluate(page, () => document.documentElement.hasAttribute('data-ready'))) break;
        await sleep(50);
      }
    } else {
      await sleep(Number(o.settle) || 0);
    }
    await evaluate(page, async () => {
      await document.fonts.ready;
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    });
    if (o['no-autofocus']) {
      // Drop the focus (and its ring) that an autofocused field still took.
      await evaluate(page, async () => {
        if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
        await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      });
    }
    if (o.vision === 'greyscale') {
      // A filter on the root element greys everything, fixed layers included.
      await evaluate(page, async () => {
        document.documentElement.style.setProperty('filter', 'grayscale(1)', 'important');
        await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      });
    }

    if (o.probe) {
      const report = await evaluate(page, probePage);
      report.vp = `${vp.width}x${vp.height}@${vp.dpr}`;
      report.errors = errors;
      report.failed = failed;
      console.log(JSON.stringify(report, null, 2));
    }

    if (o.out) {
      const params = { format: 'png', fromSurface: true };
      let what = o.full ? ', full page' : '';
      if (o.selector !== undefined) {
        let box = await evaluate(page, locate, o.selector, pad);
        if (box.error) throw new Error(box.error);
        // Content below the viewport is not painted when the page scrolls
        // inside a container rather than the window (the app shell does),
        // so captureBeyondViewport cannot reach it. Instead, a box that
        // does not fit grows the emulated viewport's height (never its
        // width) until it does, and the capture stays inside the viewport.
        let height = vp.height;
        for (let i = 0; i < 4 && box.y + box.height + pad > height + 0.5; i++) {
          if (height >= MAX_GROWN_HEIGHT) break;
          height = Math.min(MAX_GROWN_HEIGHT, Math.ceil(box.y + box.height + pad) + 1);
          await page.send('Emulation.setDeviceMetricsOverride', {
            width: vp.width,
            height,
            deviceScaleFactor: vp.dpr,
            mobile: vp.mobile
          });
          box = await evaluate(page, locate, o.selector, pad);
          if (box.error) throw new Error(box.error);
        }
        if (box.y + box.height + pad > height + 0.5)
          console.error(`shot: ${o.selector} is taller than ${MAX_GROWN_HEIGHT} px; cut off`);
        // The clip is in document CSS px: the viewport box plus the scroll
        // offset, padded, and kept inside the document and the viewport.
        const m = await page.send('Page.getLayoutMetrics');
        const { pageX, pageY } = m.cssVisualViewport;
        const x0 = Math.max(pageX, Math.floor(box.x + pageX - pad));
        const y0 = Math.max(pageY, Math.floor(box.y + pageY - pad));
        const x1 = Math.min(pageX + vp.width, Math.ceil(box.x + pageX + box.width + pad));
        const y1 = Math.min(pageY + height, Math.ceil(box.y + pageY + box.height + pad));
        params.clip = { x: x0, y: y0, width: x1 - x0, height: y1 - y0, scale: 1 };
        what =
          `, ${o.selector} at ${x0},${y0} ${x1 - x0}x${y1 - y0}` +
          (height > vp.height ? `, viewport grown to ${vp.width}x${height} to fit it` : '') +
          (box.count > 1 ? `, first of ${box.count} matches` : '');
      } else if (o.full) {
        const { cssContentSize: s } = await page.send('Page.getLayoutMetrics');
        params.captureBeyondViewport = true;
        params.clip = {
          x: 0,
          y: 0,
          width: Math.ceil(s.width),
          height: Math.ceil(s.height),
          scale: 1
        };
      }
      const { data } = await page.send('Page.captureScreenshot', params);
      fs.mkdirSync(path.dirname(path.resolve(o.out)), { recursive: true });
      fs.writeFileSync(o.out, Buffer.from(data, 'base64'));
      if (o.vision) what += `, vision ${o.vision}`;
      console.error(`saved ${o.out} (${vp.width}x${vp.height}@${vp.dpr}${what})`);
    }
  } finally {
    await page?.close();
    browser?.close();
    await chrome.close();
  }
}

if (isMain(import.meta.url)) main().catch(reportAndExit);
