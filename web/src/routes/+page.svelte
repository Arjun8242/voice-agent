<script lang="ts">
  import Logo from '$lib/components/Logo.svelte';
  import Character from '$lib/components/Character.svelte';
  import Hero from '$lib/components/landing/Hero.svelte';
  import Crew from '$lib/components/landing/Crew.svelte';
  import { reveal } from '$lib/reveal';

  // The landing page (docs/viva-landing.html). Static text only; the voice app is at /app.
  const MARQUEE = ['no script', 'real follow-ups', 'say "I" not "we"', 'pausing is allowed', 'numbers > adjectives',
    'feedback on every answer', "it's giving STAR method", 'deleted after'];

  const STEPS = [
    { title: 'drop your résumé', text: "Upload a PDF. Paste the job description if you have one. viva builds a plan from what's actually on your résumé, plus the gaps against the role.", example: '"we\'ll cover your internship, Beacon, and Node.js / Postgres"' },
    { title: 'talk it out', text: 'A real voice conversation. Interrupt, pause to think, ask for a hint, skip. Every follow-up is written from your last answer.', example: '"why five retries? what if it\'s a bug, not a timeout?"' },
    { title: 'get the receipts', text: 'A report for every question: your transcript, what a strong answer covers, what you hit, what you missed, and one thing to fix.', example: 'deep dive: strong · behavioral: needs a result' },
  ];

  const STOPS = [
    { name: 'intro', count: '1 question', text: 'walk me through your background' },
    { name: 'deep dive', count: '2–4 questions', text: 'what you did → why → what broke' },
    { name: 'technical', count: '2–4 questions', text: 'from the job description, gaps first' },
    { name: 'behavioral', count: '1–2 questions', text: 'STAR, framed around your work' },
    { name: 'flex', count: '2 questions', text: 'achievements or open source, if you have them' },
    { name: 'wrap-up', count: 'closing', text: 'and then your report' },
  ];

  const FEATURES = [
    { icon: '⏸', tint: 'var(--color-sun)', title: 'pauses are allowed', text: "Thinking out loud doesn't get you cut off. It waits for you to actually finish." },
    { icon: '✋', tint: 'var(--color-sky)', title: 'interrupt anytime', text: 'Talk over it and it stops. Say "repeat", "hint" or "skip" whenever you need to.' },
    { icon: '🎯', tint: 'var(--color-bubblegum)', title: 'grounded questions', text: "It only asks about what's on your résumé and what you said. No made-up claims about you." },
    { icon: '🗑', tint: 'var(--color-leaf)', title: 'gone after', text: 'Your résumé is used for the session, then deleted. Contact details never reach the AI.' },
  ];

  const FAQ = [
    { q: 'What do I need to start?', a: 'A résumé as a PDF and a microphone. A job description is optional. With one, you also get questions on the gaps between your résumé and the role.' },
    { q: 'How long is an interview?', a: 'About 15 minutes, usually 8 to 13 questions depending on how deep your answers go.' },
    { q: 'Is it the same questions every time?', a: 'No. The plan comes from your résumé, and every follow-up is written from your last answer. Two people with the same job description get different interviews.' },
    { q: 'What happens to my résumé?', a: "It's used to plan your session and deleted when the session ends. Contact details like your email and phone number are stripped before anything reaches the AI." },
    { q: "What's recruiter mode?", a: "The other side of viva: an AI representative that answers recruiters' questions about Arjun, who built this, from his portfolio. It always says it's an AI." },
  ];
</script>

<svelte:head>
  <title>viva! — mock interviews that talk back</title>
  <meta name="description" content="A voice mock interviewer that reads your résumé, asks real follow-ups, and gives you feedback on every answer." />
</svelte:head>

<nav class="wrap">
  <div class="nav">
    <a href="/"><Logo /></a>
    <div class="links">
      <a href="#how">how it works</a><a href="#crew">the crew</a><a href="#report">the report</a><a href="#faq">faq</a>
    </div>
    <a class="btn btn-sm" href="/app">try it →</a>
  </div>
</nav>

<div class="wrap"><Hero /></div>

