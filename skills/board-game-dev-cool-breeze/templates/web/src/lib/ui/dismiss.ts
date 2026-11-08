// "Any tap closes it, and the tap is swallowed": the dismiss behaviour that
// the tooltip layer and the floating panels share (components/shell/
// TooltipLayer.svelte and DismissLayer.svelte). A tap that closes an
// overlay must not also act on whatever lies beneath it, so the press is
// stopped before any component sees it and the click that follows it is
// cancelled.
//
// DOM-only. Install it from an effect and return its cleanup.

let armedBy: Event | null = null;
let armed = false;
let expiry: ReturnType<typeof setTimeout> | undefined;
let listening = false;

/** How long after the finger lifts a swallowed press's click may still
 *  arrive. Browsers send it within a frame or two; a press that became a
 *  scroll sends none, and the next press disarms anyway. */
const CLICK_GRACE_MS = 700;

function disarm(): void {
  armed = false;
  armedBy = null;
  if (expiry !== undefined) clearTimeout(expiry);
  expiry = undefined;
}

function onClick(e: MouseEvent): void {
  if (!armed) return;
  // A click from the keyboard (Enter or Space on a button) has no pointer
  // type; it was never part of the swallowed press.
  if ('pointerType' in e && (e as PointerEvent).pointerType === '') return;
  e.preventDefault();
  e.stopImmediatePropagation();
  disarm();
}

function onDown(e: Event): void {
  // A new press disarms an old swallow, unless this very press armed it.
  if (armed && e !== armedBy) disarm();
}

function onUp(): void {
  if (!armed) return;
  if (expiry !== undefined) clearTimeout(expiry);
  expiry = setTimeout(disarm, CLICK_GRACE_MS);
}

function listen(): void {
  if (listening || typeof window === 'undefined') return;
  listening = true;
  window.addEventListener('click', onClick, true);
  window.addEventListener('pointerdown', onDown, true);
  window.addEventListener('pointerup', onUp, true);
  window.addEventListener('pointercancel', onUp, true);
}

/** Cancels the click that ends the current press (`by` is the press's
 *  pointerdown, when the swallow starts there). */
export function swallowClick(by?: Event): void {
  listen();
  armed = true;
  armedBy = by ?? null;
  if (expiry !== undefined) clearTimeout(expiry);
  expiry = undefined;
}

let quietFocus: Element | null = null;

/**
 * Gives the focus back to `el` without opening its keyboard focus tooltip
 * (the tooltip layer asks isQuietFocus). The focus that returns to an
 * opener is not the user moving it, and a tooltip popping up there would
 * also take the next tap on a touch screen.
 */
export function restoreFocus(el: HTMLElement): void {
  quietFocus = el;
  try {
    el.focus({ preventScroll: true });
  } finally {
    quietFocus = null;
  }
}

/** Whether `el` is taking the focus through restoreFocus right now. */
export function isQuietFocus(el: Element): boolean {
  return quietFocus !== null && el === quietFocus;
}

