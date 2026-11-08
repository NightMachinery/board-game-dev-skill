import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { copyText } from './clipboard';

// Only the DOM surface copying needs, with observable focus and selections.
class Element {
  focus = vi.fn();
  closest = vi.fn(() => null);
}
class Field extends Element {
  value = '';
  readOnly = false;
  style = { cssText: '' };
  selectionStart: number | null = 2;
  selectionEnd: number | null = 5;
  selectionDirection = 'backward';
  setSelectionRange = vi.fn();
  select = vi.fn();
  remove = vi.fn();
}

describe('copyText', () => {
  const active = new Field();
  const textarea = new Field();
  const range = { cloneRange: vi.fn() };
  const selection = {
    rangeCount: 1,
    getRangeAt: vi.fn(() => range),
    removeAllRanges: vi.fn(),
    addRange: vi.fn()
  };
  const document = {
    activeElement: active,
    getSelection: vi.fn(() => selection),
    createElement: vi.fn(() => textarea),
    body: { append: vi.fn() },
    execCommand: vi.fn(() => true)
  };
  const writeText = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    writeText.mockResolvedValue(undefined);
    document.execCommand.mockReset().mockReturnValue(true);
    range.cloneRange.mockReturnValue(range);
    vi.stubGlobal('HTMLElement', Element);
    vi.stubGlobal('HTMLInputElement', Field);
    vi.stubGlobal('HTMLTextAreaElement', Field);
    vi.stubGlobal('document', document);
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    vi.stubGlobal('isSecureContext', true);
  });
  afterEach(() => vi.unstubAllGlobals());

  it('uses the secure API without changing focus or selection', async () => {
    expect(await copyText('secure link')).toBe(true);
    expect(writeText).toHaveBeenCalledWith('secure link');
    expect(document.createElement).not.toHaveBeenCalled();
    expect(active.focus).not.toHaveBeenCalled();
  });

  it('copies synchronously when the API is missing and restores both selections', async () => {
    vi.stubGlobal('navigator', {});
    const result = copyText('HTTP link');
    expect(document.execCommand).toHaveBeenCalledWith('copy');
    expect(textarea.value).toBe('HTTP link');
    expect(textarea.readOnly).toBe(true);
    expect(document.body.append).toHaveBeenCalledWith(textarea);
    expect(textarea.select).toHaveBeenCalledOnce();
    expect(textarea.remove).toHaveBeenCalledOnce();
    expect(active.focus).toHaveBeenCalledWith({ preventScroll: true });
    expect(selection.removeAllRanges).toHaveBeenCalledOnce();
    expect(selection.addRange).toHaveBeenCalledWith(range);
    expect(active.setSelectionRange).toHaveBeenCalledWith(2, 5, 'backward');
    expect(await result).toBe(true);
  });

  it('skips the modern API in an insecure context even when exposed', async () => {
    vi.stubGlobal('isSecureContext', false);
    const result = copyText('HTTP link');
    expect(document.execCommand).toHaveBeenCalledOnce();
    expect(writeText).not.toHaveBeenCalled();
    expect(await result).toBe(true);
  });

  it('falls back when the secure API rejects', async () => {
    writeText.mockRejectedValue(new Error('permission denied'));
    expect(await copyText('link')).toBe(true);
    expect(document.execCommand).toHaveBeenCalledOnce();
  });

  it.each(['false', 'throws'])(
    'reports execCommand failure (%s) and restores focus',
    async (mode) => {
      vi.stubGlobal('navigator', {});
      if (mode === 'throws')
        document.execCommand.mockImplementation(() => {
          throw new Error('denied');
        });
      else document.execCommand.mockReturnValue(false);
      expect(await copyText('link')).toBe(false);
      expect(textarea.remove).toHaveBeenCalledOnce();
      expect(active.focus).toHaveBeenCalledOnce();
      expect(active.setSelectionRange).toHaveBeenCalledWith(2, 5, 'backward');
    }
  );

  it('reports failure outside a browser', async () => {
    vi.stubGlobal('document', undefined);
    expect(await copyText('link')).toBe(false);
  });
});
