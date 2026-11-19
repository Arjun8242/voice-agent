<script lang="ts">
  import Character from '$lib/components/Character.svelte';
  import { CHARACTERS } from '$lib/characters';
  import { clock } from '$lib/convo';
  import { PERSONAS, STAGE_CHIPS, chipState, stepPersona, type Mode, type PersonaName } from '$lib/interview';
  import type { Phase } from '$lib/motion';

  // The left half of the talk screen: the character, who it is, and the buttons that start and stop.
  // The stage chips follow the server's interview_stage message after each interview turn.
  let {
    mode, persona = $bindable(), phase, visitorSpeaking, holding, liveStage,
    started, ended, micOn, planReady, elapsed, limit,
    onstart, onend, ontogglemic,
  }: {
    mode: Mode; persona: PersonaName; phase: Phase; visitorSpeaking: boolean; holding: boolean; liveStage: string | null;
    started: boolean; ended: boolean; micOn: boolean; planReady: boolean; elapsed: number; limit: number;
    onstart: () => void; onend: () => void; ontogglemic: () => void;
  } = $props();

  const interviewing = $derived(mode === 'interview');
  const current = $derived(PERSONAS.find((p) => p.name === persona) ?? PERSONAS[0]);
  const kind = $derived(interviewing ? current.character : 'rep');
  const look = $derived(CHARACTERS[kind]);
  const canSwap = $derived(interviewing && !started);

  const bubble = $derived.by(() => {
    if (holding) return 'take your time…';
    if (phase === 'listening') return "i'm all ears 👂";
    if (phase === 'thinking') return 'hmm…';
    if (phase === 'speaking') return '';
    if (ended) return 'good talk!';
    return interviewing ? 'hi! pick me or swipe →' : 'ask me about arjun!';
  });

  function onKey(e: KeyboardEvent) {
    if (!canSwap || (e.target as HTMLElement).closest('input, textarea')) return;
    if (e.key === 'ArrowLeft') persona = stepPersona(persona, -1);
    if (e.key === 'ArrowRight') persona = stepPersona(persona, 1);
  }
</script>

<svelte:window onkeydown={onKey} />

