/** Runs in the page: the probe report. Keep it self-contained. */
export function probePage() {
  const de = document.documentElement;
  // Mobile overflow can enlarge innerWidth through automatic zoom. Compare
  // against the intended layout viewport, while retaining iw/ih in the output.
  const viewportWidth = de.clientWidth;
  const viewportHeight = de.clientHeight;
  const modal = document.querySelector('dialog:modal');
  const active = (el) => !el.closest('[inert], dialog:not([open])') && (!modal || modal.contains(el));
  const visible = (el) =>
    el.checkVisibility
      ? el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })
      : true;
  const round = (n) => Math.round(n * 10) / 10;
  const describe = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += `#${el.id}`;
    const cls = [...el.classList].slice(0, 2);
    if (cls.length) s += `.${cls.join('.')}`;
    for (const a of ['data-act', 'data-card', 'data-testid', 'aria-label', 'name']) {
      const v = el.getAttribute(a);
      if (v) {
        s += `[${a}="${v.slice(0, 40)}"]`;
        break;
      }
    }
    const text = (el.innerText || el.value || '').trim().replace(/\s+/g, ' ').slice(0, 30);
    return text ? `${s} "${text}"` : s;
  };

  // The box actually painted by scroll/clipping ancestors, before viewport clipping.
  const paintedBox = (el) => {
    const r = el.getBoundingClientRect();
    let left = r.left, right = r.right, top = r.top, bottom = r.bottom;
    for (let p = el.parentElement; p && p !== document.documentElement; p = p.parentElement) {
      const b = p.getBoundingClientRect(), style = getComputedStyle(p);
      if (style.overflowX !== 'visible') { left = Math.max(left, b.left); right = Math.min(right, b.right); }
      if (style.overflowY !== 'visible') { top = Math.max(top, b.top); bottom = Math.min(bottom, b.bottom); }
      if (p.matches('dialog:modal')) break;
    }
    return right > left && bottom > top ? { left, right, top, bottom } : null;
  };

  const overflow = [];
  const viewportOutside = [];
  const reported = [];
  for (const el of document.body.querySelectorAll('*')) {
    if (!active(el) || !visible(el) || (el.closest('svg') && el.tagName.toLowerCase() !== 'svg')) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    const part = paintedBox(el);
    if (!part) continue;
    const { left, right, top, bottom } = part;
    const horizontal = right > viewportWidth + 0.5 || left < -0.5;
    const vertical = (top < -0.5 && bottom > 0) || (top < viewportHeight && bottom > viewportHeight + 0.5);
    if (!horizontal && !vertical) continue;
    if (reported.some(p => p.contains(el))) continue;
    reported.push(el);
    const item = { el: describe(el), left: round(left), right: round(right), width: round(right - left), top: round(top), bottom: round(bottom) };
    viewportOutside.push(item);
    if (horizontal) overflow.push(item);
  }

  const tapSelector = [
    'button',
    'a[href]',
    'input:not([type="hidden"])',
    'select',
    'textarea',
    'summary',
    '[role="button"]',
    '[role="link"]',
    '[role="tab"]',
    '[role="radio"]',
    '[role="checkbox"]',
    '[tabindex]:not([tabindex="-1"])',
    '[data-act]'
  ].join(',');
  let smallest = null;
  let count = 0;
  let under24 = 0;
  let under44 = 0;
  for (const el of document.querySelectorAll(tapSelector)) {
    if (el.matches(':disabled, [aria-disabled="true"]') || !active(el)) continue;
    // A visually hidden input is hit through its label.
    let target = el;
    const box = el.getBoundingClientRect();
    if (el.labels?.length && (el.matches('input[type=radio], input[type=checkbox]') ||
        (box.width <= 1 && box.height <= 1))) target = [...el.labels].find(visible) ?? el;
    if (!visible(target)) continue;
    const part = paintedBox(target);
    if (!part || part.bottom <= 0 || part.top >= viewportHeight || part.right <= 0 || part.left >= viewportWidth) continue;
    const r = target.getBoundingClientRect();
    if (r.bottom <= 0 || r.top >= viewportHeight || r.right <= 0 || r.left >= viewportWidth) continue;
    if (r.width <= 1 && r.height <= 1) continue; // screen-reader-only
    count++;
    const min = Math.min(r.width, r.height);
    if (min < 24) under24++;
    if (min < 44) under44++;
    if (!smallest || min < smallest.min) {
      smallest = { el: describe(target), w: round(r.width), h: round(r.height), min: round(min) };
    }
  }

  const covered = [];
  for (const el of document.querySelectorAll('button[data-act]:not(:disabled)')) {
    if (!active(el) || !visible(el) || el.getAttribute('aria-disabled') === 'true') continue;
    const r = el.getBoundingClientRect();
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    if (r.width <= 1 || r.height <= 1 || x < 0 || x >= viewportWidth || y < 0 || y >= viewportHeight) continue;
    // A scroll container may hide a control whose centre is in the viewport.
    let clippedCentre = false;
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const b = p.getBoundingClientRect(), style = getComputedStyle(p);
      if ((style.overflowX !== 'visible' && (x < b.left || x > b.right)) ||
          (style.overflowY !== 'visible' && (y < b.top || y > b.bottom))) clippedCentre = true;
      if (p.matches('dialog:modal')) break;
    }
    if (clippedCentre) continue;
    const at = document.elementFromPoint(x, y);
    if (!at || (at !== el && !el.contains(at))) covered.push({ el: describe(el), by: at ? describe(at) : null });
  }
  return {
    domNodes: document.querySelectorAll('*').length,
    covered,
    viewportOutside,
    url: location.href,
    title: document.title,
    iw: window.innerWidth,
    ih: window.innerHeight,
    viewportWidth,
    viewportHeight,
    sw: de.scrollWidth,
    sh: de.scrollHeight,
    hscroll: de.scrollWidth > viewportWidth,
    vscroll: de.scrollHeight > viewportHeight,
    theme: de.dataset.theme ?? null,
    ready: de.hasAttribute('data-ready'),
    // Do not dump localStorage: identity tokens and player data are private.
    body: (document.body?.innerText ?? '').slice(0, 400),
    overflow,
    tap: { count, smallest, under24, under44 }
  };
}

