<script lang="ts">
  import type { SkillCard } from '$lib/cards';
  import { badgeOf } from '$lib/skillView';
  import EvidenceList from './EvidenceList.svelte';

  let { data }: { data: SkillCard['data'] } = $props();
</script>

<article class="card">
  <div class="skill-card__head">
    <div class="skill-card__badge" data-category={data.category} aria-hidden="true">{badgeOf(data.skill)}</div>
    <div>
      <h3 class="skill-card__name">{data.skill}</h3>
      <span class="skill-card__category">{data.category}</span>
    </div>
  </div>
  <p class="skill-card__used">used in <EvidenceList evidence={data.evidence} /></p>
</article>
