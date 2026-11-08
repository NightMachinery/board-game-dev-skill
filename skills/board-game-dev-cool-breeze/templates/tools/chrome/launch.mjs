#!/usr/bin/env node
// Launches our own headless Chromium for the CDP tools, or attaches to one
// that is already running. Never touches the owner's everyday browser: the
// binary is Playwright's Chromium (Chrome for Testing, its own app with its
// own bundle id), not the installed Google Chrome (D26).
//
// Library:
//   import { launch } from './launch.mjs';
//   const chrome = await launch();        // { wsUrl, httpOrigin, version, close, ... }
//   try { ... } finally { await chrome.close(); }
//
// CLI (a self-test, or a browser held open for several tool runs):
//   python3 tools/heavy.py run --kind browser -- node tools/chrome/launch.mjs
//   python3 tools/heavy.py run --kind browser -- node tools/chrome/launch.mjs --hold 600
//     then, from another shell: CHROME_CDP=http://127.0.0.1:41739 node tools/chrome/shot.mjs ...
//
// Rules it enforces:
// - It launches only inside the guard's browser lock (BGD_HEAVY_KIND=browser,
//   which `heavy.py run --kind browser` sets) or with --force / {force: true}.
// - It finds the DevTools endpoint from the "DevTools listening on" line in
//   its own Chrome's stderr, never by probing a port that another browser
//   might own, and it refuses to start when the port is already taken.
// - Each launch gets a fresh profile, <os tmpdir>/bgd-chrome-<pid>-XXXXXX,
//   so `ps -axo pid=,command=` finds any browser we left behind.
// - close() kills Chrome's process group, then any process still naming the
//   profile directory, then deletes the profile. Exit, SIGINT, SIGTERM and
//   SIGHUP do the same.
// - If CHROME_CDP is set (http://host:port of a running Chrome's DevTools),
//   it attaches instead, and close() never kills that browser.
//
// Env: CHROME_PORT (default 41739; 0 lets Chrome pick a free port),
// CHROME_BIN (another Chromium executable to use instead of Playwright's),
// CHROME_CDP (attach mode).

import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { getJSON, sleep } from './cdp.mjs';

import { project } from '../config.mjs';
export const DEFAULT_PORT = project.ports.chrome;
// The e2e package's Playwright knows where its Chromium is installed.
const E2E_PACKAGE = fileURLToPath(new URL('../../package.json', import.meta.url));

/** Thrown when a launch is refused because the guard's browser lock is not held. */
export class LaunchRefused extends Error {}

export const REFUSAL = [
  'chrome: refusing to start Chrome outside the heavy.py browser lock.',
  'Run the tool through the guard, for example:',
  '  python3 tools/heavy.py run --kind browser -- node tools/chrome/shot.mjs --url / --out /tmp/home.png',
  'or pass --force when you are sure no other browser job is running.',
  'To use a Chrome that is already running instead, set CHROME_CDP=http://127.0.0.1:<port>.'
].join('\n');

