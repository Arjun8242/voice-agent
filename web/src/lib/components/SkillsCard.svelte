<script lang="ts">
  import type { SkillsCard } from '$lib/cards';
  import { groupSkills } from '$lib/skillView';
  import EvidenceList from './EvidenceList.svelte';

  let { data }: { data: SkillsCard['data'] } = $props();

  const groups = $derived(groupSkills(data.skills));
  let selectedName = $state<string | null>(null);
  const selected = $derived(data.skills.find((entry) => entry.skill === selectedName));
</script>

<article class="card">
  <header class="skills-card__top">
    <h3 class="skills-card__title">Skills</h3>
    <span class="skills-card__count">{data.skills.length} listed</span>
  </header>

  <div class="skills-card__groups">
    {#each groups as group (group.category)}
      <section>
        <h4 class="skills-card__group-label">{group.label}</h4>
        <ul class="skills-card__chips">
          {#each group.skills as entry (entry.skill)}
            <li>
              <button
                class="skill-chip"
                data-category={entry.category}
                aria-pressed={selectedName === entry.skill}
                onclick={() => (selectedName = entry.skill)}
              >{entry.skill}</button>
            </li>
          {/each}
        </ul>
      </section>
    {/each}
  </div>

  <div class="skills-card__evidence" aria-live="polite">
    {#if selected}
      <b>{selected.skill}</b> → used in <EvidenceList evidence={selected.evidence} />
    {:else}
      <p class="skills-card__hint">tap a skill to see where he used it</p>
    {/if}
  </div>
</article>
