<script lang="ts">
  import type { BookingSummaryCard, CardActionHandler } from '$lib/cards';
  import CardHeader from './CardHeader.svelte';

  let { data, onAction, disabled }: { data: BookingSummaryCard['data']; onAction: CardActionHandler; disabled: boolean } = $props();
</script>

<article class="card">
  <CardHeader title="Check and confirm" tags={['step 3 of 3']} />
  <div class="booking-body">
    <dl class="booking-summary">
      <dt>When</dt><dd>{data.label} ({data.duration_minutes} min)</dd>
      <dt>Title</dt><dd>{data.title}</dd>
      <dt>Name</dt><dd>{data.name}</dd>
      <dt>Invite to</dt><dd>{data.email}</dd>
    </dl>
    <div class="action-buttons">
      <button class="action-button" data-tone="go" {disabled} onclick={() => onAction('confirm', { booking_id: data.booking_id })}>Confirm booking</button>
      <button class="action-button" {disabled} onclick={() => onAction('cancel', { booking_id: data.booking_id })}>Cancel</button>
    </div>
  </div>
</article>
