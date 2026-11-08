<script lang="ts">
  // Nonmodal desktop drawer keeps the board live; phones use a modal sheet.
  import { onMount, tick, type Snippet } from 'svelte';
  import { rulesOverlay, closeRules } from './rules-overlay.svelte';
  import type { RuleSectionId } from './sections';
  import RulesContent from './RulesContent.svelte';
  import { restoreFocus } from '../ui/dismiss';
  let { t, diagrams = {}, pathname }: { t: (key: string) => string;
    diagrams?: Partial<Record<RuleSectionId, Snippet>>; pathname: string } = $props();
  let panel: HTMLDialogElement | undefined = $state();
  let wide = $state(false);
  let opener: HTMLElement | null = null;
  onMount(() => {
    const media = matchMedia('(min-width: 64rem)');
    const update = () => { wide = media.matches; };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && rulesOverlay.open && !event.defaultPrevented) closeRules();
    };
    update(); media.addEventListener('change', update);
    window.addEventListener('keydown', escape);
    return () => { media.removeEventListener('change', update); window.removeEventListener('keydown', escape); };
  });
  $effect(() => {
    if (rulesOverlay.open && pathname !== rulesOverlay.openedOn) {
      const openedOn = rulesOverlay.openedOn;
      queueMicrotask(() => { if (rulesOverlay.openedOn === openedOn) closeRules(); });
    }
  });
  $effect(() => {
    const el = panel, open = rulesOverlay.open, desktop = wide;
    if (!el) return;
    if (!open) {
      if (el.open) el.close();
      if (opener?.isConnected) restoreFocus(opener);
      opener = null; return;
    }
    if (!opener && document.activeElement instanceof HTMLElement) opener = document.activeElement;
    if (el.open) el.close();
    if (desktop) el.show(); else el.showModal();
  });
  $effect(() => {
    const request = rulesOverlay.request, id = rulesOverlay.section, el = panel;
    if (!rulesOverlay.open || !el) return;
    void tick().then(() => {
      if (request !== rulesOverlay.request || !el.open) return;
      if (id) el.querySelector<HTMLElement>(`[data-rule-section="${id}"]`)?.scrollIntoView({ block: 'start' });
      else el.scrollTop = 0;
    });
  });
</script>

<dialog bind:this={panel} aria-label={t('rules.title')} data-rules-overlay
  oncancel={(event) => { event.preventDefault(); closeRules(); }}>
  <header><h1>{t('rules.title')}</h1><button type="button" onclick={closeRules}>{t('common.close')}</button></header>
  <RulesContent {t} {diagrams} prefix="overlay-" />
</dialog>

<style>
  dialog { position: fixed; inset: auto 0 0; margin: 0; inline-size: 100%; max-inline-size: none;
    block-size: min(88dvh, 60rem); max-block-size: 90dvh; box-sizing: border-box;
    padding: 1rem; overflow: auto; border: 1px solid var(--rules-rule, currentColor);
    border-start-start-radius: 1rem; border-start-end-radius: 1rem;
    color: var(--rules-fg, CanvasText); background: var(--rules-bg, Canvas); }
  header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
  button { min-block-size: 2.75rem; }
  dialog::backdrop { background: #0006; }
  @media (min-width: 64rem) {
    dialog { inset-block: 0; inset-inline: auto 0; inline-size: min(28rem, 42vw);
      block-size: 100dvh; max-block-size: none; border-radius: 0; }
  }
</style>
