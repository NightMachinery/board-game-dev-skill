// Where a tooltip goes: pure placement math for the tooltip layer
// (components/shell/TooltipLayer.svelte), unit-tested in
// tooltip-place.test.ts. Everything is in viewport pixels, measured from the
// top-left corner. The layer draws its boxes in a dir="ltr" overlay, so
// these physical coordinates are right in a right-to-left page too; only the
// text inside the boxes follows the page's direction.
//
// A tooltip is a bubble with an arrow to its anchor, and optionally a stack:
// a second panel of linked previews (the card a chain symbol makes free, for
// example). The stack sits beside the bubble when there is room for both
// side by side ('beside', wide screens), otherwise on the bubble's far side
// from the anchor ('below' on a phone, so the bubble and its arrow always
// stay next to the anchor). A short connector joins the two.

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Size {
  width: number;
  height: number;
}

export type Side = 'top' | 'bottom' | 'start' | 'end';
export type StackMode = 'beside' | 'below';

export interface PlaceInput {
  /** The anchor's bounding box. */
  anchor: Rect;
  /** The bubble's measured size. */
  bubble: Size;
  /** The stack panel's measured size, when the tooltip has one. */
  stack?: Size;
  /** The area the tooltip must stay inside: the viewport less the safe-area
   *  insets (notches, home indicator). */
  bounds: Rect;
  /** Keep this far from the bounds' edges. */
  margin?: number;
  /** Space between the anchor and the bubble, which the arrow spans. */
  gap?: number;
  /** Space between the bubble and the stack, which the connector spans. */
  stackGap?: number;
  /** Put the stack beside the bubble when both fit side by side. The layer
   *  passes true on wide screens only; a phone always stacks vertically. */
  allowBeside?: boolean;
  /** For a whole-card summary, use either side of the card before overlapping it. */
  avoidAnchor?: boolean;
  /** The bubble's arrow keeps this far from the bubble's corners. */
  arrowInset?: number;
}

export interface Placement {
  /** Which side of the anchor the bubble is on. */
  side: Side;
  bubble: { x: number; y: number };
  /** The arrow's centre along the bubble's edge, from the bubble's left. */
  arrowX: number;
  stack?: { x: number; y: number; mode: StackMode };
  /** The connector between bubble and stack: a segment in viewport space. */
  connector?: { x1: number; y1: number; x2: number; y2: number };
}

export const PLACE_DEFAULTS = {
  margin: 8,
  gap: 10,
  stackGap: 12,
  arrowInset: 12
} as const;

function clamp(value: number, lo: number, hi: number): number {
  // When the box is wider than the room, pin it to the low edge, so its
  // start (where the text starts) stays visible.
  if (hi < lo) return lo;
  return Math.min(Math.max(value, lo), hi);
}

/** Places a tooltip next to its anchor, inside the bounds. Prefers above
 *  the anchor, flips below when the tooltip does not fit above, and shifts
 *  sideways so it never leaves the bounds. */
