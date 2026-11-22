<script lang="ts">
  import CalendarDays from '@lucide/svelte/icons/calendar-days';

  let { title, tags = [] }: { title: string; tags?: string[] } = $props();
</script>

<header class="booking-header">
  <span class="booking-header__icon" aria-hidden="true"><CalendarDays size={18} strokeWidth={2.4} /></span>
  <h3 class="booking-header__title">{title}</h3>
  {#if tags.length}
    <ul class="booking-header__tags">
      {#each tags as tag (tag)}<li class="booking-header__tag">{tag}</li>{/each}
    </ul>
  {/if}
</header>
