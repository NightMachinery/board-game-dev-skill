import { afterEach, expect, it, vi } from 'vitest';
import { copyText } from './clipboard';
afterEach(() => vi.unstubAllGlobals());
it('uses the secure API when available', async () => {
  const writeText = vi.fn(async () => {});
  vi.stubGlobal('isSecureContext', true);
  vi.stubGlobal('navigator', { clipboard: { writeText } });
  expect(await copyText('room link')).toBe(true);
  expect(writeText).toHaveBeenCalledWith('room link');
});
it('copies on plain HTTP through a selected field and restores focus', async () => {
  vi.stubGlobal('isSecureContext', false);
  class FakeElement { isConnected = true; focus = vi.fn(); }
  vi.stubGlobal('HTMLElement', FakeElement);
  const before = new FakeElement();
  const field = { style: {}, focus: vi.fn(), select: vi.fn(), setSelectionRange: vi.fn(), remove: vi.fn(), value: '', readOnly: false };
  const execCommand = vi.fn(() => true);
  vi.stubGlobal('document', { activeElement: before, getSelection: () => null,
    createElement: () => field, body: { append: vi.fn() }, execCommand });
  expect(await copyText('http room')).toBe(true);
  expect(field.value).toBe('http room'); expect(field.select).toHaveBeenCalled();
  expect(execCommand).toHaveBeenCalledWith('copy'); expect(field.remove).toHaveBeenCalled();
  expect(before.focus).toHaveBeenCalledWith({ preventScroll: true });
});
it('reports unavailable copying rather than claiming success', async () => {
  vi.stubGlobal('isSecureContext', false); vi.stubGlobal('document', undefined);
  expect(await copyText('text')).toBe(false);
});
