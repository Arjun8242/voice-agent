<script lang="ts">
  import type { BookingOutcomeCard } from '$lib/cards';
  import { MEETING_MINUTES, parseSlotLabel } from '$lib/bookingView';

  // Shown only after the calendar call really succeeded: the server sends booking_confirmed then, and not before.
  let { data }: { data: BookingOutcomeCard['data'] } = $props();

  const when = $derived(parseSlotLabel(data.label));
</script>

<article class="card booking-ticket" data-dated={when !== null}>
  {#if when}
    <div class="booking-ticket__date" aria-hidden="true">
      <span class="booking-ticket__month">{when.month.toUpperCase()}</span>
      <span class="booking-ticket__day">{when.day}</span>
      <span class="booking-ticket__weekday">{when.weekday}</span>
    </div>
  {/if}
  <div class="booking-ticket__main">
    <span class="booking-ticket__badge">✓ booked</span>
    <h3 class="booking-ticket__title">{data.title}</h3>
    <p class="booking-ticket__when">{when ? `${when.time} ${when.zone}` : data.label} · {MEETING_MINUTES} min</p>
    <p class="booking-ticket__invite">The invite is on its way to {data.email}</p>
  </div>
</article>
