<script lang="ts">
  import type { BookingCard } from '$lib/cards';

  // onAction sends a ui_action to the server; the server checks every field and decides what happens.
  let { card, onAction }: { card: BookingCard; onAction: (action: string, payload: Record<string, string>) => void } = $props();

  let name = $state('');
  let email = $state('');
  let title = $state('');
  // Buttons that confirm or cancel are used once per card. The server guards double clicks anyway.
  let clicked = $state(false);

  function once(action: string, payload: Record<string, string>) {
    if (clicked) return;
    clicked = true;
    onAction(action, payload);
  }

  const good = new Set(['booking_confirmed', 'booking_cancelled']);
</script>

<div class="panel p-4">
  {#if card.type === 'slots'}
    <p class="text-xs font-medium text-ink font-bold mb-3 uppercase tracking-wider">Free times ({card.data.timezone})</p>
    <div class="flex flex-wrap gap-2">
      {#each card.data.slots as slot (slot.slot_id)}
        <button
          class="px-3 py-1.5 rounded-lg text-sm bg-cream hover:bg-sun border-2 border-ink"
          onclick={() => onAction('select_slot', { slot_id: slot.slot_id })}
        >{slot.label}</button>
      {/each}
    </div>

  {:else if card.type === 'booking_form'}
    <p class="text-xs font-medium text-ink font-bold mb-1 uppercase tracking-wider">Book {card.data.label}</p>
    <p class="text-xs text-neutral-600 mb-3">30 minutes. Nothing is booked until you confirm.</p>
    <form
      class="flex flex-col gap-2"
      onsubmit={(e) => { e.preventDefault(); onAction('submit_details', { booking_id: card.data.booking_id, name, email, title }); }}
    >
      <label class="text-xs text-neutral-600">Your name
        <input bind:value={name} required maxlength="80" autocomplete="name"
          class="mt-1 w-full rounded-lg bg-cream border-2 border-ink px-3 py-2 text-sm" />
      </label>
      <label class="text-xs text-neutral-600">Your email (the invite goes here)
        <input bind:value={email} type="email" required maxlength="254" autocomplete="email"
          class="mt-1 w-full rounded-lg bg-cream border-2 border-ink px-3 py-2 text-sm" />
      </label>
      <label class="text-xs text-neutral-600">Meeting title (optional)
        <input bind:value={title} maxlength="80" placeholder={card.data.default_title}
          class="mt-1 w-full rounded-lg bg-cream border-2 border-ink px-3 py-2 text-sm" />
      </label>
      <div class="flex gap-2 mt-1">
        <button type="submit" class="px-4 py-2 rounded-lg text-sm bg-sun border-2 border-ink font-bold">Continue</button>
        <button type="button" class="px-4 py-2 rounded-lg text-sm bg-cream"
          onclick={() => once('cancel', { booking_id: card.data.booking_id })}>Cancel</button>
      </div>
    </form>

  {:else if card.type === 'booking_summary'}
    <p class="text-xs font-medium text-ink font-bold mb-2 uppercase tracking-wider">Check and confirm</p>
    <dl class="text-sm grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 mb-3">
      <dt class="text-neutral-600">When</dt><dd>{card.data.label} ({card.data.duration_minutes} min)</dd>
      <dt class="text-neutral-600">Title</dt><dd>{card.data.title}</dd>
      <dt class="text-neutral-600">Name</dt><dd>{card.data.name}</dd>
      <dt class="text-neutral-600">Invite to</dt><dd class="break-all">{card.data.email}</dd>
    </dl>
    <div class="flex gap-2">
      <button class="px-4 py-2 rounded-lg text-sm bg-sun border-2 border-ink font-bold disabled:opacity-50"
        disabled={clicked} onclick={() => once('confirm', { booking_id: card.data.booking_id })}>Confirm booking</button>
      <button class="px-4 py-2 rounded-lg text-sm bg-cream disabled:opacity-50"
        disabled={clicked} onclick={() => once('cancel', { booking_id: card.data.booking_id })}>Cancel</button>
    </div>

  {:else if card.type === 'cancel_confirm'}
    <p class="text-sm mb-3">Cancel your meeting on {card.data.label}?</p>
    <div class="flex gap-2">
      <button class="px-4 py-2 rounded-lg text-sm bg-bubblegum border-2 border-ink font-bold disabled:opacity-50"
        disabled={clicked} onclick={() => once('confirm_cancel', { booking_id: card.data.booking_id })}>Yes, cancel it</button>
      <button class="px-4 py-2 rounded-lg text-sm bg-cream disabled:opacity-50"
        disabled={clicked} onclick={() => once('keep_booking', { booking_id: card.data.booking_id })}>Keep it</button>
    </div>

  {:else}
    <p class="text-xs font-medium mb-1 uppercase tracking-wider {good.has(card.type) ? 'text-green-700' : 'text-red-700'}">
      {good.has(card.type) ? 'Done' : 'Not done'}
    </p>
    <p class="text-sm leading-relaxed">{card.data.text}</p>
  {/if}
</div>
