<script lang="ts">
  import { tick } from 'svelte';
  import type { Card } from '$lib/cards';
  import type { ConvoMessage } from '$lib/convo';
  import type { ReportState } from '$lib/interview';
  import ProjectCard from '$lib/components/ProjectCard.svelte';
  import LinkCard from '$lib/components/LinkCard.svelte';
  import SkillsCard from '$lib/components/SkillsCard.svelte';
  import SkillCard from '$lib/components/SkillCard.svelte';
  import BookingCard from '$lib/components/BookingCard.svelte';
  import InterviewReport from '$lib/components/InterviewReport.svelte';

  // The scrolling conversation: messages, the words being heard right now, tool cards and the report.
  let {
    feed, partialText, thinking, cards, reportState, errorMsg, interviewing, interviewerName, onAction,
  }: {
    feed: ConvoMessage[]; partialText: string; thinking: boolean; cards: Card[]; reportState: ReportState | null;
    errorMsg: string; interviewing: boolean; interviewerName: string;
    onAction: (action: string, payload: Record<string, string>) => void;
  } = $props();

  let scroller: HTMLDivElement;
  const empty = $derived(feed.length === 0 && !partialText && !thinking && !cards.length && !reportState && !errorMsg);

  // follow new content, unless the visitor scrolled up to read (measured before the DOM grows)
  $effect.pre(() => {
    void [feed, partialText, thinking, cards, reportState];
    if (!scroller) return;
    const nearBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120;
    if (nearBottom) void tick().then(() => scroller.scrollTo({ top: scroller.scrollHeight }));
  });
</script>

<div class="feed" bind:this={scroller} aria-live="polite">
  {#if empty}
    <div class="empty">
      {#if interviewing}
        <div class="big">no script.<br /><span>just vibes</span><br />&amp; follow-ups.</div>
        <p>{interviewerName} reads your résumé, asks, listens, and digs into what you actually say.</p>
      {:else}
        <div class="big">ask me<br /><span>anything</span><br />about arjun.</div>
        <p>Projects, stack, internship. I only answer from his portfolio, and yes, I'm an AI. Say "book a call" to meet him.</p>
      {/if}
    </div>
  {/if}

  {#each feed as message (message.id)}
    <div class="row {message.who}">
      <div class="mini" aria-hidden="true"></div>
      <div class="msg"><span class="sr-only">{message.who === 'user' ? 'You:' : 'Agent:'}</span>{message.text}</div>
    </div>
  {/each}

  {#if partialText}
    <div class="row user">
      <div class="mini" aria-hidden="true"></div>
      <div class="msg partial">{partialText}</div>
    </div>
  {/if}

  {#if thinking}<div class="dots" aria-label="Thinking"><i></i><i></i><i></i></div>{/if}

  {#each cards as card (card.card_id)}
    <div class="card-slot">
      {#if card.type === 'project_detail'}
        <ProjectCard data={card.data} />
      {:else if card.type === 'link'}
        <LinkCard data={card.data} />
      {:else if card.type === 'skills'}
        <SkillsCard data={card.data} />
      {:else if card.type === 'skill'}
        <SkillCard data={card.data} />
      {:else}
        <BookingCard {card} {onAction} />
      {/if}
    </div>
  {/each}

  {#if reportState}<InterviewReport state={reportState} />{/if}

  {#if errorMsg}<div class="error panel" role="alert"><b>Something went wrong.</b> {errorMsg}</div>{/if}
</div>

<style>
  .feed { overflow-y: auto; min-height: 0; padding: 18px 8px 18px 2px; display: flex; flex-direction: column; gap: 14px; scrollbar-width: none; }
  .feed::-webkit-scrollbar { width: 0; }
  .empty { margin: auto; text-align: center; max-width: 300px; }
  .big { font-weight: 800; font-size: 46px; letter-spacing: -.05em; line-height: .95; }
  .big span { background: var(--color-sun); padding: 0 6px; border: 2.5px solid var(--color-ink); border-radius: 10px; display: inline-block; transform: rotate(-3deg); }
  .empty p { font-weight: 500; font-size: 15px; color: #555; margin-top: 14px; line-height: 1.45; }

  .row { display: flex; gap: 10px; align-items: flex-end; animation: boing .45s cubic-bezier(.3,1.7,.5,1); }
  .row.user { flex-direction: row-reverse; }
  @keyframes boing { from { opacity: 0; transform: scale(.85) translateY(10px); } }
  .mini { width: 34px; height: 34px; flex: none; border-radius: 45% 55% 50% 50%; border: 2.5px solid var(--color-ink); background: var(--c, var(--color-leaf)); position: relative; }
  .mini::before, .mini::after { content: ""; position: absolute; top: 11px; width: 5px; height: 6px; border-radius: 50%; background: var(--color-ink); }
  .mini::before { left: 9px; } .mini::after { right: 9px; }
  .row.user .mini { background: var(--color-sun); border-radius: 50%; }
  .msg { max-width: 78%; border: 3px solid var(--color-ink); border-radius: 20px; padding: 12px 16px; font-weight: 500; font-size: 16.5px; line-height: 1.42; background: #fff; box-shadow: 4px 4px 0 var(--color-ink); overflow-wrap: anywhere; }
  .row.agent .msg { border-bottom-left-radius: 6px; }
  .row.user .msg { background: var(--color-sun); border-bottom-right-radius: 6px; box-shadow: -4px 4px 0 var(--color-ink); }
  .msg.partial { opacity: .55; font-style: italic; }
  .dots { align-self: flex-start; display: flex; gap: 6px; margin-left: 44px; border: 3px solid var(--color-ink); border-radius: 18px; padding: 12px 16px; background: #fff; box-shadow: 4px 4px 0 var(--color-ink); }
  .dots i { width: 9px; height: 9px; border-radius: 50%; background: var(--color-ink); animation: hop 1s infinite; }
  .dots i:nth-child(2) { animation-delay: .15s; } .dots i:nth-child(3) { animation-delay: .3s; }
  @keyframes hop { 30% { transform: translateY(-6px); } }
  .error { padding: 12px 16px; background: #ffe0ec; font-size: 15px; }
</style>
