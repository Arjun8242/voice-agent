<script lang="ts">
  import { onMount } from 'svelte';
  import Character from '$lib/components/Character.svelte';

  // Sapwa and Sheru Bhai take turns asking sample questions, typed out word by word.
  type Side = 'sapwa' | 'sheru';
  const LINES: [Side, string][] = [
    ['sapwa', 'Hello ji! Walk me through your background. Take your time.'],
    ['sheru', 'Why Redis and not just Postgres for the queue, bhai?'],
    ['sapwa', 'Nice. Can you give me a concrete example from the project?'],
    ['sheru', 'What breaks first at ten times the load?'],
    ['sapwa', 'Tell me about a time you disagreed with a teammate.'],
    ['sheru', "You said 'we'. What did you do, exactly?"],
  ];
  const WORD_MS = 110;
  const PAUSE_MS = 1700;

  let talker = $state<Side | null>(null);
  let shown = $state('');
  let typing = $state(false);

  onMount(() => {
    let stopped = false;
    const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
    (async () => {
      for (let i = 0; !stopped; i = (i + 1) % LINES.length) {
        const [side, text] = LINES[i];
        talker = side;
        typing = true;
        const words = text.split(' ');
        for (let w = 1; w <= words.length && !stopped; w++) {
          shown = words.slice(0, w).join(' ');
          await sleep(WORD_MS);
        }
        typing = false;
        await sleep(PAUSE_MS);
      }
    })();
    return () => { stopped = true; };
  });
</script>

