<script lang="ts">
  import type { LinkCard } from '$lib/cards';

  let { data }: { data: LinkCard['data'] } = $props();
</script>

<a
  href={data.url}
  target="_blank"
  rel="noopener noreferrer"
  class="block rounded-xl bg-[hsl(222,47%,14%)] border border-[hsl(199,89%,48%)]/30 p-4 hover:border-[hsl(199,89%,48%)]/60 transition-colors"
>
  <p class="text-xs font-medium text-[hsl(199,89%,48%)] mb-1 uppercase tracking-wider">{data.label}</p>
  <p class="text-sm leading-relaxed">{data.description}</p>
  <p class="text-xs text-[hsl(215,20%,55%)] mt-2 break-all">{data.url}</p>
</a>
