<script lang="ts">
  // Replace this adapter with the game's translator before shipping.
  import RulesContent from '../../lib/rules/RulesContent.svelte';
  const t = (key: string) => key;
</script>

<svelte:head><title>{t('rules.title')}</title></svelte:head>
<main><h1>{t('rules.title')}</h1><RulesContent {t} /></main>
