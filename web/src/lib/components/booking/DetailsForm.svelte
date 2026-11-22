<script lang="ts">
  import CalendarDays from '@lucide/svelte/icons/calendar-days';
  import type { BookingFormCard, CardActionHandler } from '$lib/cards';
  import { MEETING_MINUTES } from '$lib/bookingView';
  import CardHeader from './CardHeader.svelte';

  let { data, onAction }: { data: BookingFormCard['data']; onAction: CardActionHandler } = $props();

  let name = $state('');
  let email = $state('');
  let title = $state('');
  // Cancel is used once per card; the server guards double clicks anyway.
  let cancelled = $state(false);

  function submit(event: SubmitEvent) {
    event.preventDefault();
    onAction('submit_details', { booking_id: data.booking_id, name, email, title });
  }

  function cancel() {
    if (cancelled) return;
    cancelled = true;
    onAction('cancel', { booking_id: data.booking_id });
  }
</script>

<article class="card">
  <CardHeader title="Your details" tags={['step 2 of 3']} />
  <div class="booking-body">
    <p class="booking-chosen">
      <CalendarDays size={18} strokeWidth={2.4} aria-hidden="true" />
      <span>{data.label} <small>· {MEETING_MINUTES} min</small></span>
    </p>
    <form onsubmit={submit}>
      <label class="booking-field"><span>Your name</span>
        <input bind:value={name} required maxlength="80" autocomplete="name" />
      </label>
      <label class="booking-field"><span>Your email (the invite goes here)</span>
        <input bind:value={email} type="email" required maxlength="254" autocomplete="email" />
      </label>
      <label class="booking-field"><span>Meeting title (optional)</span>
        <input bind:value={title} maxlength="80" placeholder={data.default_title} />
      </label>
      <div class="action-buttons">
        <button class="action-button" data-tone="go" type="submit" disabled={cancelled}>Continue →</button>
        <button class="action-button" type="button" disabled={cancelled} onclick={cancel}>Cancel</button>
      </div>
    </form>
    <p class="booking-note booking-note--after">Nothing is booked until you confirm.</p>
  </div>
</article>
