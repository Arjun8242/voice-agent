<script lang="ts">
  import type { LinkCard } from '$lib/cards';

  let { data }: { data: LinkCard['data'] } = $props();
</script>

<a
  href={data.url}
  target="_blank"
  rel="noopener noreferrer"
  class="block panel p-4 hover:-translate-y-0.5 transition-transform"
>
  <p class="text-xs font-medium text-ink font-bold mb-1 uppercase tracking-wider">{data.label}</p>
  <p class="text-sm leading-relaxed">{data.description}</p>
  <p class="text-xs text-neutral-600 mt-2 break-all">{data.url}</p>
</a>
