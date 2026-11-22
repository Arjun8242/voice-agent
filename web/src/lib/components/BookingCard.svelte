<script lang="ts">
  import type { BookingCard, CardActionHandler } from '$lib/cards';
  import SlotsPicker from './booking/SlotsPicker.svelte';
  import DetailsForm from './booking/DetailsForm.svelte';
  import Summary from './booking/Summary.svelte';
  import CancelConfirm from './booking/CancelConfirm.svelte';
  import Ticket from './booking/Ticket.svelte';
  import Outcome from './booking/Outcome.svelte';

  // Picks the booking card for the server's card type. onAction sends a ui_action; the server checks every field.
  let { card, onAction }: { card: BookingCard; onAction: CardActionHandler } = $props();

  // Buttons that confirm or cancel are used once per card state: the card is re-sent as a new type after each step.
  let usedFor = $state<string | null>(null);
  const used = $derived(usedFor === card.type);

  const once: CardActionHandler = (action, payload) => {
    if (used) return;
    usedFor = card.type;
    onAction(action, payload);
  };
</script>

{#if card.type === 'slots'}
  <SlotsPicker data={card.data} {onAction} />
{:else if card.type === 'booking_form'}
  <DetailsForm data={card.data} {onAction} />
{:else if card.type === 'booking_summary'}
  <Summary data={card.data} onAction={once} disabled={used} />
{:else if card.type === 'cancel_confirm'}
  <CancelConfirm data={card.data} onAction={once} disabled={used} />
{:else if card.type === 'booking_confirmed'}
  <Ticket data={card.data} />
{:else}
  <Outcome type={card.type} data={card.data} />
{/if}
