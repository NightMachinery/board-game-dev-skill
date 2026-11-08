// A tiny Chrome DevTools Protocol (CDP) client. Dependency-free: Node 24's
// built-in WebSocket and fetch.
//
//   import { CDP, openPage } from './cdp.mjs';
//   const browser = await CDP.connect(wsUrl);           // a webSocketDebuggerUrl
//   const page = await openPage(browser);               // isolated context + tab
//   await page.send('Page.navigate', { url });
//   const off = page.on('Runtime.consoleAPICalled', (p) => ...);
//   await page.waitFor('Page.loadEventFired', { timeoutMs: 15000 });
//   console.log(await evaluate(page, () => document.title));
//   await page.close();                                 // tab and context
//
// The protocol is {id, method, params[, sessionId]} out and {id, result |
// error} or {method, params[, sessionId]} in. We connect to the browser
// target and attach to pages in "flat" mode, so one socket carries every
// session and each message names its sessionId.

const DEFAULT_TIMEOUT_MS = 30_000;

export class CDP {
  #ws;
  #nextId = 0;
  #pending = new Map(); // id -> {resolve, reject, method, timer}
  #listeners = new Map(); // "sessionId|method" -> Set<fn>
  #closed = false;

  constructor(ws) {
    this.#ws = ws;
    ws.addEventListener('message', (ev) => this.#onMessage(ev));
    ws.addEventListener('close', () => this.#onClose());
  }

  /** Opens a WebSocket to a webSocketDebuggerUrl and resolves once open. */
  static connect(url, { timeoutMs = 10_000 } = {}) {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(url);
      const timer = setTimeout(() => {
        ws.close();
        reject(new Error(`cdp: timed out connecting to ${url}`));
      }, timeoutMs);
      ws.addEventListener(
        'open',
        () => {
          clearTimeout(timer);
          resolve(new CDP(ws));
        },
        { once: true }
      );
      ws.addEventListener(
        'error',
        () => {
          clearTimeout(timer);
          reject(new Error(`cdp: cannot connect to ${url}`));
        },
        { once: true }
      );
    });
  }

  get closed() {
    return this.#closed;
  }

  /** Sends one command; resolves with its result or rejects with its error. */
  send(method, params = {}, { sessionId, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
    if (this.#closed) return Promise.reject(new Error(`cdp: ${method} after the socket closed`));
    const id = ++this.#nextId;
    const msg = { id, method, params };
    if (sessionId) msg.sessionId = sessionId;
    return new Promise((resolve, reject) => {
      // Timeout timers are unref'd: the open socket keeps the process alive
      // while it matters, and a forgotten wait must not delay exit.
      const timer = setTimeout(() => {
        this.#pending.delete(id);
        reject(new Error(`cdp: ${method} timed out after ${timeoutMs} ms`));
      }, timeoutMs).unref();
      this.#pending.set(id, { resolve, reject, method, timer });
      this.#ws.send(JSON.stringify(msg));
    });
  }

  /** Calls fn(params) for every `method` event; returns an unsubscribe function. */
  on(method, fn, { sessionId } = {}) {
    const key = `${sessionId ?? ''}|${method}`;
    let set = this.#listeners.get(key);
    if (!set) this.#listeners.set(key, (set = new Set()));
    set.add(fn);
    return () => set.delete(fn);
  }

  /** Resolves with the params of the next `method` event that passes `predicate`. */
  waitFor(method, { sessionId, predicate = () => true, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        off();
        reject(new Error(`cdp: no ${method} event within ${timeoutMs} ms`));
      }, timeoutMs).unref();
      const off = this.on(
        method,
        (params) => {
          if (!predicate(params)) return;
          clearTimeout(timer);
          off();
          resolve(params);
        },
        { sessionId }
      );
    });
  }

  /** A view of this connection bound to one flat session. */
  session(sessionId) {
    return {
      sessionId,
      browser: this,
      send: (method, params, opts = {}) => this.send(method, params, { ...opts, sessionId }),
      on: (method, fn) => this.on(method, fn, { sessionId }),
      waitFor: (method, opts = {}) => this.waitFor(method, { ...opts, sessionId })
    };
  }

  close() {
    if (!this.#closed) this.#ws.close();
    this.#onClose();
  }

  #onMessage(ev) {
    let msg;
    try {
      msg = JSON.parse(typeof ev.data === 'string' ? ev.data : Buffer.from(ev.data).toString());
    } catch {
      return;
    }
    if (msg.id !== undefined) {
      const p = this.#pending.get(msg.id);
      if (!p) return;
      this.#pending.delete(msg.id);
      clearTimeout(p.timer);
      if (msg.error)
        p.reject(new Error(`cdp: ${p.method}: ${msg.error.message} (${msg.error.code})`));
      else p.resolve(msg.result ?? {});
      return;
    }
    const set = this.#listeners.get(`${msg.sessionId ?? ''}|${msg.method}`);
    if (set) for (const fn of [...set]) fn(msg.params ?? {});
  }

  #onClose() {
    if (this.#closed) return;
    this.#closed = true;
    for (const [, p] of this.#pending) {
      clearTimeout(p.timer);
      p.reject(new Error(`cdp: socket closed before ${p.method} answered`));
    }
    this.#pending.clear();
  }
}

/** GET a DevTools HTTP endpoint (such as /json/version) as JSON. */
export async function getJSON(httpOrigin, path) {
  const res = await fetch(new URL(path, httpOrigin), { signal: AbortSignal.timeout(5_000) });
  if (!res.ok) throw new Error(`cdp: GET ${path} returned HTTP ${res.status}`);
  return res.json();
}

/**
 * Opens a fresh tab in its own browser context (so localStorage, cookies and
 * cache start empty and never touch other tabs), attached as a flat session.
 * page.close() closes the tab and disposes the context.
 */
export async function openPage(browser, { url = 'about:blank' } = {}) {
  const { browserContextId } = await browser.send('Target.createBrowserContext', {
    disposeOnDetach: true
  });
  const { targetId } = await browser.send('Target.createTarget', { url, browserContextId });
  const { sessionId } = await browser.send('Target.attachToTarget', { targetId, flatten: true });
  const page = browser.session(sessionId);
  page.targetId = targetId;
  page.browserContextId = browserContextId;
  page.close = async () => {
    if (browser.closed) return;
    await browser.send('Target.closeTarget', { targetId }).catch(() => {});
    await browser.send('Target.disposeBrowserContext', { browserContextId }).catch(() => {});
  };
  return page;
}

/**
 * Runs fn(...args) in the page and returns its (JSON-serialisable) value,
 * awaiting a returned promise. Throws with the page's message on an exception.
 */
export async function evaluate(page, fn, ...args) {
  const expression = `(${fn})(...${JSON.stringify(args)})`;
  const r = await page.send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true
  });
  if (r.exceptionDetails) {
    const d = r.exceptionDetails;
    throw new Error(`page threw: ${d.exception?.description ?? d.text}`);
  }
  return r.result?.value;
}

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
