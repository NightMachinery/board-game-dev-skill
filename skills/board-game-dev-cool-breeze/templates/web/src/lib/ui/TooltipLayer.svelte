<script lang="ts">
  // Mount once. Marked bubble controls take the pointer; previews are read-only.
  import { tooltips, installTooltipGestures, TOOLTIP_ID } from './tooltip.svelte';
  import { placeTooltip } from './tooltip-place';
  import { openRules } from '../rules/rules-overlay.svelte';
  import type { RuleSectionId } from '../rules/sections';
  import type { Attachment } from 'svelte/attachments';
  let { onrules = openRules, rulesLabel }: {
    onrules?: (id: RuleSectionId) => void; rulesLabel: string;
  } = $props();
  let popover: HTMLDivElement | undefined = $state();
  const active = $derived(tooltips.active);
  $effect(() => installTooltipGestures());
  $effect(() => {
    if (!active && popover?.matches(':popover-open')) popover.hidePopover();
  });
  const place: Attachment<HTMLElement> = (group) => {
    const tip = active, pop = popover;
    const bubble = group.querySelector<HTMLElement>('[data-tooltip-bubble]');
    const stack = group.querySelector<HTMLElement>('[data-tooltip-stack]');
    const connector = group.querySelector<HTMLElement>('[data-tooltip-connector]');
    if (!tip || !pop || !bubble) return;
    if (pop.matches(':popover-open')) pop.hidePopover();
    pop.showPopover();
    const layout = () => {
      if (!tip.anchor.isConnected) { tooltips.hide(); return; }
      const anchor = tip.anchor.getBoundingClientRect();
      if (anchor.bottom <= 0 || anchor.top >= innerHeight || anchor.right <= 0 || anchor.left >= innerWidth) {
        tooltips.hide(); return;
      }
      const p = placeTooltip({ anchor, bubble: { width: bubble.offsetWidth, height: bubble.offsetHeight },
        stack: stack ? { width: stack.offsetWidth, height: stack.offsetHeight } : undefined,
        bounds: { x: 12, y: 12, width: Math.max(1, innerWidth - 24), height: Math.max(1, innerHeight - 24) },
        allowBeside: innerWidth >= 640, avoidAnchor: tip.content.avoidAnchor });
      bubble.style.transform = `translate(${p.bubble.x}px, ${p.bubble.y}px)`;
      if (stack && p.stack) stack.style.transform = `translate(${p.stack.x}px, ${p.stack.y}px)`;
      if (connector && p.connector) {
        const { x1, y1, x2, y2 } = p.connector;
        connector.style.transform = `translate(${Math.min(x1, x2)}px, ${Math.min(y1, y2)}px)`;
        connector.style.inlineSize = `${Math.max(2, Math.abs(x2 - x1))}px`;
        connector.style.blockSize = `${Math.max(2, Math.abs(y2 - y1))}px`;
      }
      group.dataset.placed = '';
    };
    layout();
    const observer = new ResizeObserver(layout);
    observer.observe(bubble); if (stack) observer.observe(stack);
    window.addEventListener('scroll', layout, { capture: true, passive: true });
    return () => { observer.disconnect(); window.removeEventListener('scroll', layout, true); };
  };
</script>

<div bind:this={popover} popover="manual" data-tooltip-layer dir="ltr">
  {#if active}
    {#key active.id}
      <div class="tooltip-group" data-tooltip-open={active.via} {@attach place}>
        {#if active.content.stack?.length}
          <span data-tooltip-connector></span>
          <div data-tooltip-stack>
            {#each active.content.stack.slice(0, 2) as item, i (i)}
              <figure dir="auto" data-tooltip-stack-item>
                <figcaption>{item.caption}</figcaption>
                {@render item.render()}
              </figure>
            {/each}
          </div>
        {/if}
        <div id={TOOLTIP_ID} role="tooltip" data-tooltip-bubble dir="auto">
          <span>{active.content.text}</span>
          {#each active.content.lines ?? [] as line}<span>{line}</span>{/each}
          {#if active.content.diagram}{@render active.content.diagram()}{/if}
          {#if active.content.controls}{@render active.content.controls()}{/if}
          {#if active.content.rulesId}
            <button type="button" data-tooltip-rules data-tooltip-interactive onclick={() => {
              const id = active?.content.rulesId; tooltips.hide(); if (id) onrules(id);
            }}>{rulesLabel}</button>
          {/if}
        </div>
      </div>
    {/key}
  {/if}
</div>

<style>
  [data-tooltip-layer] { position: fixed; inset: 0; margin: 0; border: 0; padding: 0;
    inline-size: 100%; block-size: 100%; max-inline-size: none; max-block-size: none;
    background: transparent; overflow: visible; pointer-events: none; }
  [data-tooltip-layer]:popover-open { display: block; }
  [data-tooltip-bubble], [data-tooltip-stack], [data-tooltip-connector] {
    position: absolute; inset-block-start: 0; inset-inline-start: 0; }
  [data-tooltip-bubble], [data-tooltip-stack] {
    gap: .3rem; padding: .6rem .8rem; border: 1px solid var(--tooltip-rule, currentColor);
    border-radius: .6rem; background: var(--tooltip-bg, Canvas); color: var(--tooltip-fg, CanvasText);
    font: 0.875rem/1.4 system-ui; box-shadow: 0 2px 12px #0003; }
  [data-tooltip-bubble] { display: grid; max-inline-size: min(18rem, calc(100vw - 40px)); }
  [data-tooltip-stack] { display: flex; gap: .5rem; inline-size: max-content;
    max-inline-size: calc(100vw - 40px); }
  figure { margin: 0; min-inline-size: 0; max-inline-size: 8.5rem; }
  figcaption { margin-block-end: .3rem; text-align: center; }
  [data-tooltip-connector] { background: var(--tooltip-rule, currentColor); }
  .tooltip-group:not(:global([data-placed])) { visibility: hidden; }
  .tooltip-group :global(*) { pointer-events: none !important; }
  .tooltip-group :global([data-tooltip-bubble] [data-tooltip-interactive]),
  .tooltip-group :global([data-tooltip-bubble] [data-tooltip-interactive] *) { pointer-events: auto !important; }
  [data-tooltip-rules] { min-block-size: 2.75rem; }
  :global([data-tooltip]) { -webkit-touch-callout: none; user-select: none; }
</style>
