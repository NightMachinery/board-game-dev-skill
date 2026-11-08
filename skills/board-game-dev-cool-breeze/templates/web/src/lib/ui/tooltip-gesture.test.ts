import { describe, expect, it } from 'vitest';
import { downAction, LONG_PRESS_MS, Press, resolveAnchor, TOUCH_SLOP_PX } from './tooltip-gesture';

interface FakeNode {
  name: string;
  parent: FakeNode | null;
  anchor: boolean;
}

function chain(...specs: [string, boolean][]): FakeNode[] {
  const nodes: FakeNode[] = [];
  let parent: FakeNode | null = null;
  for (const [name, anchor] of specs) {
    const node: FakeNode = { name, parent, anchor };
    nodes.push(node);
    parent = node;
  }
  return nodes;
}

describe('resolveAnchor', () => {
  const resolve = (start: FakeNode | null) =>
    resolveAnchor(
      start,
      (n) => n.parent,
      (n) => n.anchor
    )?.name ?? null;

  it('picks the innermost registered anchor: a chip inside a card', () => {
    const [, , , chip, glyph] = chain(
      ['body', false],
      ['slot-button', true],
      ['card-face', false],
      ['chain-chip', true],
      ['svg-use', false]
    );
    expect(resolve(glyph!)).toBe('chain-chip');
    expect(resolve(chip!)).toBe('chain-chip');
  });

  it('falls back to the outer anchor off the chip', () => {
    const [, , face] = chain(['body', false], ['slot-button', true], ['card-face', false]);
    expect(resolve(face!)).toBe('slot-button');
  });

  it('finds nothing outside any anchor', () => {
    const [, inner] = chain(['body', false], ['div', false]);
    expect(resolve(inner!)).toBeNull();
    expect(resolve(null)).toBeNull();
  });
});

describe('Press (touch model B)', () => {
  it('a short tap on a passive element shows', () => {
    const p = new Press(100, 100, 0, false);
    expect(p.due(150)).toBe(false);
    expect(p.up(102, 101, 150)).toBe('show');
  });

  it('a short tap on an actionable element passes through to its action', () => {
    const p = new Press(100, 100, 0, true);
    expect(p.up(100, 100, 200)).toBe('pass');
  });

  it('a long-press fires at the threshold, and its release is swallowed', () => {
    const p = new Press(100, 100, 1000, true);
    expect(p.due(1000 + LONG_PRESS_MS - 1)).toBe(false);
    expect(p.due(1000 + LONG_PRESS_MS)).toBe(true);
    // Fires once.
    expect(p.due(1000 + LONG_PRESS_MS + 50)).toBe(false);
    expect(p.up(100, 100, 1900)).toBe('swallow');
  });

  it('a release after the threshold whose timer has not run yet is still a long-press', () => {
    const p = new Press(100, 100, 0, true);
    expect(p.up(100, 100, LONG_PRESS_MS + 20)).toBe('swallow');
    expect(p.fired).toBe(true);
  });

  it('moving past the slop cancels: a scroll is never a long-press', () => {
    const p = new Press(100, 100, 0, true);
    p.move(100, 100 + TOUCH_SLOP_PX + 1);
    expect(p.cancelled).toBe(true);
    expect(p.due(LONG_PRESS_MS + 10)).toBe(false);
    expect(p.up(100, 140, LONG_PRESS_MS + 10)).toBe('cancel');
  });

  it('small jitter within the slop is still a press', () => {
    const p = new Press(100, 100, 0, false);
    p.move(104, 106);
    expect(p.due(LONG_PRESS_MS)).toBe(true);
  });

  it('a move after the long-press fired does not undo it', () => {
    const p = new Press(100, 100, 0, true);
    expect(p.due(LONG_PRESS_MS)).toBe(true);
    p.move(160, 100);
    expect(p.up(160, 100, LONG_PRESS_MS + 100)).toBe('swallow');
  });

  it('a browser takeover (pointercancel) cancels, unless the tooltip already showed', () => {
    const early = new Press(0, 0, 0, true);
    expect(early.cancel()).toBe('cancel');
    const late = new Press(0, 0, 0, true);
    late.due(LONG_PRESS_MS);
    expect(late.cancel()).toBe('swallow');
  });
});

describe('downAction (the "More in Rules" link exception)', () => {
  const at = (mouse: boolean, open: boolean, inBubble = false, onLink = false) =>
    downAction({ mouse, open, inBubble, onLink });

  it('a mouse press closes an open tooltip, except inside its bubble', () => {
    expect(at(true, false)).toBe('keep');
    expect(at(true, true)).toBe('hide');
    expect(at(true, true, true)).toBe('keep');
    expect(at(true, true, true, true)).toBe('keep');
  });

  it('a touch closes an open tooltip and is swallowed, except on its link', () => {
    expect(at(false, false)).toBe('press');
    expect(at(false, true)).toBe('swallow');
    // Elsewhere in the bubble is still "any tap": it closes and is swallowed.
    expect(at(false, true, true)).toBe('swallow');
    expect(at(false, true, true, true)).toBe('keep');
  });
});