/** The command line flags (infra plan, section 4). */
export function chromeFlags({ port, profileDir }) {
  return [
    '--headless=new',
    `--remote-debugging-port=${port}`,
    '--remote-debugging-address=127.0.0.1',
    `--user-data-dir=${profileDir}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    '--disable-background-networking',
    '--disable-component-update',
    '--disable-sync',
    '--mute-audio',
    '--hide-scrollbars',
    '--use-mock-keychain', // no macOS keychain prompts
    '--password-store=basic',
    'about:blank'
  ];
}

function isExecutable(file) {
  try {
    fs.accessSync(file, fs.constants.X_OK);
    return fs.statSync(file).isFile();
  } catch {
    return false;
  }
}

export function findChrome() {
  const fromEnv = process.env.CHROME_BIN;
  if (fromEnv) {
    if (/Google Chrome\.app|Brave Browser|Microsoft Edge\.app/i.test(fromEnv))
      throw new Error('chrome: CHROME_BIN must be a testing Chromium, never an everyday browser');
    if (!isExecutable(fromEnv))
      throw new Error(`chrome: CHROME_BIN=${fromEnv} is not an executable`);
    return fromEnv;
  }
  let bin = null;
  try {
    bin = createRequire(E2E_PACKAGE)('playwright').chromium.executablePath();
  } catch {
    // No e2e dependencies installed yet: fall through to the hint below.
  }
  if (bin && isExecutable(bin)) return bin;
  throw new Error(
    "chrome: Playwright's Chromium is not installed. Run `make install` (it runs " +
      '`playwright install chromium --no-shell`), or set CHROME_BIN to a Chromium executable.'
  );
}

function portInUse(port) {
  return new Promise((resolve) => {
    const sock = net.connect({ host: '127.0.0.1', port });
    const done = (used) => {
      sock.destroy();
      resolve(used);
    };
    sock.setTimeout(500, () => done(false));
    sock.once('connect', () => done(true));
    sock.once('error', () => done(false));
  });
}

/** PIDs (other than ours) whose command line contains `needle`, a literal. */
function pidsMentioning(needle) {
  if (!needle || needle.length < 12) return []; // never match on a short or empty string
  const ps = spawnSync('/bin/ps', ['-axo', 'pid=,command='], { encoding: 'utf8' });
  if (ps.status !== 0) return [];
  const pids = [];
  for (const line of ps.stdout.split('\n')) {
    const m = /^\s*(\d+)\s+(.*)$/.exec(line);
    if (m && m[2].includes(needle) && Number(m[1]) !== process.pid) pids.push(Number(m[1]));
  }
  return pids;
}

function alive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function killGroup(pid, signal) {
  try {
    process.kill(-pid, signal); // the whole process group (spawned detached)
  } catch {
    try {
      process.kill(pid, signal);
    } catch {
      // already gone
    }
  }
}

const live = new Set(); // handles of browsers we launched and have not closed
let hooksInstalled = false;

function installExitHooks() {
  if (hooksInstalled) return;
  hooksInstalled = true;
  process.on('exit', () => {
    for (const h of live) h.closeSync();
  });
  const signals = { SIGINT: 2, SIGTERM: 15, SIGHUP: 1 };
  for (const [sig, num] of Object.entries(signals)) {
    process.on(sig, () => {
      for (const h of live) h.closeSync();
      process.exit(128 + num);
    });
  }
}

/**
 * Launches headless Chrome (or attaches, when CHROME_CDP is set) and waits
 * until its DevTools endpoint answers. Resolves with
 * { attached, httpOrigin, wsUrl, version, pid, profileDir, close }.
 */
export async function launch({ force = false, port, timeoutMs = 20_000 } = {}) {
  const attachTo = process.env.CHROME_CDP;
  if (attachTo) {
    const version = await getJSON(attachTo, '/json/version').catch((err) => {
      throw new Error(
        `chrome: CHROME_CDP=${attachTo} does not answer /json/version (${err.message})`
      );
    });
    return {
      attached: true,
      httpOrigin: attachTo,
      wsUrl: version.webSocketDebuggerUrl,
      version,
      pid: null,
      profileDir: null,
      close: async () => {} // not ours: never kill it
    };
  }

  if (process.env.BGD_HEAVY_KIND !== 'browser' && !force) throw new LaunchRefused(REFUSAL);

  const wantPort = port ?? Number(process.env.CHROME_PORT ?? DEFAULT_PORT);
  if (!Number.isInteger(wantPort) || wantPort < 0 || wantPort > 65535) {
    throw new Error(`chrome: bad port ${process.env.CHROME_PORT ?? port}`);
  }
  if (wantPort !== 0 && (await portInUse(wantPort))) {
    throw new Error(
      `chrome: 127.0.0.1:${wantPort} is already in use. A browser left behind? Check with ` +
        `ps -axo pid=,command=. Set CHROME_CDP=http://127.0.0.1:${wantPort} to attach to it, ` +
        'or CHROME_PORT to use another port.'
    );
  }

  const bin = findChrome();
  const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), `bgd-chrome-${process.pid}-`));
  const child = spawn(bin, chromeFlags({ port: wantPort, profileDir }), {
    detached: true, // its own process group, so close() can kill helpers too
    stdio: ['ignore', 'ignore', 'pipe']
  });
  // Chrome prints "DevTools listening on ws://127.0.0.1:<port>/devtools/browser/<id>"
  // to stderr once DevTools is up. Reading it from our own child's stderr
  // proves that the endpoint we talk to belongs to the Chrome we started.
  // (Headless Chrome does not write DevToolsActivePort for a fixed port.)
  let stderrTail = '';
  let listening = null;
  child.stderr.on('data', (chunk) => {
    stderrTail = (stderrTail + chunk).slice(-4000);
    listening ??= /DevTools listening on (ws:\/\/\S+)/.exec(stderrTail)?.[1] ?? null;
  });
  let exited = false;
  const exitPromise = new Promise((resolve) => child.once('exit', resolve)).then(() => {
    exited = true;
  });
  child.once('error', () => {}); // reported through the readiness timeout below

  let closed = false;
  const handle = {
    attached: false,
    httpOrigin: null,
    wsUrl: null,
    version: null,
    pid: child.pid,
    profileDir,
    // Synchronous last-resort cleanup, for process exit and signals.
    closeSync() {
      if (closed) return;
      closed = true;
      live.delete(handle);
      if (child.pid && !exited) killGroup(child.pid, 'SIGKILL');
      for (const pid of pidsMentioning(profileDir)) killGroup(pid, 'SIGKILL');
      fs.rmSync(profileDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
    },
    async close() {
      if (closed) return;
      closed = true;
      live.delete(handle);
      if (child.pid && !exited) {
        killGroup(child.pid, 'SIGTERM');
        await Promise.race([exitPromise, sleep(5_000)]);
        if (!exited) {
          killGroup(child.pid, 'SIGKILL');
          await Promise.race([exitPromise, sleep(2_000)]);
        }
      }
      // Helpers that left the process group, if any: matched on the unique
      // profile path, printed, then killed by PID.
      for (let i = 0; i < 20; i++) {
        const left = pidsMentioning(profileDir).filter(alive);
        if (left.length === 0) break;
        if (i === 0) console.error(`chrome: killing leftover processes ${left.join(' ')}`);
        for (const pid of left) killGroup(pid, 'SIGKILL');
        await sleep(100);
      }
      fs.rmSync(profileDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
    }
  };
  live.add(handle);
  installExitHooks();

  const deadline = Date.now() + timeoutMs;
  try {
    for (;;) {
      if (exited) throw new Error(`chrome: exited during startup.\n${stderrTail.trim()}`);
      if (Date.now() > deadline) {
        throw new Error(
          `chrome: DevTools did not come up within ${timeoutMs} ms.\n${stderrTail.trim()}`
        );
      }
      if (listening) {
        const httpOrigin = `http://${new URL(listening).host}`;
        const version = await getJSON(httpOrigin, '/json/version').catch(() => null);
        if (version?.webSocketDebuggerUrl === listening) {
          Object.assign(handle, { httpOrigin, wsUrl: listening, version });
          return handle;
        }
      }
      await sleep(100);
    }
  } catch (err) {
    await handle.close();
    throw err;
  }
}

/** Runs fn(chrome) with a launched (or attached) browser and always closes it. */
export async function withChrome(fn, opts = {}) {
  const chrome = await launch(opts);
  try {
    return await fn(chrome);
  } finally {
    await chrome.close();
  }
}

/**
 * Shared CLI error handling for the tools: refusals exit 2, errors 1.
 * Expected errors (a plain Error, such as a usage mistake, or a parseArgs
 * error) print their message only, crashes their stack; BGD_STACK=1
 * prints the stack for every error.
 */
export function reportAndExit(err) {
  const refused = err instanceof LaunchRefused;
  const expected =
    err instanceof Error &&
    ((typeof err.code === 'string' && err.code.startsWith('ERR_PARSE_ARGS_')) ||
      Object.getPrototypeOf(err) === Error.prototype);
  const brief = refused || (expected && process.env.BGD_STACK !== '1');
  console.error(brief ? err.message : `${err?.stack ?? err}`);
  process.exit(refused ? 2 : 1);
}

/** True when the module at `metaUrl` is the script node was asked to run. */
export function isMain(metaUrl) {
  return !!process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(metaUrl);
}

/** Prints a tool's header comment (after the shebang) as its --help text. */
export function printHeader(metaUrl) {
  const lines = fs.readFileSync(fileURLToPath(metaUrl), 'utf8').split('\n').slice(1);
  const end = lines.findIndex((l) => !l.startsWith('//'));
  console.log(
    lines
      .slice(0, end)
      .map((l) => l.replace(/^\/\/ ?/, ''))
      .join('\n')
  );
}

async function main() {
  const { values } = parseArgs({
    options: {
      force: { type: 'boolean', default: false },
      hold: { type: 'string' },
      help: { type: 'boolean', short: 'h', default: false }
    },
    allowPositionals: false
  });
  if (values.help) {
    console.log(
      'Usage: node tools/chrome/launch.mjs [--force] [--hold SECONDS]\n\n' +
        'Without --hold: start headless Chrome, print its version as JSON, close it (a self-test).\n' +
        'With --hold: keep it open for SECONDS (or until Ctrl-C) and print the CHROME_CDP to\n' +
        'export so the other tools attach to it. Run under heavy.py --kind browser.'
    );
    return;
  }
  const chrome = await launch({ force: values.force });
  const info = {
    browser: chrome.version.Browser,
    cdp: chrome.httpOrigin,
    pid: chrome.pid,
    profileDir: chrome.profileDir,
    attached: chrome.attached
  };
  console.log(JSON.stringify(info));
  if (values.hold !== undefined) {
    const secs = Number(values.hold || 600);
    if (!Number.isFinite(secs) || secs <= 0)
      throw new Error(`--hold needs a positive number of seconds`);
    console.log(`CHROME_CDP=${chrome.httpOrigin}  (holding for ${secs} s; Ctrl-C closes it)`);
    await sleep(secs * 1000);
  }
  await chrome.close();
  if (chrome.profileDir) {
    const left = pidsMentioning(chrome.profileDir);
    console.log(
      JSON.stringify({
        closed: true,
        leftover: left,
        profileRemoved: !fs.existsSync(chrome.profileDir)
      })
    );
  }
}

if (isMain(import.meta.url)) main().catch(reportAndExit);
