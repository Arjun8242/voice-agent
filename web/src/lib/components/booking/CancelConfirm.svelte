<script lang="ts">
  import type { CancelConfirmCard, CardActionHandler } from '$lib/cards';

  let { data, onAction, disabled }: { data: CancelConfirmCard['data']; onAction: CardActionHandler; disabled: boolean } = $props();
</script>

<article class="card booking-notice">
  <span class="booking-notice__icon" aria-hidden="true">?</span>
  <div>
    <h3 class="booking-notice__title">Cancel your meeting on {data.label}?</h3>
    <div class="action-buttons">
      <button class="action-button" data-tone="danger" {disabled} onclick={() => onAction('confirm_cancel', { booking_id: data.booking_id })}>Yes, cancel it</button>
      <button class="action-button" {disabled} onclick={() => onAction('keep_booking', { booking_id: data.booking_id })}>Keep it</button>
    </div>
  </div>
</article>
