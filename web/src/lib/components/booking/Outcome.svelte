<script lang="ts">
  import type { BookingOutcomeCard } from '$lib/cards';
  import { outcomeView } from '$lib/bookingView';

  let { type, data }: { type: BookingOutcomeCard['type']; data: BookingOutcomeCard['data'] } = $props();

  const view = $derived(outcomeView(type));
</script>

<article class="card booking-notice">
  <span class="booking-notice__icon" data-tone={view.tone} aria-hidden="true">{view.icon}</span>
  <div>
    <h3 class="booking-notice__title">{view.title}</h3>
    <p class="booking-notice__text">{data.text}</p>
  </div>
</article>
