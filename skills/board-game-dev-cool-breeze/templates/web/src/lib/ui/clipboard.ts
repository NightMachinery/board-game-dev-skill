// Call directly in a user gesture. A false result should show selectable text.
export async function copyText(text: string): Promise<boolean> {
  if (globalThis.isSecureContext && typeof globalThis.navigator?.clipboard?.writeText === 'function') {
    try { await navigator.clipboard.writeText(text); return true; } catch { /* fallback */ }
  }
  if (typeof document === 'undefined') return false;
  const before = document.activeElement;
  const selection = document.getSelection();
  const ranges = selection ? Array.from({ length: selection.rangeCount }, (_, i) => selection.getRangeAt(i).cloneRange()) : [];
  const field = document.createElement('textarea');
  field.value = text;
  field.readOnly = true;
  field.style.cssText = 'position:fixed;inset:0;opacity:0;pointer-events:none';
  document.body.append(field);
  try {
    field.focus({ preventScroll: true });
    field.select(); field.setSelectionRange(0, text.length);
    return document.execCommand('copy');
  } catch { return false; }
  finally {
    field.remove();
    if (before instanceof HTMLElement && before.isConnected) before.focus({ preventScroll: true });
    selection?.removeAllRanges();
    for (const range of ranges) selection?.addRange(range);
  }
}
