/** Copy on HTTPS and plain HTTP, preserving the caller's focus and selection. */
export async function copyText(text: string): Promise<boolean> {
  if (typeof document === 'undefined') return false;
  if (globalThis.isSecureContext && typeof navigator !== 'undefined') {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch {
      // Permissions or browser policy can reject the modern API. Try selection.
    }
  }
  return copySelection(text);
}

function copySelection(text: string): boolean {
  const active = document.activeElement;
  const field =
    active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement ? active : null;
  const start = field?.selectionStart ?? null;
  const end = field?.selectionEnd ?? null;
  const direction = field?.selectionDirection ?? null;
  const selection = document.getSelection();
  const ranges = selection
    ? Array.from({ length: selection.rangeCount }, (_, i) => selection.getRangeAt(i).cloneRange())
    : [];
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.readOnly = true;
  textarea.style.cssText = 'position:fixed;inset:0;opacity:0;pointer-events:none;';
  try {
    (active?.closest('dialog[open]') ?? document.body).append(textarea);
    textarea.select();
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    textarea.remove();
    if (active instanceof HTMLElement) active.focus({ preventScroll: true });
    if (selection) {
      selection.removeAllRanges();
      for (const range of ranges) selection.addRange(range);
    }
    if (field && start !== null && end !== null) {
      field.setSelectionRange(start, end, direction ?? undefined);
    }
  }
}
