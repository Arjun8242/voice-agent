<script lang="ts">
  // The wordmark. The name is a placeholder from the design; change it here and in <title>s.
  let { size = 28 }: { size?: number } = $props();
</script>

<span class="logo" style="font-size: {size}px">viva<span class="bang">!</span></span>

<style>
  .logo { font-weight: 800; letter-spacing: -.04em; white-space: nowrap; }
  .bang { display: inline-block; transform: rotate(12deg); color: var(--color-bubblegum); -webkit-text-stroke: 1.5px var(--color-ink); }
</style>
