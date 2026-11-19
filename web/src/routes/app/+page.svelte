<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { startMic, stopMic } from '$lib/mic';
  import { initPlayback, appendChunk, signalDone, resetPlayback, markSentenceDone, currentSentenceId } from '$lib/playback';
  import { KEEP_ACROSS_TURNS, type Card } from '$lib/cards';
  import { addAgentText, addVisitorWords, dropTurn, type ConvoMessage } from '$lib/convo';
  import { CHARACTERS } from '$lib/characters';
  import TopBar from '$lib/components/talk/TopBar.svelte';
  import StagePanel from '$lib/components/talk/StagePanel.svelte';
  import ConvoFeed from '$lib/components/talk/ConvoFeed.svelte';
  import ResumeUpload from '$lib/components/ResumeUpload.svelte';
  import {
    INTERVIEW_LIMIT_SECONDS, PERSONAS, endInterviewMessage, reportStateFrom, startInterviewMessage,
    type Mode, type PersonaName, type ReportState,
  } from '$lib/interview';
  import type { Phase } from '$lib/motion';

  // The talk screen (docs/viva-design-blobs.html): the character on the left, the conversation on the right.
  // This file owns the WebSocket and the mic; the components only draw what it passes them.

  // ── State ────────────────────────────────────────────────────────────────
  type Status = 'idle' | 'listening' | 'thinking' | 'speaking';

  let status = $state<Status>('idle');
  // Whether the server is still waiting for the visitor to finish (sent as turn_state, never tied to a turn).
  let turnState = $state<'speaking' | 'holding' | 'thinking' | 'idle'>('idle');
  let partialText = $state('');
  let feed = $state<ConvoMessage[]>([]);
  let cards = $state<Card[]>([]);
  // Turns up to this id were interrupted; the server tags every message of a turn with turnId.
  let cancelledTurn = 0;
  // Turn whose answer the server has finished sending; its audio may still be playing here.
  let doneTurn = 0;
  let errorMsg = $state('');
  let firstAudioMs = $state<number | null>(null);

  let ws: WebSocket | null = null;
  let audioEl: HTMLAudioElement;
  let micActive = $state(false);
  let mode = $state<Mode>('interview');
  let persona = $state<PersonaName>('neutral');
  let interviewStarted = $state(false);
  let interviewEnded = $state(false);
  let reportState = $state<ReportState | null>(null);
  let sessionId = $state(''); // from the server's session message; the resume upload is filed under it
  let planReady = $state(false);
  let liveStage = $state<string | null>(null); // from interview_stage, sent after each interview turn
  let startedAt = 0;
  let elapsed = $state(0);

  const WS_URL = 'ws://localhost:3001';

  const character = $derived(mode === 'interview' ? (PERSONAS.find((p) => p.name === persona) ?? PERSONAS[0]).character : 'rep');
  const look = $derived(CHARACTERS[character]);
  const phase = $derived<Phase>(status);
  const live = $derived(micActive || (interviewStarted && !interviewEnded));

  // A newer card for the same booking replaces the older ones (form -> summary -> outcome),
  // and picking a slot retires the slots list.
  function placeCard(card: Card) {
    const bookingId = 'booking_id' in card.data ? card.data.booking_id : null;
    cards = [
      ...cards.filter((c) =>
        c.card_id !== card.card_id
        && !(bookingId && 'booking_id' in c.data && c.data.booking_id === bookingId)
        && !(card.type === 'booking_form' && c.type === 'slots')),
      card,
    ];
  }

  // A click on a booking card runs as a turn of its own on the server (graph booking_gate).
  function sendAction(action: string, payload: Record<string, string>) {
    if (ws?.readyState !== WebSocket.OPEN) return;
    status = 'thinking';
    ws.send(JSON.stringify({ type: 'ui_action', action, payload }));
  }

  // ── Interview mode ────────────────────────────────────────────────────────
  // Start is a click, so the browser lets the interviewer's opening question play.
  function startInterview() {
    if (ws?.readyState !== WebSocket.OPEN) return;
    // toggleMic resets playback before its first await; the server gets start_interview before any audio,
    // so its STT opens with the interview's longer silence.
    if (!micActive) void toggleMic();
    ws.send(startInterviewMessage(persona));
    interviewStarted = true;
    startedAt = performance.now();
    status = 'thinking';
  }

  function endInterview() {
    if (ws?.readyState !== WebSocket.OPEN) return;
    ws.send(endInterviewMessage());
    if (micActive) void toggleMic(); // the mic stops; the closing line still plays
    interviewEnded = true;
    // the finished interview stays on this session id: forgetting it lets a reload start a new interview
    sessionStorage.removeItem('sessionId');
  }

  // the timer ticks only while an interview runs
  $effect(() => {
    if (!interviewStarted || interviewEnded) return;
    const timer = setInterval(() => { elapsed = (performance.now() - startedAt) / 1000; }, 1000);
    return () => clearInterval(timer);
  });

  // ── WebSocket ─────────────────────────────────────────────────────────────
  function connectWS() {
    ws = new WebSocket(WS_URL);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
      errorMsg = '';
      // First message of every page load: resend the id kept from before (empty on a first visit).
      ws?.send(JSON.stringify({
        type: 'session_start',
        sessionId: sessionStorage.getItem('sessionId') ?? '',
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      }));
    };
    ws.onerror = () => { errorMsg = 'Could not reach the voice server. Is it running on :3001?'; };
    ws.onclose = () => {
      stopMic();
      micActive = false;
      status = 'idle';
    };

    ws.onmessage = (ev) => {
      // Binary = MP3 audio frame [u32LE sentenceId][mp3 bytes]
      if (ev.data instanceof ArrayBuffer) {
        // a late frame of a cut-off answer is dropped and must not flip the character to speaking
        if (appendChunk(ev.data) && status === 'thinking') status = 'speaking';
        return;
      }

      const msg = JSON.parse(ev.data as string);

      // A cancelled turn's text or card must never show up late.
      if (msg.turnId !== undefined && msg.turnId <= cancelledTurn) return;

      switch (msg.type) {
        case 'session':
          sessionStorage.setItem('sessionId', msg.sessionId);
          sessionId = msg.sessionId;
          break;

        case 'transcript_partial':
          partialText = msg.text;
          break;

        case 'interview_report':
          // No turnId: it arrives whenever the evaluator finishes, after the interview's last turn.
          reportState = reportStateFrom(msg.status, msg.report) ?? reportState;
          // the interview is over however it ended (End, time cap, last question): the server stopped listening
          if (micActive) void toggleMic();
          interviewEnded = true;
          sessionStorage.removeItem('sessionId');
          break;

        case 'interview_stage':
          liveStage = msg.stage;
          break;

        case 'turn_state':
          turnState = msg.state;
          break;

        case 'transcript_final':
          feed = addVisitorWords(feed, msg.text);
          partialText = '';
          cards = cards.filter((c) => KEEP_ACROSS_TURNS.has(c.type));
          resetPlayback(audioEl);
          status = 'thinking';
          break;

        case 'assistant_text':
          feed = addAgentText(feed, msg.turnId ?? null, msg.text);
          break;

        case 'ui_card':
          // Same card_id replaces the earlier card instead of showing it twice.
          placeCard(msg.card);
          break;

        case 'booking_update':
          // The calendar call's result. It has no turnId, so it arrives even if the turn was cut off.
          placeCard({ ...msg.card, data: { ...msg.card.data, text: msg.text } });
          break;

        case 'tts_end':
          if (msg.isFirst && msg.firstAudioLatencyMs) firstAudioMs = msg.firstAudioLatencyMs;
          markSentenceDone(msg.sentenceId);
          break;

        case 'done':
          doneTurn = msg.turnId;
          signalDone();
          // Only return to listening if the mic is still on.
          status = micActive ? 'listening' : 'idle';
          break;

        case 'interrupted':
          // Server superseded current turn due to barge-in
          if (msg.turnId > cancelledTurn) cancelledTurn = msg.turnId;
          // Tell the server which sentence was playing, so it keeps only what the visitor heard.
          ws?.send(JSON.stringify({ type: 'playback_progress', turnId: msg.turnId, lastSentenceId: currentSentenceId() }));
          resetPlayback(audioEl);
          feed = dropTurn(feed, msg.turnId);
          status = micActive ? 'listening' : 'idle';
          break;

        case 'error':
          errorMsg = msg.message;
          micActive = false;
          stopMic();
          status = 'idle';
          break;
      }
    };
  }

  // ── Mic toggle ───────────────────────────────────────────────────────────
  async function toggleMic() {
    if (micActive) {
      stopMic();
      micActive = false;
      status = 'idle';
      return;
    }

    partialText = '';
    errorMsg = '';
    resetPlayback(audioEl);

    micActive = true;
    try {
      status = 'listening';
      await startMic((pcm: ArrayBuffer) => {
        if (ws?.readyState === WebSocket.OPEN) ws.send(pcm);
      });
      // Stopped while the permission prompt / worklet was still loading.
      if (!micActive) stopMic();
    } catch (e: unknown) {
      if (!micActive) return;
      micActive = false;
      errorMsg = e instanceof Error ? e.message : 'Mic access denied';
      status = 'idle';
    }
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────
  onMount(() => {
    initPlayback(audioEl);
    // The answer's audio finished: tell the server, so speech from now on is a new question, not a barge-in.
    audioEl.addEventListener('ended', () => {
      if (doneTurn && ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'playback_ended', turnId: doneTurn }));
      }
    });
    connectWS();
  });

  onDestroy(() => {
    stopMic();
    ws?.close();
  });
