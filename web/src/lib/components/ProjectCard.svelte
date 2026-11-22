<script lang="ts">
  import type { ProjectDetailCard } from '$lib/cards';
  import { needsCollapse, projectLinks, statusView } from '$lib/cardView';

  let { data }: { data: ProjectDetailCard['data'] } = $props();

  const status = $derived(statusView(data.status));
  const links = $derived(projectLinks(data.links));
  const collapsible = $derived(needsCollapse(data.text));
  let expanded = $state(false);
</script>

<article class="card">
  <header class="project-card__top">
    <div class="project-card__title">
      <h3 class="project-card__name">{data.name}</h3>
      <span class="status" data-tone={status.tone}>{status.label}</span>
    </div>
    {#if data.one_line}<p class="project-card__one-line">{data.one_line}</p>{/if}
    <ul class="project-card__sections" aria-label="Sections">
      {#each data.sections ?? [data.section] as section (section)}
        <li class="project-card__section" aria-current={section === data.section}>{section}</li>
      {/each}
    </ul>
  </header>

  <div class="project-card__body">
    <p class="project-card__text" data-collapsed={collapsible && !expanded}>{data.text}</p>
    {#if collapsible}
      <button class="project-card__toggle" aria-expanded={expanded} onclick={() => (expanded = !expanded)}>
        {expanded ? 'show less' : 'read more'}
      </button>
    {/if}
  </div>

  {#if data.tech?.length}
    <ul class="project-card__tech" aria-label="Tech">
      {#each data.tech as tech (tech)}<li class="project-card__pill">{tech}</li>{/each}
    </ul>
  {/if}

  <footer class="project-card__links">
    {#each links as link (link.key)}
      {#if link.href}
        <a class="link-button" data-primary={link.key === 'repo'} href={link.href} target="_blank" rel="noopener noreferrer">{link.label} ↗</a>
      {:else}
        <span class="link-button" aria-disabled="true">{link.label} ↗</span>
      {/if}
    {/each}
  </footer>
</article>
