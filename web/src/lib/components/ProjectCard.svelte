<script lang="ts">
  import type { ProjectDetailCard } from '$lib/cards';

  let { data }: { data: ProjectDetailCard['data'] } = $props();

  // Status words follow the knowledge base: only "shipped" may be called built.
  const statusLabel: Record<string, string> = {
    shipped: 'Shipped',
    runnable_not_deployed: 'Runs locally, not deployed',
    in_progress: 'In progress',
    idea: 'Idea',
  };
</script>

<div class="panel p-4">
  <div class="flex items-start justify-between gap-3 mb-2">
    <p class="text-xs font-medium text-ink font-bold uppercase tracking-wider">{data.name} · {data.section}</p>
    <span class="shrink-0 rounded-full bg-cream px-2 py-0.5 text-[10px] font-medium text-neutral-600">
      {statusLabel[data.status] ?? data.status}
    </span>
  </div>

  <p class="text-sm leading-relaxed whitespace-pre-line max-h-64 overflow-y-auto">{data.text}</p>

  {#if data.links.repo || data.links.live}
    <div class="flex gap-4 mt-3 text-xs">
      {#if data.links.repo}
        <a href={data.links.repo} target="_blank" rel="noopener noreferrer" class="text-ink font-bold hover:underline">Repository</a>
      {/if}
      {#if data.links.live}
        <a href={data.links.live} target="_blank" rel="noopener noreferrer" class="text-ink font-bold hover:underline">Live demo</a>
      {/if}
    </div>
  {/if}
</div>
