import { describe, expect, it } from 'vitest';
import { placeTooltip, type PlaceInput, type Placement, type Rect } from './tooltip-place';

const PHONE: Rect = { x: 0, y: 0, width: 360, height: 740 };
const DESKTOP: Rect = { x: 0, y: 0, width: 1280, height: 800 };
const MARGIN = 8;

function inside(p: Placement, input: PlaceInput): void {
  const { bounds, bubble, stack } = input;
  const boxes = [{ ...p.bubble, ...bubble }];
  if (stack && p.stack) boxes.push({ ...p.stack, ...stack });
  for (const b of boxes) {
    expect(b.x).toBeGreaterThanOrEqual(bounds.x + MARGIN);
    expect(b.y).toBeGreaterThanOrEqual(bounds.y + MARGIN);
    expect(b.x + b.width).toBeLessThanOrEqual(bounds.x + bounds.width - MARGIN);
    expect(b.y + b.height).toBeLessThanOrEqual(bounds.y + bounds.height - MARGIN);
  }
}

function overlaps(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

describe('placeTooltip: a bubble alone', () => {
  const bubble = { width: 200, height: 48 };

  it('sits above the anchor, centred, with the arrow at the anchor', () => {
    const anchor = { x: 160, y: 400, width: 40, height: 20 };
    const p = placeTooltip({ anchor, bubble, bounds: PHONE });
    expect(p.side).toBe('top');
    expect(p.bubble.y + bubble.height).toBe(anchor.y - 10);
    expect(p.bubble.x + p.arrowX).toBe(anchor.x + anchor.width / 2);
  });

  it('flips below when there is no room above', () => {
    const anchor = { x: 160, y: 30, width: 40, height: 20 };
    const input = { anchor, bubble, bounds: PHONE };
    const p = placeTooltip(input);
    expect(p.side).toBe('bottom');
    expect(p.bubble.y).toBe(anchor.y + anchor.height + 10);
    inside(p, input);
  });

  it('shifts away from the left and right edges at 360 px, keeping the arrow on the anchor', () => {
    for (const ax of [0, 4, 320, 340]) {
      const anchor = { x: ax, y: 300, width: 20, height: 20 };
      const input = { anchor, bubble, bounds: PHONE };
      const p = placeTooltip(input);
      inside(p, input);
      const anchorCx = ax + 10;
      // The arrow points at the anchor unless that would push it off the
      // bubble's rounded corner.
      expect(p.arrowX).toBeGreaterThanOrEqual(12);
      expect(p.arrowX).toBeLessThanOrEqual(bubble.width - 12);
      if (anchorCx >= p.bubble.x + 12 && anchorCx <= p.bubble.x + bubble.width - 12) {
        expect(p.bubble.x + p.arrowX).toBe(anchorCx);
      }
    }
  });

  it('respects the safe area', () => {
    const bounds = { x: 0, y: 44, width: 360, height: 740 - 44 - 34 };
    const anchor = { x: 100, y: 60, width: 30, height: 20 };
    const input = { anchor, bubble, bounds };
    const p = placeTooltip(input);
    expect(p.side).toBe('bottom');
    inside(p, input);
  });

  it('takes the roomier side when neither fits, and stays inside', () => {
    const tall = { width: 200, height: 500 };
    const anchor = { x: 160, y: 300, width: 40, height: 20 };
    const input = { anchor, bubble: tall, bounds: PHONE };
    const p = placeTooltip(input);
    expect(p.side).toBe('bottom');
    inside(p, input);
  });
});

describe('placeTooltip: a bubble with a stack', () => {
  const bubble = { width: 240, height: 60 };
  const stack = { width: 158, height: 250 };

  it('stacks vertically on a phone, on the far side, the bubble next to the anchor', () => {
    const anchor = { x: 150, y: 600, width: 54, height: 83 };
    const input = { anchor, bubble, stack, bounds: PHONE, allowBeside: false };
    const p = placeTooltip(input);
    expect(p.side).toBe('top');
    expect(p.stack?.mode).toBe('below');
    expect(p.stack!.y + stack.height).toBeLessThan(p.bubble.y);
    inside(p, input);
    // The connector spans the gap between them, vertically.
    expect(p.connector?.x1).toBe(p.connector?.x2);
    expect(p.connector?.y1).toBe(p.bubble.y);
    expect(p.connector?.y2).toBe(p.stack!.y + stack.height);
  });

  it('goes below a card in the top row of a phone pyramid', () => {
    const anchor = { x: 10, y: 120, width: 54, height: 83 };
    const input = { anchor, bubble, stack, bounds: PHONE, allowBeside: false };
    const p = placeTooltip(input);
    expect(p.side).toBe('bottom');
    expect(p.stack!.y).toBeGreaterThan(p.bubble.y + bubble.height);
    inside(p, input);
  });

  it('never overlaps the anchor at any edge of a phone', () => {
    for (const [ax, ay] of [
      [4, 100],
      [300, 100],
      [4, 600],
      [300, 600],
      [150, 330]
    ] as const) {
      const anchor = { x: ax, y: ay, width: 54, height: 83 };
      const input = { anchor, bubble, stack, bounds: PHONE, allowBeside: false };
      const p = placeTooltip(input);
      inside(p, input);
      expect(overlaps({ ...p.bubble, ...bubble }, anchor)).toBe(false);
      expect(overlaps({ ...p.stack!, ...stack }, anchor)).toBe(false);
    }
  });

  it('sits beside on a wide screen, on the side with room', () => {
    const left = { x: 20, y: 500, width: 72, height: 110 };
    const right = { x: 1200, y: 500, width: 72, height: 110 };
    for (const anchor of [left, right]) {
      const input = { anchor, bubble, stack, bounds: DESKTOP, allowBeside: true };
      const p = placeTooltip(input);
      expect(p.stack?.mode).toBe('beside');
      inside(p, input);
      expect(overlaps({ ...p.bubble, ...bubble }, { ...p.stack!, ...stack })).toBe(false);
      expect(p.connector?.y1).toBe(p.connector?.y2);
    }
    const pl = placeTooltip({ anchor: left, bubble, stack, bounds: DESKTOP, allowBeside: true });
    expect(pl.stack!.x).toBeGreaterThan(pl.bubble.x);
    const pr = placeTooltip({ anchor: right, bubble, stack, bounds: DESKTOP, allowBeside: true });
    expect(pr.stack!.x).toBeLessThan(pr.bubble.x);
  });

  it('falls back to vertical when side by side does not fit', () => {
    const anchor = { x: 150, y: 600, width: 54, height: 83 };
    const p = placeTooltip({ anchor, bubble, stack, bounds: PHONE, allowBeside: true });
    expect(p.stack?.mode).toBe('below');
  });

  it('aligns the stack with the bubble edge nearest the anchor when beside', () => {
    const anchor = { x: 600, y: 600, width: 72, height: 110 };
    const p = placeTooltip({ anchor, bubble, stack, bounds: DESKTOP, allowBeside: true });
    expect(p.side).toBe('top');
    expect(p.stack!.y + stack.height).toBe(p.bubble.y + bubble.height);
  });
});

describe('placeTooltip: a stack on a phone in landscape', () => {
  // A short screen: 740x360, less the notch's safe area on both sides.
  const LANDSCAPE: Rect = { x: 47, y: 0, width: 740 - 94, height: 360 };
  const bubble = { width: 272, height: 60 };
  const one = { width: 158, height: 260 };
  const three = { width: 452, height: 260 };

  function apart(p: Placement, input: PlaceInput): void {
    inside(p, input);
    expect(p.stack).toBeDefined();
    expect(overlaps({ ...p.bubble, ...input.bubble }, { ...p.stack!, ...input.stack! })).toBe(
      false
    );
  }

  it('puts the stack beside the bubble when stacking them would not fit', () => {
    for (const ay of [20, 140, 280]) {
      const anchor = { x: 340, y: ay, width: 48, height: 72 };
      // Even where the layer would not ask for beside (a narrow landscape).
      for (const allowBeside of [true, false]) {
        const input = { anchor, bubble, stack: one, bounds: LANDSCAPE, allowBeside };
        const p = placeTooltip(input);
        expect(p.stack?.mode).toBe('beside');
        apart(p, input);
      }
    }
  });

  it('moves the bubble and a wide stack as one, so they never overlap', () => {
    for (const [ax, ay] of [
      [60, 20],
      [340, 140],
      [600, 280],
      [340, 300]
    ] as const) {
      const anchor = { x: ax, y: ay, width: 48, height: 40 };
      const input = { anchor, bubble, stack: three, bounds: LANDSCAPE, allowBeside: true };
      const p = placeTooltip(input);
      expect(p.stack?.mode).toBe('below');
      apart(p, input);
    }
  });
});

describe('whole-card exclusion', () => {
  it('keeps above/below preference when either fits', () => {
    const anchor = { x: 16, y: 400, width: 140, height: 216 };
    const bubble = { width: 272, height: 180 };
    const input = { anchor, bubble, bounds: PHONE, avoidAnchor: true };
    const p = placeTooltip(input);
    expect(p.side).toBe('top');
    expect(overlaps({ ...p.bubble, ...bubble }, anchor)).toBe(false);
    inside(p, input);
  });

  it('uses a free column before covering a phone card, on either side', () => {
    for (const x of [16, 204]) {
      const anchor = { x, y: 220, width: 140, height: 300 };
      const bubble = { width: 174, height: 260 };
      const input = { anchor, bubble, bounds: PHONE, avoidAnchor: true };
      const p = placeTooltip(input);
      expect(p.side).toBe(x === 16 ? 'end' : 'start');
      expect(overlaps({ ...p.bubble, ...bubble }, anchor)).toBe(false);
      inside(p, input);
    }
  });
});
