<script lang="ts">
  import type { LinkCard } from '$lib/cards';
  import { hostOf, initials } from '$lib/cardView';

  let { data }: { data: LinkCard['data'] } = $props();
</script>

<a class="card link-card" href={data.url} target="_blank" rel="noopener noreferrer">
  <div class="link-card__icon" aria-hidden="true">{initials(data.label)}</div>
  <div>
    <p class="link-card__label">{data.label}</p>
    <p class="link-card__description">{data.description}</p>
    <p class="link-card__host">{hostOf(data.url)}</p>
  </div>
  <div class="link-card__go" aria-hidden="true">↗</div>
</a>
