<script lang="ts">
  import Logo from '$lib/components/Logo.svelte';
  import type { Mode } from '$lib/interview';

  // The mode is locked once a conversation is live: the server never switches a connection back.
  let { mode = $bindable(), locked, live }: { mode: Mode; locked: boolean; live: boolean } = $props();

  const OPTIONS: { value: Mode; label: string }[] = [
    { value: 'recruiter', label: 'recruiter' },
    { value: 'interview', label: 'interviewer' },
  ];
</script>

<header class="top">
  <a href="/" class="brand"><Logo size={30} /><span class="tag">mock interviews that talk back</span></a>
  <div class="mode" class:right={mode === 'interview'} role="radiogroup" aria-label="Mode">
    <span class="ind"></span>
    {#each OPTIONS as option (option.value)}
      <button role="radio" aria-checked={mode === option.value} disabled={locked && mode !== option.value} onclick={() => (mode = option.value)}>
        {option.label}
      </button>
    {/each}
  </div>
  <div class="live" class:on={live}><span class="rec"></span>{live ? 'live' : 'not live'}</div>
</header>

<style>
  .top { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 22px; border-bottom: 3px solid var(--color-ink); background: var(--color-sun); }
  .brand { display: flex; align-items: center; gap: 8px; color: inherit; text-decoration: none; }
  .tag { font-size: 12px; font-weight: 700; background: #fff; border: 2px solid var(--color-ink); border-radius: 999px; padding: 3px 9px; transform: rotate(-4deg); }
  .mode { position: relative; display: grid; grid-template-columns: 1fr 1fr; border: 3px solid var(--color-ink); border-radius: 999px; background: #fff; padding: 4px; width: 360px; box-shadow: 4px 4px 0 var(--color-ink); }
  .ind { position: absolute; top: 4px; bottom: 4px; left: 4px; width: calc(50% - 4px); border-radius: 999px; background: var(--color-ink); transition: transform .45s cubic-bezier(.5,-0.5,.3,1.5); }
  .mode.right .ind { transform: translateX(100%); }
  .mode button { position: relative; z-index: 1; border: 0; background: none; padding: 9px 0; font-weight: 800; font-size: 15px; transition: color .25s; }
  .mode button[aria-checked="true"] { color: #fff; }
  .mode button:disabled { opacity: .4; }
  .live { font-weight: 700; font-size: 14px; display: flex; align-items: center; gap: 8px; }
  .rec { width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--color-ink); background: #fff; }
  .live.on .rec { background: #ff4d4d; animation: pulse 1s infinite; }
  @keyframes pulse { 50% { transform: scale(.7); } }
  @media (max-width: 980px) { .tag, .live { display: none; } .mode { width: 240px; } }
  @media (max-width: 480px) { .top { padding: 12px 14px; } .mode { width: 200px; } .mode button { font-size: 13px; } }
</style>
