<script lang="ts">
  import type { SkillEvidence } from '$lib/cards';
  import { evidenceTag } from '$lib/skillView';

  let { evidence }: { evidence: SkillEvidence[] } = $props();
</script>

<ul class="evidence-list">
  {#each evidence as item (item.id)}
    <li class="evidence-item">{item.name} <small>{evidenceTag(item)}</small></li>
  {/each}
</ul>