<div class="marquee" aria-hidden="true">
  <div class="track">
    {#each [0, 1, 2] as copy (copy)}
      {#each MARQUEE as item (item)}<span>{item}</span><span class="star">✦</span>{/each}
    {/each}
  </div>
</div>

<section class="wrap" id="how">
  <div class="sec-head" use:reveal>
    <h2>how it<br /><span class="hl">works</span></h2>
    <p>Three steps. No forms to fill in, no GitHub to connect. Just your résumé and your voice.</p>
  </div>
  <div class="steps">
    {#each STEPS as step, i (step.title)}
      <div class="step" use:reveal>
        <div class="num">{i + 1}</div>
        <h3>{step.title}</h3>
        <p>{step.text}</p>
        <div class="mini">{step.example}</div>
      </div>
    {/each}
  </div>
</section>

<section class="wrap" id="crew">
  <div class="sec-head" use:reveal>
    <h2>meet the<br /><span class="hl">crew</span></h2>
    <p>Pick who interviews you. Same questions, very different energy.</p>
  </div>
  <Crew />
</section>

<section class="wrap">
  <div class="sec-head" use:reveal>
    <h2>a real interview<br /><span class="hl">shape</span></h2>
    <p>Not five random questions. Stages in a fixed order, with a minimum and maximum in each, so it never rushes and never drags.</p>
  </div>
  <div class="map" use:reveal>
    <div class="lane">
      {#each STOPS as stop, i (stop.name)}
        <div class="stop"><div class="dot">{i + 1}</div><h4>{stop.name}</h4><div class="q">{stop.count}</div><p>{stop.text}</p></div>
      {/each}
    </div>
    <div class="map-foot">
      <span class="chip">follow-ups climb: explain → justify → stress-test</span>
      <span class="chip">"I don't know" moves on, no penalty</span>
      <span class="chip">time is shared so every stage gets its turn</span>
    </div>
  </div>
</section>

<section class="wrap" id="report">
  <div class="report">
    <div use:reveal>
      <h2>feedback,<br />not a <span class="hl">vibe check</span></h2>
      <ul>
        <li><b>✓</b>Every question, with your own words next to it, so you can see exactly what was graded.</li>
        <li><b>✦</b>What a strong answer covers, and which of those points you actually hit.</li>
        <li><b>!</b>Plain bands, strong / ok / weak, instead of fake-precise scores out of 10.</li>
        <li><b>?</b>Words the speech-to-text may have mis-heard are listed and never held against you.</li>
      </ul>
    </div>
    <div class="sheet" use:reveal>
      <div class="sheet-top"><h4>your report</h4><span class="chip">sample</span></div>
      <div class="bands">
        <span class="band strong">deep dive · strong</span>
        <span class="band ok">technical · ok</span>
        <span class="band weak">behavioral · weak</span>
      </div>
      <div class="qa">
        <div class="qq">Q: What happens to a job that fails because of a bug, not a timeout?</div>
        <div class="qa-a">"It keeps failing, so after the retries it lands in the dead-letter queue and we alert on it."</div>
        <div class="row"><i>✅</i>named the dead-letter queue as the end state</div>
        <div class="row"><i>✅</i>mentioned alerting</div>
        <div class="row"><i>❌</i>didn't separate retryable from non-retryable errors</div>
        <div class="heard">heard "dead letter cue" → read as dead-letter queue</div>
        <div class="fix">fix: say how you'd stop retrying a bug early instead of burning all five attempts.</div>
      </div>
    </div>
  </div>
</section>

<section class="wrap">
  <div class="sec-head" use:reveal><h2>small things,<br /><span class="hl">done right</span></h2></div>
  <div class="feats">
    {#each FEATURES as feature (feature.title)}
      <div class="feat" use:reveal>
        <div class="ic" style="background: {feature.tint}" aria-hidden="true">{feature.icon}</div>
        <h3>{feature.title}</h3>
        <p>{feature.text}</p>
      </div>
    {/each}
  </div>
</section>

<section class="wrap" id="faq">
  <div class="sec-head" use:reveal><h2>questions,<br /><span class="hl">answered</span></h2></div>
  <div class="faq">
    {#each FAQ as item (item.q)}
      <details use:reveal><summary>{item.q}</summary><p>{item.a}</p></details>
    {/each}
  </div>
</section>

<div class="wrap">
  <div class="final" use:reveal>
    <div>
      <h2>ready to get<br />grilled?</h2>
      <p>15 minutes with Sapwa or Sheru Bhai. Bring your résumé and your voice.</p>
      <a class="btn" href="/app">start a mock interview →</a>
    </div>
    <Character kind="sapwa" phase="idle" followPointer class="final-art" />
  </div>
  <footer>
    <Logo size={22} />
    <span>built by Arjun · a voice agent project</span>
    <div class="links"><a href="#how">how it works</a><a href="#faq">faq</a><a href="/app">try it</a></div>
  </footer>
</div>

<style>
  :global(html) { scroll-behavior: smooth; }
  a { color: inherit; text-decoration: none; }
  .wrap { width: min(1180px, calc(100% - 40px)); margin: 0 auto; }

  nav { position: sticky; top: 14px; z-index: 20; margin-top: 14px; }
  .nav { display: flex; align-items: center; justify-content: space-between; background: #fff; border: 3px solid var(--color-ink); border-radius: 22px; padding: 10px 12px 10px 20px; box-shadow: 5px 5px 0 var(--color-ink); }
  .links { display: flex; gap: 6px; }
  .links a { font-weight: 700; font-size: 15px; padding: 8px 12px; border-radius: 12px; }
  .links a:hover { background: var(--color-cream); }

  .marquee { border-block: 3px solid var(--color-ink); background: var(--color-ink); color: var(--color-sun); overflow: hidden; white-space: nowrap; transform: rotate(-1.2deg); margin: 10px -20px 0; }
  .track { display: inline-block; padding: 14px 0; font-weight: 800; font-size: 22px; animation: tick 30s linear infinite; will-change: transform; }
  .track span { margin: 0 22px; }
  .track .star { color: var(--color-bubblegum); }
  @keyframes tick { to { transform: translateX(-33.33%); } }

  section { padding: 100px 0 20px; }
  .sec-head { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 36px; flex-wrap: wrap; }
  h2 { font-size: clamp(40px, 5vw, 66px); line-height: .95; letter-spacing: -.05em; margin: 0; font-weight: 800; }
  .hl { background: var(--color-sun); border: 3px solid var(--color-ink); border-radius: 14px; padding: 0 10px; display: inline-block; transform: rotate(-2deg); }
  .sec-head p { max-width: 420px; font-size: 18px; line-height: 1.45; font-weight: 500; color: #444; margin: 0; }
  .sec-head p, .report ul, footer { background: var(--color-cream); border-radius: 12px; box-shadow: 0 0 0 10px var(--color-cream); }

  .steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; }
  .step { background: #fff; border: 3px solid var(--color-ink); border-radius: 26px; padding: 26px; box-shadow: 7px 7px 0 var(--color-ink); }
  .step:nth-child(2) { transform: translateY(26px) rotate(1deg); }
  .step:nth-child(3) { transform: rotate(-1deg); }
  .num { width: 54px; height: 54px; border-radius: 50%; border: 3px solid var(--color-ink); display: grid; place-items: center; font-weight: 800; font-size: 26px; background: var(--color-sun); margin-bottom: 18px; }
  .step:nth-child(2) .num { background: var(--color-sky); }
  .step:nth-child(3) .num { background: var(--color-bubblegum); }
  .step h3 { font-size: 28px; letter-spacing: -.03em; margin: 0 0 10px; }
  .step p { margin: 0; font-size: 16.5px; line-height: 1.5; color: #444; font-weight: 500; }
  .mini { margin-top: 18px; border: 2.5px dashed var(--color-ink); border-radius: 16px; padding: 12px; font-weight: 700; font-size: 14px; background: var(--color-cream); }

  .map { background: #fff; border: 3px solid var(--color-ink); border-radius: 30px; padding: 30px; box-shadow: 8px 8px 0 var(--color-ink); }
  .lane { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; position: relative; }
  .lane::before { content: ""; position: absolute; left: 6%; right: 6%; top: 34px; border-top: 3px dashed var(--color-ink); }
  .stop { position: relative; text-align: center; }
  .dot { width: 68px; height: 68px; margin: 0 auto; border-radius: 50%; border: 3px solid var(--color-ink); display: grid; place-items: center; font-weight: 800; font-size: 26px; background: #fff; position: relative; box-shadow: 4px 4px 0 var(--color-ink); }
  .stop:nth-child(1) .dot { background: var(--color-sun); } .stop:nth-child(2) .dot { background: var(--color-lilac); }
  .stop:nth-child(3) .dot { background: var(--color-sky); } .stop:nth-child(4) .dot { background: var(--color-bubblegum); }
  .stop:nth-child(5) .dot { background: var(--color-leaf); } .stop:nth-child(6) .dot { background: var(--color-tangerine); }
  .stop h4 { margin: 14px 0 4px; font-size: 19px; letter-spacing: -.02em; }
  .stop .q { font-weight: 700; font-size: 13px; }
  .stop p { margin: 6px 0 0; font-size: 14px; line-height: 1.4; color: #555; font-weight: 500; }
  .map-foot { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 28px; padding-top: 20px; border-top: 2.5px solid var(--color-ink); }
  .map-foot .chip { background: var(--color-cream); }

  .report { display: grid; grid-template-columns: 1fr 1.1fr; gap: 30px; align-items: center; }
  .report ul { list-style: none; padding: 0; margin: 24px 0 0; display: grid; gap: 14px; }
  .report li { display: flex; gap: 14px; align-items: flex-start; font-size: 17px; line-height: 1.45; font-weight: 500; }
  .report li b { flex: none; width: 34px; height: 34px; border-radius: 10px; border: 2.5px solid var(--color-ink); display: grid; place-items: center; background: var(--color-sun); font-size: 16px; }
  .sheet { background: #fff; border: 3px solid var(--color-ink); border-radius: 28px; padding: 24px; box-shadow: 9px 9px 0 var(--color-ink); transform: rotate(1.5deg); }
  .sheet-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
  .sheet-top h4 { margin: 0; font-size: 22px; letter-spacing: -.03em; }
  .bands { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 18px; }
  .band { border: 2.5px solid var(--color-ink); border-radius: 999px; padding: 4px 11px; font-weight: 700; font-size: 13px; }
  .strong { background: var(--color-leaf); } .ok { background: var(--color-sun); } .weak { background: var(--color-bubblegum); }
  .qa { border: 2.5px solid var(--color-ink); border-radius: 18px; padding: 16px; background: var(--color-cream); }
  .qq { font-weight: 800; font-size: 16px; margin-bottom: 8px; }
  .qa-a { font-size: 14.5px; line-height: 1.45; color: #444; font-style: italic; margin-bottom: 12px; }
  .row { display: flex; gap: 8px; font-size: 14.5px; font-weight: 600; margin-top: 6px; line-height: 1.35; }
  .row i { font-style: normal; width: 22px; flex: none; }
  .heard { margin-top: 12px; font-size: 13px; font-weight: 600; background: #fff; border: 2px dashed var(--color-ink); border-radius: 12px; padding: 8px 10px; }
  .fix { margin-top: 12px; font-size: 14px; font-weight: 700; background: var(--color-sky); border: 2.5px solid var(--color-ink); border-radius: 12px; padding: 9px 12px; }

  .feats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 18px; }
  .feat { background: #fff; border: 3px solid var(--color-ink); border-radius: 24px; padding: 22px; box-shadow: 6px 6px 0 var(--color-ink); }
  .ic { width: 50px; height: 50px; border-radius: 14px; border: 2.5px solid var(--color-ink); display: grid; place-items: center; font-size: 24px; margin-bottom: 14px; }
  .feat h3 { margin: 0 0 8px; font-size: 21px; letter-spacing: -.02em; line-height: 1.1; }
  .feat p { margin: 0; font-size: 15px; line-height: 1.45; color: #444; font-weight: 500; }

  .faq { display: grid; gap: 14px; max-width: 860px; }
  details { background: #fff; border: 3px solid var(--color-ink); border-radius: 20px; box-shadow: 5px 5px 0 var(--color-ink); }
  summary { list-style: none; cursor: pointer; padding: 18px 22px; font-weight: 800; font-size: 20px; letter-spacing: -.02em; display: flex; justify-content: space-between; align-items: center; gap: 16px; }
  summary::-webkit-details-marker { display: none; }
  summary::after { content: "+"; width: 34px; height: 34px; flex: none; border-radius: 50%; border: 2.5px solid var(--color-ink); display: grid; place-items: center; font-size: 22px; background: var(--color-sun); transition: transform .25s; }
  details[open] summary::after { transform: rotate(45deg); background: var(--color-bubblegum); }
  details p { margin: 0; padding: 0 22px 20px; font-size: 16.5px; line-height: 1.5; color: #444; font-weight: 500; }

  .final { margin: 90px 0 40px; background: var(--color-sun); border: 3px solid var(--color-ink); border-radius: 36px; box-shadow: 10px 10px 0 var(--color-ink); padding: 56px; display: grid; grid-template-columns: 1.4fr 1fr; gap: 24px; align-items: center; overflow: hidden; }
  .final h2 { font-size: clamp(44px, 5.6vw, 78px); }
  .final p { font-size: 19px; font-weight: 500; margin: 18px 0 26px; max-width: 520px; }
  .final .btn { background: var(--color-ink); color: #fff; box-shadow: 6px 6px 0 #fff; }
  .final :global(.final-art) { width: 100%; height: 280px; }

  footer { padding: 26px 0 40px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; font-weight: 600; font-size: 14px; color: #555; }
  footer .links a { font-size: 14px; }

  @media (max-width: 980px) {
    .links { display: none; }
    footer .links { display: flex; }
    .report, .final { grid-template-columns: 1fr; }
    .steps { grid-template-columns: 1fr; }
    .step:nth-child(2), .step:nth-child(3) { transform: none; }
    .feats { grid-template-columns: 1fr 1fr; }
    .lane { grid-template-columns: repeat(3, 1fr); row-gap: 30px; }
    .lane::before { display: none; }
    .final { padding: 34px; }
  }
  @media (max-width: 560px) {
    .final { padding: 26px 22px; border-radius: 28px; }
    .final :global(.final-art) { height: 200px; }
    .map { padding: 22px 16px; }
    .sheet { padding: 18px; transform: none; }
    .feats { grid-template-columns: 1fr; }
    .lane { grid-template-columns: repeat(2, 1fr); }
  }
</style>
