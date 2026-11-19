<script lang="ts">
  import { onMount } from 'svelte';
  import { characterSvg, type CharacterKey } from '$lib/characters';
  import { blinkAmount, ease, lookToward, nextBlink, targetLevel, type Phase } from '$lib/motion';

  // One animated character. The loop runs only while it is on screen and the tab is visible, and not at all
  // for visitors who asked for reduced motion, so a page with several characters stays light.
  let {
    kind,
    phase = 'idle',
    visitorSpeaking = false,
    followPointer = false,
    seed = 0,
    class: className = '',
  }: {
    kind: CharacterKey;
    phase?: Phase;
    visitorSpeaking?: boolean;
    followPointer?: boolean;
    seed?: number;
    class?: string;
  } = $props();

  let svg: SVGSVGElement;
  const uid = `ch${Math.random().toString(36).slice(2, 8)}`;
  const markup = $derived(characterSvg(kind, uid));

  type Parts = { body: Element; pupils: Element; smile: Element; open: Element; mo: Element; ears: Element; think: Element; lids: Element[] };
  let parts: Parts | null = null;

  function findParts(): Parts | null {
    const pick = (name: string) => svg.querySelector(`.${name}`);
    const [body, pupils, smile, open, mo, ears, think] = ['body', 'pupils', 'smile', 'open', 'mo', 'ears', 'think'].map(pick);
    if (!body || !pupils || !smile || !open || !mo || !ears || !think) return null;
    return { body, pupils, smile, open, mo, ears, think, lids: [...svg.querySelectorAll('.lids rect')] };
  }

  // the markup is replaced when the character changes: look the parts up again
  $effect(() => {
    void markup;
    parts = svg ? findParts() : null;
  });

  let level = 0;
  let blinkStart = -1000;
  let blinkAt = nextBlink(0);
  let gaze = { x: 0, y: 0 };

  function draw(now: number, p: Parts) {
    level = ease(level, targetLevel(phase, now, visitorSpeaking, seed));
    const squash = phase === 'speaking' ? level * 0.05 : 0;
    const lift = phase === 'speaking' ? -level * 6 : 0;
    p.body.setAttribute('transform', `translate(150 262) scale(${1 + squash} ${1 - squash}) translate(-150 -262) translate(0 ${lift})`);
    const mouthOpen = phase === 'speaking' && level > 0.08;
    p.open.setAttribute('opacity', mouthOpen ? '1' : '0');
    p.smile.setAttribute('opacity', mouthOpen ? '0' : '1');
    p.mo.setAttribute('ry', String(4 + level * 20));
    p.mo.setAttribute('rx', String(16 + level * 6));
    const look = followPointer ? gaze : { x: phase === 'listening' ? 6 : 0, y: phase === 'thinking' ? -8 : phase === 'listening' ? 2 : 0 };
    p.pupils.setAttribute('transform', `translate(${look.x} ${look.y})`);
    p.ears.setAttribute('opacity', phase === 'listening' ? String(Math.min(1, 0.15 + level * 1.6)) : '0');
    p.think.setAttribute('opacity', phase === 'thinking' ? '1' : '0');
    if (now > blinkAt) { blinkStart = now; blinkAt = nextBlink(now); }
    const lidHeight = String(50 * blinkAmount(now, blinkStart));
    for (const lid of p.lids) lid.setAttribute('height', lidHeight);
  }

  onMount(() => {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    let frame = 0;
    let onScreen = false;
    const tick = (now: number) => {
      if (parts) draw(now, parts);
      frame = requestAnimationFrame(tick);
    };
    const run = () => {
      cancelAnimationFrame(frame);
      if (onScreen && !document.hidden) frame = requestAnimationFrame(tick);
    };
    const watcher = new IntersectionObserver(([entry]) => { onScreen = entry.isIntersecting; run(); });
    watcher.observe(svg);
    document.addEventListener('visibilitychange', run);

    // the box is read on pointer moves only, never in the frame loop
    const onPointer = (e: PointerEvent) => {
      const box = svg.getBoundingClientRect();
      gaze = lookToward(e.clientX - (box.left + box.width / 2), e.clientY - (box.top + box.height * 0.45));
    };
    if (followPointer) addEventListener('pointermove', onPointer, { passive: true });

    return () => {
      cancelAnimationFrame(frame);
      watcher.disconnect();
      document.removeEventListener('visibilitychange', run);
      removeEventListener('pointermove', onPointer);
    };
  });
</script>

<svg bind:this={svg} class={className} viewBox="0 0 300 300" aria-hidden="true" style="overflow: visible">{@html markup}</svg>
