// One tooltip store and Svelte 5 attachment. Mount TooltipLayer once.
import { untrack, type Snippet } from 'svelte';
import type { Attachment } from 'svelte/attachments';
import { isQuietFocus, swallowClick } from './dismiss';
import type { RuleSectionId } from '../rules/sections';
import {
  downAction,
  HOVER_DELAY_MS,
  HOVER_HIDE_LINK_MS,
  HOVER_HIDE_MS,
  HOVER_RESUME_PX,
  HOVER_SKIP_MS,
  isActionable,
  LONG_PRESS_MS,
  Press,
  resolveAnchor
} from './tooltip-gesture';

/** Caller-rendered real components. No nested stack API is exposed. */
export interface TooltipStackItem {
  caption: string;
  render: Snippet;
}

export interface TooltipContent {
  /** The tooltip's text, already translated. Short: one or two lines. */
  text: string;
  /** Status lines under the text, already translated: facts the server
   *  sent about the anchor now (where a card is, what a guild is worth). */
  lines?: readonly string[];
  /** A small concept diagram under the text. Its labels must be
   *  translatable text, not baked into the SVG. */
  diagram?: Snippet;
  /** A second joined panel; the layer shows at most two previews. */
  stack?: readonly TooltipStackItem[];
  /** The rules reference section this tooltip's topic belongs to: the
   *  bubble shows a "More in Rules" link that opens it. */
  rulesId?: RuleSectionId;
  /** Whether a tap on the anchor acts, when the DOM cannot tell (the
   *  default looks for a button, a link, a data-act and the like on the
   *  anchor or an ancestor). */
  actionable?: boolean;
  /** Keep the whole card clear, allowing a bubble beside it when needed. */
  avoidAnchor?: boolean;
}

export type TooltipVia = 'hover' | 'focus' | 'touch' | 'api';

export interface ActiveTooltip {
  /** Unique per showing, so the layer can restart its fade. */
  id: number;
  anchor: Element;
  content: TooltipContent;
  /** The anchor's box when it was shown. */
  rect: DOMRect;
  via: TooltipVia;
  /** Keyboard focus can belong to the button that encloses this card. */
  focusOwner?: Element;
}

/** The bubble's element id, for aria-describedby. */
export const TOOLTIP_ID = 'game-tooltip';
/** The attribute every registered anchor carries. */
export const ANCHOR_ATTR = 'data-tooltip';
/** The open bubble, and its "More in Rules" link. */
const BUBBLE_SELECTOR = '[data-tooltip-layer] [data-tooltip-bubble]';
const LINK_SELECTOR = '[data-tooltip-layer] [data-tooltip-rules]';

function inside(target: EventTarget | null, selector: string): boolean {
  return target instanceof Element && target.closest(selector) !== null;
}

const FOCUSABLE =
  'a[href], button, input, select, textarea, summary, [tabindex]:not([tabindex="-1"])';

class TooltipStore {
  /** The tooltip on screen, if any. Replaced whole. */
  active: ActiveTooltip | null = $state.raw(null);

  #registry = new WeakMap<Element, TooltipContent>();
  #seq = 0;
  #closedAt = -Infinity;

  /** Registers an anchor, or updates its content (a re-run attachment). */
  register(el: Element, content: TooltipContent): void {
    this.#registry.set(el, content);
    el.setAttribute(ANCHOR_ATTR, '');
    // An open tooltip whose anchor re-registered shows the new content. The
    // write waits for a microtask, outside the attachment's effect (state is
    // never written from inside an effect).
    // untrack: the attachment that calls this must not re-run whenever a
    // tooltip opens or closes.
    if (untrack(() => this.active?.anchor === el)) {
      queueMicrotask(() => {
        const active = this.active;
        if (active?.anchor === el && this.#registry.get(el) === content) {
          this.active = { ...active, content };
        }
      });
    }
  }

