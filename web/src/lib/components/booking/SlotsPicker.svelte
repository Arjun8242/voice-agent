<script lang="ts">
  import type { CardActionHandler, SlotsCard } from '$lib/cards';
  import { MEETING_MINUTES, groupSlotsByDay } from '$lib/bookingView';
  import CardHeader from './CardHeader.svelte';

  let { data, onAction }: { data: SlotsCard['data']; onAction: CardActionHandler } = $props();

  const days = $derived(groupSlotsByDay(data.slots));
  let selected = $state<string | null>(null);
  // a fresh slots card with different times must not stay locked by a pick from the old one
  const picked = $derived(data.slots.some((slot) => slot.slot_id === selected) ? selected : null);

  function pick(slotId: string) {
    if (picked) return;
    selected = slotId;
    onAction('select_slot', { slot_id: slotId });
  }
</script>

<article class="card">
  <CardHeader title="Pick a time" tags={[`${MEETING_MINUTES} min`]} />
  <div class="booking-body">
    <p class="booking-note">Free times in your timezone ({data.timezone}). Nothing is booked yet.</p>
    <div class="slot-days">
      {#each days as day (day.day)}
        <section>
          <h4 class="slot-day__label">{day.day}</h4>
          <ul class="slot-day__times">
            {#each day.times as slot (slot.slot_id)}
              <li>
                <button class="slot-button" aria-pressed={picked === slot.slot_id} disabled={picked !== null} onclick={() => pick(slot.slot_id)}>
                  {slot.time}
                </button>
              </li>
            {/each}
          </ul>
        </section>
      {/each}
    </div>
  </div>
</article>
