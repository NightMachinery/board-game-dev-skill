<script lang="ts">
  import type { Snippet } from 'svelte';
  import { RULE_SECTIONS, type RuleSectionId } from './sections';
  let { t, diagrams = {}, prefix = '' }: {
    t: (key: string) => string;
    diagrams?: Partial<Record<RuleSectionId, Snippet>>; prefix?: string;
  } = $props();
</script>

<nav aria-label={t('rules.contents')}>
  {#each RULE_SECTIONS as section}<a href={'#' + prefix + section.id}>{t(section.titleKey)}</a>{/each}
</nav>
{#each RULE_SECTIONS as section}
  <section id={prefix + section.id} data-rule-section={section.id}>
    <h2>{t(section.titleKey)}</h2><p>{t(section.bodyKey)}</p>
    {#if diagrams[section.id]}{@render diagrams[section.id]!()}{/if}
  </section>
{/each}

<style>
  nav { display: flex; flex-wrap: wrap; gap: .5rem 1rem; }
  section { scroll-margin-block-start: 1rem; }
</style>