export function placeTooltip(input: PlaceInput): Placement {
  const margin = input.margin ?? PLACE_DEFAULTS.margin;
  const gap = input.gap ?? PLACE_DEFAULTS.gap;
  const stackGap = input.stackGap ?? PLACE_DEFAULTS.stackGap;
  const arrowInset = input.arrowInset ?? PLACE_DEFAULTS.arrowInset;
  const { anchor, bubble, stack, bounds } = input;

  const minX = bounds.x + margin;
  const maxX = bounds.x + bounds.width - margin;
  const minY = bounds.y + margin;
  const maxY = bounds.y + bounds.height - margin;
  const room = maxX - minX;
  const anchorCx = anchor.x + anchor.width / 2;

  const roomAbove = anchor.y - gap - minY;
  const roomBelow = maxY - (anchor.y + anchor.height + gap);
  if (input.avoidAnchor && !stack && bubble.height > Math.max(roomAbove, roomBelow)) {
    const before = anchor.x - gap - minX;
    const after = maxX - anchor.x - anchor.width - gap;
    if (bubble.height <= maxY - minY && bubble.width <= Math.max(before, after)) {
      const end = after >= before;
      return {
        side: end ? 'end' : 'start',
        bubble: {
          x: end ? anchor.x + anchor.width + gap : anchor.x - gap - bubble.width,
          y: clamp(anchor.y + (anchor.height - bubble.height) / 2, minY, maxY - bubble.height)
        },
        arrowX: 0
      };
    }
  }

  // Beside only when the bubble and the stack fit side by side: on a wide
  // screen, or wherever stacking them vertically would not fit on either
  // side of the anchor (a phone in landscape, which is short), since two
  // boxes that are each pushed inside a short screen would overlap.
  const fitsBeside = !!stack && bubble.width + stackGap + stack.width <= room;
  const fitsBelow =
    !!stack && bubble.height + stackGap + stack.height <= Math.max(roomAbove, roomBelow);
  const mode: StackMode | undefined = stack
    ? fitsBeside && (input.allowBeside || !fitsBelow)
      ? 'beside'
      : 'below'
    : undefined;

  // The height the whole group needs on the anchor's side.
  const groupHeight =
    stack && mode === 'below'
      ? bubble.height + stackGap + stack.height
      : Math.max(bubble.height, stack?.height ?? 0);
  const side: Side =
    roomAbove >= groupHeight
      ? 'top'
      : roomBelow >= groupHeight
        ? 'bottom'
        : roomAbove >= roomBelow
          ? 'top'
          : 'bottom';

  // The bubble's vertical position: next to the anchor, kept inside.
  const bubbleY = clamp(
    side === 'top' ? anchor.y - gap - bubble.height : anchor.y + anchor.height + gap,
    minY,
    maxY - bubble.height
  );

  if (!stack || !mode) {
    const x = clamp(anchorCx - bubble.width / 2, minX, maxX - bubble.width);
    return {
      side,
      bubble: { x, y: bubbleY },
      arrowX: arrowAt(anchorCx - x, bubble.width, arrowInset)
    };
  }

  if (mode === 'below') {
    const x = clamp(anchorCx - bubble.width / 2, minX, maxX - bubble.width);
    const bubbleCx = x + bubble.width / 2;
    const sx = clamp(bubbleCx - stack.width / 2, minX, maxX - stack.width);
    // The two boxes move as one: when the group does not fit on the
    // anchor's side, the bubble gives way to the stack rather than the
    // stack sliding over the bubble. Only a group taller than the whole
    // screen still overlaps (each box is then kept inside on its own).
    const by = clamp(
      clamp(
        bubbleY,
        side === 'top' ? minY + stack.height + stackGap : minY,
        side === 'top' ? maxY - bubble.height : maxY - groupHeight
      ),
      minY,
      maxY - bubble.height
    );
    const sy = clamp(
      side === 'top' ? by - stackGap - stack.height : by + bubble.height + stackGap,
      minY,
      maxY - stack.height
    );
    // The connector runs straight up or down where the two boxes overlap.
    const lo = Math.max(x, sx) + 6;
    const hi = Math.min(x + bubble.width, sx + stack.width) - 6;
    const cx = clamp(bubbleCx, lo, hi);
    const [y1, y2] = side === 'top' ? [by, sy + stack.height] : [by + bubble.height, sy];
    return {
      side,
      bubble: { x, y: by },
      arrowX: arrowAt(anchorCx - x, bubble.width, arrowInset),
      stack: { x: sx, y: sy, mode },
      connector: { x1: cx, y1, x2: cx, y2 }
    };
  }

  // Beside: the bubble centred on the anchor where possible, the stack on
  // whichever side of it has room (the right first). When neither side has
  // room, the bubble moves away from the edge just enough for the stack.
  const groupWidth = bubble.width + stackGap + stack.width;
  let x = clamp(anchorCx - bubble.width / 2, minX, maxX - bubble.width);
  let stackRight = x + bubble.width + stackGap + stack.width <= maxX;
  if (!stackRight && x - stackGap - stack.width < minX) {
    // Neither side fits as is: lean the group away from the nearer edge.
    stackRight = anchorCx < (minX + maxX) / 2;
    x = stackRight
      ? clamp(x, minX, maxX - groupWidth)
      : clamp(x, minX + stack.width + stackGap, maxX - bubble.width);
  }
  const sx = stackRight ? x + bubble.width + stackGap : x - stackGap - stack.width;
  // Align the edges nearest the anchor, so both boxes hug it.
  const sy = clamp(
    side === 'top' ? bubbleY + bubble.height - stack.height : bubbleY,
    minY,
    maxY - stack.height
  );
  const top = Math.max(bubbleY, sy) + 6;
  const bottom = Math.min(bubbleY + bubble.height, sy + stack.height) - 6;
  const cy = clamp(bubbleY + bubble.height / 2, top, bottom);
  const [x1, x2] = stackRight ? [x + bubble.width, sx] : [x, sx + stack.width];
  return {
    side,
    bubble: { x, y: bubbleY },
    arrowX: arrowAt(anchorCx - x, bubble.width, arrowInset),
    stack: { x: sx, y: sy, mode },
    connector: { x1, y1: cy, x2, y2: cy }
  };
}

function arrowAt(offset: number, width: number, inset: number): number {
  return clamp(offset, Math.min(inset, width / 2), Math.max(width - inset, width / 2));
}