  unregister(el: Element, content: TooltipContent): void {
    // A re-run attachment registers its new content right after this
    // cleanup; only a stale entry is removed.
    if (this.#registry.get(el) !== content) return;
    this.#registry.delete(el);
    el.removeAttribute(ANCHOR_ATTR);
    // The anchor left the page (or lost its tooltip): close after the
    // current update settles, unless it registered again meanwhile.
    queueMicrotask(() => {
      if (this.active?.anchor === el && (!el.isConnected || !this.#registry.has(el))) this.hide();
    });
  }

  contentOf(el: Element): TooltipContent | undefined {
    return this.#registry.get(el);
  }

  /** The innermost registered anchor at or above `target`. Nothing inside
   *  the tooltip layer counts: a diagram in a bubble is drawn with the
   *  board's own components, which may carry tooltips of their own. */
  anchorFor(target: EventTarget | null): Element | null {
    const start = target instanceof Element ? target : null;
    if (start?.closest('[data-tooltip-layer]')) return null;
    return resolveAnchor<Element>(
      start,
      (node) => node.parentElement,
      (node) => this.#registry.has(node)
    );
  }

  show(anchor: Element, via: TooltipVia, focusOwner?: Element): void {
    const content = this.#registry.get(anchor);
    if (!content) return;
    if (this.active && this.active.anchor !== anchor)
      this.#undescribe(this.active.focusOwner ?? this.active.anchor);
    this.active = {
      id: ++this.#seq,
      anchor,
      content,
      rect: anchor.getBoundingClientRect(),
      via,
      focusOwner
    };
    const described = focusOwner ?? anchor;
    // A focusable anchor points at the bubble while it shows. Micro-elements
    // inside a focusable card are not focusable themselves; the card's own
    // accessible description covers them.
    if (described.matches(FOCUSABLE)) {
      const ids = (described.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean);
      if (!ids.includes(TOOLTIP_ID)) {
        described.setAttribute('aria-describedby', [...ids, TOOLTIP_ID].join(' '));
      }
    }
  }

  hide(): void {
    if (!this.active) return;
    this.#undescribe(this.active.focusOwner ?? this.active.anchor);
    this.active = null;
    this.#closedAt = performance.now();
  }

  /** Whether a tooltip closed so recently that the next one should skip
   *  the hover delay. */
  get warm(): boolean {
    return this.active !== null || performance.now() - this.#closedAt < HOVER_SKIP_MS;
  }

  #undescribe(anchor: Element): void {
    const ids = (anchor.getAttribute('aria-describedby') ?? '')
      .split(/\s+/)
      .filter((id) => id && id !== TOOLTIP_ID);
    if (ids.length > 0) anchor.setAttribute('aria-describedby', ids.join(' '));
    else anchor.removeAttribute('aria-describedby');
  }
}

/** The app's one tooltip store. */
export const tooltips = new TooltipStore();

/**
 * The attachment that gives an element a tooltip. Pass undefined to give it
 * none (a conditional tooltip). When the content changes, Svelte re-runs
 * the attachment and an open tooltip updates in place.
 */
export function tooltip(content: TooltipContent | undefined): Attachment {
  return (el) => {
    if (!content) return;
    untrack(() => tooltips.register(el, content));
    return () => tooltips.unregister(el, content);
  };
}

/**
 * Wires the gestures to the store: pointer, touch, focus, Escape and
 * resize. The layer installs it once, from an effect; returns the
 * cleanup.
 */
export function installTooltipGestures(store: TooltipStore = tooltips): () => void {
  let hoverTimer: ReturnType<typeof setTimeout> | undefined;
  let hideTimer: ReturnType<typeof setTimeout> | undefined;
  let pressTimer: ReturnType<typeof setTimeout> | undefined;
  let hovered: Element | null = null;
  let linkCandidate: Element | null = null;
  let press: { state: Press; anchor: Element; pointerId: number } | null = null;
  // Where the mouse last pressed: hovering shows nothing new until it has
  // moved away from there (HOVER_RESUME_PX).
  let clickedAt: { x: number; y: number } | null = null;
  // Native dialogs restore focus during Escape's default action, before
  // their close event. That return is as quiet as restoreFocus().
  let closingDialog: HTMLDialogElement | null = null;
  let dialogTimer: ReturnType<typeof setTimeout> | undefined;
  const onDialogCancel = (e: Event): void => {
    if (!(e.target instanceof HTMLDialogElement)) return;
    closingDialog = e.target;
    clearTimeout(dialogTimer);
    dialogTimer = setTimeout(() => {
      closingDialog = null;
    }, 0);
  };

  const clearHover = (): void => {
    clearTimeout(hoverTimer);
    clearTimeout(hideTimer);
    hoverTimer = hideTimer = undefined;
    linkCandidate = null;
  };
  const endPress = (): void => {
    clearTimeout(pressTimer);
    pressTimer = undefined;
    press = null;
  };

  /** Shows the hovered anchor's tooltip, now or after the delay. */
  const hoverShow = (anchor: Element): void => {
    // A keyboard focus tooltip stays until focus moves.
    if (store.active?.via === 'focus') return;
    if (store.warm) store.show(anchor, 'hover');
    else hoverTimer = setTimeout(() => store.show(anchor, 'hover'), HOVER_DELAY_MS);
  };

  const onOver = (e: PointerEvent): void => {
    if (e.pointerType !== 'mouse') return;
    // Only the link keeps its bubble open. The rest of the bubble lets
    // the pointer reach neighboring anchors.
    if (store.active && inside(e.target, LINK_SELECTOR)) {
      hovered = null;
      clearHover();
      return;
    }
    const anchor = store.anchorFor(e.target);
    // The link is not an anchor. Leaving it must still arm the hide
    // timer when both the old and new hovered anchors are null.
    if (anchor === hovered && !inside(e.relatedTarget, LINK_SELECTOR)) return;
    hovered = anchor;
    clearHover();
    if (!anchor) {
      if (store.active?.via === 'hover') {
        const delay = store.active.content.rulesId ? HOVER_HIDE_LINK_MS : HOVER_HIDE_MS;
        hideTimer = setTimeout(() => store.hide(), delay);
      }
      return;
    }
    if (clickedAt) return;
    if (
      store.active?.via === 'hover' &&
      store.active.content.rulesId &&
      anchor !== store.active.anchor
    ) {
      // Linked tooltips need a short hover intent delay even across the
      // gap to the link. Movement refreshes it; after the pointer rests,
      // a neighbor takes over within the same bounded delay. Clicks pass
      // straight through and cancel it in onDown.
      linkCandidate = anchor;
      hoverTimer = setTimeout(() => {
        linkCandidate = null;
        hoverShow(anchor);
      }, HOVER_HIDE_LINK_MS);
      return;
    }
    hoverShow(anchor);
  };

  const onOut = (e: PointerEvent): void => {
    if (e.pointerType !== 'mouse' || e.relatedTarget !== null) return;
    // The pointer left the window.
    hovered = null;
    clickedAt = null;
    clearHover();
    if (store.active?.via === 'hover') store.hide();
  };

  const onDown = (e: PointerEvent): void => {
    const mouse = e.pointerType === 'mouse';
    const action = downAction({
      mouse,
      open: store.active !== null,
      inBubble: inside(e.target, BUBBLE_SELECTOR),
      onLink: inside(e.target, LINK_SELECTOR)
    });
    if (mouse) clickedAt = { x: e.clientX, y: e.clientY };
    // A press inside the bubble (its link) leaves it open; the link's click
    // closes it.
    if (action === 'keep' && store.active) return;
    clearHover();
    endPress();
    if (mouse) {
      // A click acts as usual, and closes any open tooltip, a keyboard focus
      // one too: a focus tooltip left open over a menu or sheet that the
      // click opened would take the Escape meant to close it.
      if (action === 'hide') store.hide();
      return;
    }
    // Touch or pen. Any tap while a tooltip is open closes it, and is
    // swallowed: neither the press nor its click reaches the page.
    if (action === 'swallow') {
      e.stopPropagation();
      swallowClick(e);
      store.hide();
      return;
    }
    const anchor = store.anchorFor(e.target);
    if (!anchor) return;
    const content = store.contentOf(anchor);
    const state = new Press(
      e.clientX,
      e.clientY,
      e.timeStamp,
      isActionable(anchor, content?.actionable)
    );
    press = { state, anchor, pointerId: e.pointerId };
    pressTimer = setTimeout(() => {
      if (press?.state !== state) return;
      if (state.due(Math.max(performance.now(), state.downAt + LONG_PRESS_MS))) {
        store.show(anchor, 'touch');
        swallowClick();
      }
    }, LONG_PRESS_MS);
  };

  const onMove = (e: PointerEvent): void => {
    if (e.pointerType === 'mouse') {
      if (linkCandidate) {
        const candidate = linkCandidate;
        clearTimeout(hoverTimer);
        hoverTimer = setTimeout(() => {
          linkCandidate = null;
          if (hovered === candidate) hoverShow(candidate);
        }, HOVER_HIDE_LINK_MS);
      } else if (
        hideTimer !== undefined &&
        store.active?.via === 'hover' &&
        store.active.content.rulesId
      ) {
        clearTimeout(hideTimer);
        hideTimer = setTimeout(() => store.hide(), HOVER_HIDE_LINK_MS);
      }
      // The mouse moved on from its click: hovering shows tooltips again.
      if (!clickedAt) return;
      if (Math.hypot(e.clientX - clickedAt.x, e.clientY - clickedAt.y) < HOVER_RESUME_PX) return;
      clickedAt = null;
      if (hovered && hovered !== store.active?.anchor) hoverShow(hovered);
      return;
    }
    if (!press || e.pointerId !== press.pointerId) return;
    press.state.move(e.clientX, e.clientY);
    if (press.state.cancelled) endPress();
  };

  const onUp = (e: PointerEvent): void => {
    if (!press || e.pointerId !== press.pointerId) return;
    const { state, anchor } = press;
    endPress();
    const outcome = state.up(e.clientX, e.clientY, e.timeStamp);
    if (outcome === 'show') {
      store.show(anchor, 'touch');
      swallowClick();
    } else if (outcome === 'swallow') {
      if (!store.active) store.show(anchor, 'touch');
      swallowClick();
    }
  };

  const onCancel = (e: PointerEvent): void => {
    if (!press || e.pointerId !== press.pointerId) return;
    press.state.cancel();
    endPress();
  };

  // The long-press must not open the browser's own menu or callout.
  const onContextMenu = (e: Event): void => {
    if (press || store.active?.via === 'touch') e.preventDefault();
  };

  const onKey = (e: KeyboardEvent): void => {
    // A new keyboard gesture is deliberate focus, even if it arrives
    // before the native dialog's zero-delay cleanup timer.
    if (e.key !== 'Escape') {
      closingDialog = null;
      clearTimeout(dialogTimer);
    }
    if (e.key !== 'Escape' || !store.active) return;
    // Close the tooltip only, not the sheet beneath it.
    e.preventDefault();
    e.stopPropagation();
    clearHover();
    store.hide();
  };

  const onFocusIn = (e: FocusEvent): void => {
    const el = e.target;
    if (!(el instanceof Element)) return;
    // The focus given back to an opener (ui/dismiss.ts) opens no tooltip.
    if (isQuietFocus(el) || (closingDialog && !closingDialog.contains(el))) {
      if (store.active?.via === 'focus') store.hide();
      return;
    }
    const card = el.matches('button, [role="button"]')
      ? el.querySelector('[data-tooltip]')
      : null;
    const anchor = card && store.contentOf(card) ? card : el;
    if (store.contentOf(anchor) && el.matches(':focus-visible')) {
      clearHover();
      store.show(anchor, 'focus', el);
    } else if (store.active?.via === 'focus') store.hide();
  };

  const onFocusOut = (e: FocusEvent): void => {
    if (
      store.active?.via === 'focus' &&
      (store.active.focusOwner ?? store.active.anchor) === e.target
    )
      store.hide();
  };

  // A resize (a rotation, the keyboard opening) closes it; a scroll moves
  // it with its anchor (the layer follows the anchor).
  const onMoveAway = (): void => {
    if (store.active) store.hide();
  };

  const opts = { capture: true } as const;
  const passive = { capture: true, passive: true } as const;
  window.addEventListener('pointerover', onOver, passive);
  window.addEventListener('pointerout', onOut, passive);
  window.addEventListener('pointerdown', onDown, opts);
  window.addEventListener('pointermove', onMove, passive);
  window.addEventListener('pointerup', onUp, opts);
  window.addEventListener('pointercancel', onCancel, opts);
  window.addEventListener('contextmenu', onContextMenu, opts);
  window.addEventListener('keydown', onKey, opts);
  window.addEventListener('cancel', onDialogCancel, opts);
  window.addEventListener('focusin', onFocusIn, opts);
  window.addEventListener('focusout', onFocusOut, opts);
  window.addEventListener('resize', onMoveAway, passive);
  return () => {
    clearHover();
    endPress();
    clearTimeout(dialogTimer);
    window.removeEventListener('cancel', onDialogCancel, opts);
    window.removeEventListener('pointerover', onOver, passive);
    window.removeEventListener('pointerout', onOut, passive);
    window.removeEventListener('pointerdown', onDown, opts);
    window.removeEventListener('pointermove', onMove, passive);
    window.removeEventListener('pointerup', onUp, opts);
    window.removeEventListener('pointercancel', onCancel, opts);
    window.removeEventListener('contextmenu', onContextMenu, opts);
    window.removeEventListener('keydown', onKey, opts);
    window.removeEventListener('focusin', onFocusIn, opts);
    window.removeEventListener('focusout', onFocusOut, opts);
    window.removeEventListener('resize', onMoveAway, passive);
  };
}