<header class="hero">
  <div>
    <span class="eyebrow">✦ voice mock interviews</span>
    <h1>
      interviews<br />that <span class="hl">talk back</span><br />to
      <span class="sq">you.<svg viewBox="0 0 200 22" preserveAspectRatio="none" aria-hidden="true"><path d="M3 15 C 50 4, 120 4, 197 12" fill="none" stroke="#ff8fc8" stroke-width="7" stroke-linecap="round" /></svg></span>
    </h1>
    <p class="lede">
      Drop your résumé, talk out loud, and get grilled by an AI interviewer that actually listens. It follows up on what
      you <i>say</i>, not on a script. Then you get honest feedback on every answer.
    </p>
    <div class="cta">
      <a class="btn" href="/app">start a mock interview →</a>
      <a class="btn ghost" href="#how">see how it works</a>
    </div>
    <p class="fine">15 minutes · résumé PDF · job description optional · deleted after</p>
  </div>

  <div class="duo" aria-hidden="true">
    <div class="speech a" class:on={talker === 'sapwa'}>{talker === 'sapwa' ? shown : ''}{#if talker === 'sapwa' && typing}<span class="cur"></span>{/if}</div>
    <div class="speech k" class:on={talker === 'sheru'}>{talker === 'sheru' ? shown : ''}{#if talker === 'sheru' && typing}<span class="cur"></span>{/if}</div>
    <div class="card a" class:talking={talker === 'sapwa'}>
      <Character kind="sapwa" phase={talker === 'sapwa' && typing ? 'speaking' : 'idle'} followPointer seed={1} class="art" />
      <div class="who"><span class="nm">Sapwa</span><span class="chip">master ji</span></div>
    </div>
    <div class="card k" class:talking={talker === 'sheru'}>
      <Character kind="sheru" phase={talker === 'sheru' && typing ? 'speaking' : 'idle'} followPointer seed={2} class="art" />
      <div class="who"><span class="nm">Sheru Bhai</span><span class="chip">boss energy</span></div>
    </div>
    <div class="sticker s1">no script ✦</div>
    <div class="sticker s2">real follow-ups</div>
  </div>
</header>

<style>
  .hero { display: grid; grid-template-columns: 1.05fr 1fr; gap: 30px; align-items: center; padding: 70px 0 60px; }
  .eyebrow { display: inline-flex; gap: 8px; align-items: center; background: var(--color-sky); border: 2.5px solid var(--color-ink); border-radius: 999px; padding: 5px 14px; font-weight: 800; font-size: 14px; transform: rotate(-2deg); }
  h1 { font-size: clamp(54px, 7.2vw, 104px); line-height: .9; letter-spacing: -.06em; margin: 22px 0 0; font-weight: 800; }
  .hl { background: var(--color-sun); border: 3px solid var(--color-ink); border-radius: 18px; padding: 0 12px; display: inline-block; transform: rotate(-2.5deg); box-shadow: 5px 5px 0 var(--color-ink); margin: 6px 0; }
  .sq { position: relative; display: inline-block; }
  .sq svg { position: absolute; left: -2%; bottom: -14px; width: 104%; height: 22px; }
  .lede { font-size: 21px; line-height: 1.45; font-weight: 500; max-width: 520px; margin: 26px 0 0; color: #333; }
  .cta { display: flex; gap: 14px; margin-top: 30px; flex-wrap: wrap; }
  .ghost { background: #fff; }
  .fine { margin-top: 18px; font-weight: 600; font-size: 14px; color: #666; }
  .lede, .fine { background: var(--color-cream); border-radius: 12px; box-shadow: 0 0 0 10px var(--color-cream); }

  .duo { position: relative; height: 520px; }
  .card { position: absolute; width: 290px; border: 3px solid var(--color-ink); border-radius: 30px; padding: 16px 16px 12px; box-shadow: 8px 8px 0 var(--color-ink); transition: transform .4s cubic-bezier(.3,1.6,.5,1); }
  .card.a { left: 0; top: 70px; background: #e6f4cf; transform: rotate(-4deg); }
  .card.k { right: 0; top: 190px; background: #fff0cf; transform: rotate(4deg); }
  .card.talking { transform: rotate(0deg) scale(1.04); z-index: 2; }
  .card :global(.art) { width: 100%; height: 220px; display: block; }
  .who { display: flex; justify-content: space-between; align-items: center; margin-top: 4px; }
  .nm { font-weight: 800; font-size: 24px; letter-spacing: -.03em; white-space: nowrap; }
  .who .chip { white-space: nowrap; font-size: 13px; }

  .speech { position: absolute; max-width: 300px; background: #fff; border: 3px solid var(--color-ink); border-radius: 20px; padding: 12px 16px; font-weight: 600; font-size: 16px; line-height: 1.35; box-shadow: 5px 5px 0 var(--color-ink); min-height: 50px; z-index: 3; opacity: 0; transition: opacity .2s; }
  .speech.on { opacity: 1; }
  .speech::after { content: ""; position: absolute; width: 18px; height: 18px; background: #fff; border-right: 3px solid var(--color-ink); border-bottom: 3px solid var(--color-ink); bottom: -12px; transform: rotate(45deg); }
  .speech.a { left: 150px; top: 0; } .speech.a::after { left: 30px; }
  .speech.k { right: 40px; top: 108px; } .speech.k::after { right: 40px; }
  .cur { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--color-ink); margin-left: 4px; animation: pulse .6s infinite; }
  @keyframes pulse { 50% { transform: scale(.6); } }

  .sticker { position: absolute; border: 2.5px solid var(--color-ink); border-radius: 14px; padding: 6px 12px; font-weight: 800; font-size: 14px; box-shadow: 3px 3px 0 var(--color-ink); }
  .s1 { left: 40px; bottom: 20px; background: var(--color-leaf); transform: rotate(-6deg); }
  .s2 { right: 30px; bottom: 0; background: var(--color-bubblegum); transform: rotate(8deg); }

  @media (max-width: 980px) {
    .hero { grid-template-columns: 1fr; }
    .duo { height: 500px; max-width: 520px; }
  }
  /* phones: one bubble across the top, the two cards side by side below it, so neither hides the other */
  @media (max-width: 560px) {
    .duo { height: 390px; }
    .speech.a, .speech.k { left: 0; right: 0; top: 0; max-width: none; font-size: 15px; }
    .speech.a::after { left: 22%; right: auto; }
    .speech.k::after { right: 22%; left: auto; }
    .card { width: 48%; padding: 10px 10px 8px; border-radius: 22px; box-shadow: 5px 5px 0 var(--color-ink); }
    .card.a { top: 112px; transform: rotate(-3deg); }
    .card.k { top: 132px; transform: rotate(3deg); }
    .card.talking { transform: scale(1.03); }
    .card :global(.art) { height: 130px; }
    .who { flex-direction: column; align-items: flex-start; gap: 4px; }
    .nm { font-size: 19px; }
    .s1 { left: 6px; bottom: 6px; }
    .s2 { right: 6px; bottom: 0; }
  }
</style>