</script>

<svelte:head>
  <title>viva! — meet your interviewer</title>
</svelte:head>

<!-- Hidden audio element for MSE playback -->
<audio bind:this={audioEl} autoplay class="hidden"></audio>

<div class="page">
  <div class="shell" style="--c: {look.color}; --c-soft: {look.soft}">
    <TopBar bind:mode locked={live || interviewStarted} {live} />

    <main class="main">
      <StagePanel
        {mode}
        bind:persona
        {phase}
        visitorSpeaking={turnState === 'speaking' || partialText !== ''}
        holding={turnState === 'holding' || turnState === 'thinking'}
        {liveStage}
        started={interviewStarted}
        ended={interviewEnded}
        micOn={micActive}
        {planReady}
        {elapsed}
        limit={INTERVIEW_LIMIT_SECONDS}
        onstart={startInterview}
        onend={endInterview}
        ontogglemic={toggleMic}
      />

      <section class="chat">
        <div class="chat-head">
          <h2>the convo</h2>
          <div class="chips">
            {#if firstAudioMs !== null}<span class="ct" title="Time to the first audio of the last answer">{firstAudioMs} ms</span>{/if}
            <span class="ct">{feed.length} msgs</span>
          </div>
        </div>

        <ConvoFeed
          {feed}
          {partialText}
          thinking={status === 'thinking'}
          {cards}
          {reportState}
          {errorMsg}
          interviewing={mode === 'interview'}
          interviewerName={look.name}
          onAction={sendAction}
        />

        {#if mode === 'interview' && !interviewStarted}
          <ResumeUpload {sessionId} disabled={interviewStarted} onready={() => (planReady = true)} />
        {:else if mode === 'interview' && !interviewEnded}
          <button class="cta" onclick={endInterview}>end &amp; get my feedback ✦</button>
          <p class="cta-note">feedback on every answer, not a vibe check</p>
        {:else if mode === 'recruiter'}
          <p class="cta-note">say "book a call" to meet Arjun · 15-min screening or 30-min technical</p>
        {/if}
      </section>
    </main>
  </div>
</div>

<style>
  .page { min-height: 100vh; display: grid; place-items: center; padding: 22px; }
  .shell { width: min(1220px, 100%); height: min(800px, calc(100vh - 44px)); min-height: 680px; background: #fff; border: 3px solid var(--color-ink); border-radius: 34px; box-shadow: 10px 10px 0 var(--color-ink); display: grid; grid-template-rows: auto 1fr; grid-template-columns: minmax(0, 1fr); overflow: hidden; }
  /* minmax(0, …): a long file name or word must wrap or ellipsize, never widen a column past the screen */
  .main { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr); min-height: 0; }
  .chat { display: grid; grid-template-rows: auto 1fr auto; grid-template-columns: minmax(0, 1fr); min-height: 0; padding: 18px 24px 22px; background: #fff; }
  .chat-head { display: flex; justify-content: space-between; align-items: center; }
  .chat-head h2 { margin: 0; font-weight: 800; font-size: 24px; letter-spacing: -.03em; }
  .chips { display: flex; gap: 6px; }
  .ct { font-weight: 700; font-size: 13px; background: var(--color-sky); border: 2px solid var(--color-ink); border-radius: 999px; padding: 3px 10px; }
  .cta { width: 100%; border: 3px solid var(--color-ink); background: var(--color-ink); color: #fff; border-radius: 18px; padding: 17px; font-weight: 800; font-size: 19px; box-shadow: 6px 6px 0 var(--c); transition: transform .1s, box-shadow .1s; }
  .cta:active { transform: translate(4px, 4px); box-shadow: 2px 2px 0 var(--c); }
  .cta-note { text-align: center; font-weight: 600; font-size: 12px; color: #666; margin: 10px 0 0; }

  @media (max-width: 980px) {
    .page { padding: 12px; }
    .shell { height: auto; min-height: 0; border-radius: 24px; }
    .main { grid-template-columns: minmax(0, 1fr); }
    .chat { min-height: 520px; }
  }
</style>