<section class="stage" style="--c: {look.color}; --c-soft: {look.soft}">
  <ol class="levels" style:visibility={interviewing ? 'visible' : 'hidden'} aria-label="Interview stages">
    {#each STAGE_CHIPS as chip, i (chip.kind)}
      {@const state = chipState(i, liveStage)}
      <li class="lv {state}" aria-current={state === 'now' ? 'step' : undefined}><span>{i + 1}</span>{chip.label}</li>
    {/each}
  </ol>

  <div class="pit">
    <div class="bubble" class:hide={!bubble} aria-live="polite">{bubble}</div>
    <Character {kind} {phase} {visitorSpeaking} class="char" />
  </div>

  <div>
    <div class="nameplate">
      <button class="arrow" aria-label="Previous interviewer" disabled={!canSwap} onclick={() => (persona = stepPersona(persona, -1))}>‹</button>
      <div class="plate"><div class="nm">{look.name}</div><div class="vibe">{look.vibe}</div></div>
      <button class="arrow" aria-label="Next interviewer" disabled={!canSwap} onclick={() => (persona = stepPersona(persona, 1))}>›</button>
    </div>

    <div class="go-row">
      {#if !interviewing}
        <button class="go" onclick={ontogglemic}>{micOn ? 'stop talking ■' : 'start talking →'}</button>
      {:else if !started}
        <button class="go" disabled={!planReady} onclick={onstart} title={planReady ? '' : 'Upload your résumé first'}>let's go →</button>
      {:else if !ended}
        <!-- spoken commands: the server listens for these words; there is no button message for them -->
        <span class="pill">say “repeat”</span>
        {#if current.givesHints}<span class="pill">“hint”</span>{/if}
        <span class="pill">“skip”</span>
        <button class="pill bye" onclick={onend}>end</button>
      {:else}
        <a class="pill" href="/app" data-sveltekit-reload>new interview</a>
      {/if}
    </div>
  </div>

  {#if interviewing}<div class="timer">{clock(elapsed)} / {clock(limit)}</div>{/if}
</section>

<style>
  .stage { position: relative; background: var(--c-soft); border-right: 3px solid var(--color-ink); display: grid; grid-template-rows: auto 1fr auto; grid-template-columns: minmax(0, 1fr); padding: 18px 24px 22px; min-height: 0; transition: background .4s; }
  .levels { display: flex; gap: 6px; justify-content: center; flex-wrap: wrap; list-style: none; margin: 0; padding: 0; }
  .lv { display: flex; align-items: center; gap: 6px; border: 2.5px solid var(--color-ink); background: #fff; border-radius: 999px; padding: 3px 9px 3px 3px; font-weight: 700; font-size: 12px; transition: all .3s; }
  .lv span { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--color-ink); display: grid; place-items: center; font-size: 12px; }
  .lv.done { opacity: .55; }
  .lv.done span { background: var(--color-ink); color: #fff; }
  .lv.now { background: var(--color-ink); color: #fff; transform: translateY(-2px) rotate(-2deg); box-shadow: 3px 3px 0 var(--c); }
  .lv.now span { background: var(--color-sun); color: var(--color-ink); border-color: var(--color-sun); }

  .pit { position: relative; display: grid; place-items: center; min-height: 0; }
  .pit :global(.char) { width: min(330px, 80vw); height: min(330px, 80vw); }
  .bubble { position: absolute; top: 2%; left: 58%; background: #fff; border: 3px solid var(--color-ink); border-radius: 18px; padding: 8px 14px; font-weight: 800; font-size: 15px; box-shadow: 4px 4px 0 var(--color-ink); transform: rotate(4deg); transition: opacity .25s, transform .25s; white-space: nowrap; z-index: 1; }
  .bubble::after { content: ""; position: absolute; left: 18px; bottom: -12px; width: 16px; height: 16px; background: #fff; border-right: 3px solid var(--color-ink); border-bottom: 3px solid var(--color-ink); transform: rotate(45deg) skew(10deg, 10deg); }
  .bubble.hide { opacity: 0; transform: rotate(4deg) translateY(6px); }

  .nameplate { display: flex; align-items: center; justify-content: center; gap: 14px; }
  .arrow { width: 44px; height: 44px; border-radius: 50%; border: 3px solid var(--color-ink); background: #fff; font-weight: 800; font-size: 20px; box-shadow: 3px 3px 0 var(--color-ink); transition: transform .1s, box-shadow .1s; }
  .arrow:active:not(:disabled) { transform: translate(2px, 2px); box-shadow: 1px 1px 0 var(--color-ink); }
  .arrow:disabled { opacity: .3; }
  .plate { text-align: center; min-width: 220px; }
  .nm { font-weight: 800; font-size: 40px; letter-spacing: -.04em; line-height: 1; }
  .vibe { display: inline-block; margin-top: 6px; font-weight: 700; font-size: 13px; background: #fff; border: 2px solid var(--color-ink); border-radius: 999px; padding: 3px 10px; transform: rotate(-2deg); }

  .go-row { display: flex; justify-content: center; flex-wrap: wrap; gap: 10px; margin-top: 14px; min-height: 58px; align-items: center; }
  .go { border: 3px solid var(--color-ink); background: var(--color-sun); border-radius: 18px; padding: 14px 34px; font-weight: 800; font-size: 22px; letter-spacing: -.02em; box-shadow: 6px 6px 0 var(--color-ink); transition: transform .1s, box-shadow .1s; }
  .go:hover:not(:disabled) { transform: translate(-1px, -1px) rotate(-1deg); box-shadow: 7px 7px 0 var(--color-ink); }
  .go:active:not(:disabled) { transform: translate(4px, 4px); box-shadow: 2px 2px 0 var(--color-ink); }
  .go:disabled { opacity: .45; }
  .pill { border: 2.5px solid var(--color-ink); background: #fff; border-radius: 999px; padding: 8px 14px; font-weight: 700; font-size: 14px; box-shadow: 3px 3px 0 var(--color-ink); color: inherit; text-decoration: none; }
  button.pill:active { transform: translate(2px, 2px); box-shadow: 1px 1px 0 var(--color-ink); }
  .pill.bye { background: var(--color-bubblegum); }
  .timer { position: absolute; right: 18px; bottom: 18px; font-weight: 800; font-size: 14px; background: #fff; border: 2.5px solid var(--color-ink); border-radius: 10px; padding: 4px 9px; }

  @media (max-width: 980px) {
    .stage { border-right: 0; border-bottom: 3px solid var(--color-ink); min-height: 600px; }
    .timer { top: 18px; bottom: auto; right: 14px; }
    .levels { padding-top: 34px; }
  }
  @media (max-width: 480px) { .nm { font-size: 30px; } .plate { min-width: 0; } .bubble { left: auto; right: 0; } }
</style>
