<script lang="ts">
  import { MODES, PERSONAS, type Mode, type PersonaName } from '$lib/interview';

  // The mode and persona are locked once an interview starts: the server never switches a connection back.
  let {
    mode = $bindable(),
    persona = $bindable(),
    started,
    ended,
    onstart,
    onend,
  }: {
    mode: Mode;
    persona: PersonaName;
    started: boolean;
    ended: boolean;
    onstart: () => void;
    onend: () => void;
  } = $props();

  const description = $derived(PERSONAS.find((p) => p.name === persona)?.description ?? '');
</script>

<div class="w-full max-w-2xl flex flex-col items-center gap-3">
  <div role="radiogroup" aria-label="Mode" class="inline-flex rounded-full bg-[hsl(222,47%,14%)] border border-[hsl(217,33%,22%)] p-1">
    {#each MODES as option (option.value)}
      <button
        role="radio"
        aria-checked={mode === option.value}
        disabled={started}
        onclick={() => (mode = option.value)}
        class="px-4 py-1.5 rounded-full text-sm transition-colors disabled:cursor-not-allowed
          {mode === option.value ? 'bg-[hsl(199,89%,48%)] text-white' : 'text-[hsl(215,20%,65%)] hover:text-white'}"
      >
        {option.label}
      </button>
    {/each}
  </div>

  {#if mode === 'interview'}
    <div class="flex flex-wrap items-center justify-center gap-3">
      <label class="flex items-center gap-2 text-sm text-[hsl(215,20%,65%)]">
        Interviewer
        <select
          bind:value={persona}
          disabled={started}
          class="rounded-lg bg-[hsl(222,47%,14%)] border border-[hsl(217,33%,22%)] px-2 py-1 text-white disabled:opacity-60"
        >
          {#each PERSONAS as option (option.name)}
            <option value={option.name}>{option.label}</option>
          {/each}
        </select>
      </label>

      {#if !started}
        <button onclick={onstart} class="rounded-lg bg-[hsl(199,89%,48%)] hover:bg-[hsl(199,89%,42%)] px-4 py-1.5 text-sm font-medium text-white">
          Start interview
        </button>
      {:else if !ended}
        <button onclick={onend} class="rounded-lg bg-red-500/80 hover:bg-red-500 px-4 py-1.5 text-sm font-medium text-white">
          End interview
        </button>
      {/if}
    </div>

    {#if ended}
      <p class="text-xs text-[hsl(215,20%,65%)]" role="status">Interview ended. Reload the page to start a new one.</p>
    {:else}
      <p class="text-xs text-[hsl(215,20%,55%)]">{description} Say "repeat that" if you miss a question.</p>
    {/if}
  {/if}
</div>
