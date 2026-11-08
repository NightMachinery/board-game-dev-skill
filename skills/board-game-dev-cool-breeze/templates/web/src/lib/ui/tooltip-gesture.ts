// The pure parts of the tooltip gestures, unit-tested in
// tooltip-gesture.test.ts: which registered anchor an event belongs to (the
// innermost), whether a touch on it would act (a button, a link, a card
// slot), and the long-press timing. The DOM wiring is in tooltip.svelte.ts.
//
// The touch model (AGENTS.md, "Tooltips"): a tap shows the tooltip of an
// element with no action. An actionable element keeps its tap action and
// shows its tooltip on a long-press, whose release never triggers the
// action. Any tap while a tooltip is open closes it and is swallowed, except
// a tap on the bubble's "More in Rules" link, which acts (downAction).

/** How long a finger must rest for a long-press. Long enough that an
 *  ordinary tap (about 100 to 250 ms) never reaches it, short enough not to
 *  feel stuck. */
export const LONG_PRESS_MS = 500;
/** How far a finger may drift and still be a tap or a long-press. A larger
 *  move is a scroll or a drag, and cancels the press, so a long-press never
 *  fights scrolling. */
export const TOUCH_SLOP_PX = 10;
/** A fine pointer resting on an anchor shows its tooltip after this. */
export const HOVER_DELAY_MS = 450;
/** Moving from one anchor to another within this time after a tooltip
 *  closed shows the next one at once, with no second delay. */
export const HOVER_SKIP_MS = 300;
/** A fine pointer leaving the anchor hides the tooltip after this, so
 *  passing over a gap between two chips does not flicker. */
export const HOVER_HIDE_MS = 100;
/** The same, for a bubble with a "More in Rules" link: long enough for the
 *  pointer to cross the gap between the anchor and the bubble. */
export const HOVER_HIDE_LINK_MS = 300;
/** A mouse that pressed (a click) must move this far before hovering shows
 *  tooltips again, so a click never pops one up under a resting pointer
 *  (over the sheet the click opened, say). */
export const HOVER_RESUME_PX = 4;

/** Walks from `start` up through `parentOf` and returns the first node for
 *  which `isAnchor` holds: the innermost registered anchor wins, so a chip
 *  inside a card shows the chip's tooltip, not the card's. */
export function resolveAnchor<N>(
  start: N | null,
  parentOf: (node: N) => N | null,
  isAnchor: (node: N) => boolean
): N | null {
  for (let node = start; node !== null; node = parentOf(node)) {
    if (isAnchor(node)) return node;
  }
  return null;
}

/** Elements whose tap does something: the anchor or any ancestor matching
 *  this keeps its tap, and shows its tooltip on a long-press instead. A
 *  disabled control does nothing on a tap, so it counts as passive. */
export const ACTIONABLE_SELECTOR = [
  'button',
  'a[href]',
  'input',
  'select',
  'textarea',
  'summary',
  'label',
  '[role="button"]',
  '[role="link"]',
  '[role="tab"]',
  '[role="menuitem"]',
  '[role="option"]',
  '[role="switch"]',
  '[role="checkbox"]',
  '[role="radio"]',
  '[data-act]',
  '[data-tooltip-actionable]'
].join(',');

/** Whether a touch on `el` would act. `override` comes from the tooltip's
 *  own content, for an element whose action this selector cannot see. */
export function isActionable(el: Element, override?: boolean): boolean {
  if (override !== undefined) return override;
  const target = el.closest(ACTIONABLE_SELECTOR);
  if (!target) return false;
  if (target.matches(':disabled') || target.getAttribute('aria-disabled') === 'true') return false;
  return true;
}

/** What a finished or interrupted press means. */
export type PressOutcome =
  /** A short tap on a passive element: show its tooltip. */
  | 'show'
  /** A short tap on an actionable element: let its action run. */
  | 'pass'
  /** The finger moved or the browser took the touch: nothing. */
  | 'cancel'
  /** A long-press already showed the tooltip: swallow the release. */
  | 'swallow';

/**
 * One touch press, from finger down to finger up, with the time passed in
 * so it can be tested without timers. The DOM controller calls `move` on
 * every pointermove, `due` from a timer at `downAt + LONG_PRESS_MS`, and
 * `up` or `cancel` at the end.
 */
export class Press {
  readonly x: number;
  readonly y: number;
  readonly downAt: number;
  readonly actionable: boolean;
  /** The press moved past the slop or was cancelled. */
  cancelled = false;
  /** The long-press fired and the tooltip is showing. */
  fired = false;

  constructor(x: number, y: number, downAt: number, actionable: boolean) {
    this.x = x;
    this.y = y;
    this.downAt = downAt;
    this.actionable = actionable;
  }

  /** The finger moved; a move past the slop cancels the press for good. */
  move(x: number, y: number): void {
    if (this.fired || this.cancelled) return;
    if (Math.hypot(x - this.x, y - this.y) > TOUCH_SLOP_PX) this.cancelled = true;
  }

  /** The long-press timer ran out: true when the tooltip should show now. */
  due(now: number): boolean {
    if (this.fired || this.cancelled) return false;
    if (now - this.downAt < LONG_PRESS_MS) return false;
    this.fired = true;
    return true;
  }

  /** The finger lifted. */
  up(x: number, y: number, now: number): PressOutcome {
    this.move(x, y);
    if (this.fired) return 'swallow';
    if (this.cancelled) return 'cancel';
    // A timer that has not run yet (a busy main thread) must not turn a
    // long press into a tap that acts.
    if (this.due(now)) return 'swallow';
    return this.actionable ? 'pass' : 'show';
  }

  /** The browser took the touch over (a scroll), or the page lost it. */
  cancel(): PressOutcome {
    if (this.fired) return 'swallow';
    this.cancelled = true;
    return 'cancel';
  }
}

/** What a pointerdown does to the tooltips. */
export type DownAction =
  /** Nothing is open (a mouse), or the press is inside the open bubble (a
   *  mouse moving to click its link): leave everything as it is. */
  | 'keep'
  /** A mouse press elsewhere: close the open tooltip, and let the click act. */
  | 'hide'
  /** A touch while one is open: close it, and swallow the tap. */
  | 'swallow'
  /** A touch with none open: start a press (a tap or a long-press). */
  | 'press';

/**
 * The pointerdown rule. `inBubble` is a press inside the open bubble, and
 * `onLink` one on its "More in Rules" link: the one tap that is not
 * swallowed, so the link works under the touch model too.
 */
export function downAction(p: {
  mouse: boolean;
  open: boolean;
  inBubble: boolean;
  onLink: boolean;
}): DownAction {
  if (p.mouse) return p.open && !p.inBubble ? 'hide' : 'keep';
  if (!p.open) return 'press';
  return p.onLink ? 'keep' : 'swallow';
}
