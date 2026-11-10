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

<div class="rounded-xl bg-[hsl(222,47%,14%)] border border-[hsl(199,89%,48%)]/30 p-4">
  <div class="flex items-start justify-between gap-3 mb-2">
    <p class="text-xs font-medium text-[hsl(199,89%,48%)] uppercase tracking-wider">{data.name} · {data.section}</p>
    <span class="shrink-0 rounded-full bg-[hsl(217,33%,17%)] px-2 py-0.5 text-[10px] font-medium text-[hsl(215,20%,75%)]">
      {statusLabel[data.status] ?? data.status}
    </span>
  </div>

  <p class="text-sm leading-relaxed whitespace-pre-line max-h-64 overflow-y-auto">{data.text}</p>

  {#if data.links.repo || data.links.live}
    <div class="flex gap-4 mt-3 text-xs">
      {#if data.links.repo}
        <a href={data.links.repo} target="_blank" rel="noopener noreferrer" class="text-[hsl(199,89%,48%)] hover:underline">Repository</a>
      {/if}
      {#if data.links.live}
        <a href={data.links.live} target="_blank" rel="noopener noreferrer" class="text-[hsl(199,89%,48%)] hover:underline">Live demo</a>
      {/if}
    </div>
  {/if}
</div>
