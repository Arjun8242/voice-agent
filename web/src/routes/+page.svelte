<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { startMic, stopMic } from '$lib/mic';
  import { initPlayback, appendChunk, signalDone, resetPlayback, markSentenceDone, currentSentenceId } from '$lib/playback';
  import { KEEP_ACROSS_TURNS, type Card } from '$lib/cards';
  import ProjectCard from '$lib/components/ProjectCard.svelte';
  import LinkCard from '$lib/components/LinkCard.svelte';
  import BookingCard from '$lib/components/BookingCard.svelte';
  import Mic from '@lucide/svelte/icons/mic';
  import MicOff from '@lucide/svelte/icons/mic-off';
  import Volume2 from '@lucide/svelte/icons/volume-2';
  import Loader from '@lucide/svelte/icons/loader';

  // ── State ────────────────────────────────────────────────────────────────
  type Status = 'idle' | 'listening' | 'thinking' | 'speaking';

  let status = $state<Status>('idle');
  let partialText = $state('');
  let finalText = $state('');
  let assistantText = $state('');
  let cards = $state<Card[]>([]);
  // Turns up to this id were interrupted; the server tags every message of a turn with turnId.
  let cancelledTurn = 0;
  // Turn whose answer the server has finished sending; its audio may still be playing here.
  let doneTurn = 0;
  let errorMsg = $state('');
  let metrics = $state<{ ttfaMs?: number; ragMs?: number; llmTtftMs?: number; totalMs?: number }>({});

  let ws: WebSocket | null = null;
  let audioEl: HTMLAudioElement;
  let micActive = $state(false);

  const WS_URL = 'ws://localhost:3001';

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
    assistantText = '';
    status = 'thinking';
    ws.send(JSON.stringify({ type: 'ui_action', action, payload }));
  }

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
    ws.onerror = () => { errorMsg = 'WebSocket error — is the server running on :3001?'; };
    ws.onclose = () => {
      stopMic();
      micActive = false;
      status = 'idle';
    };

    ws.onmessage = (ev) => {
      // Binary = MP3 audio frame [u32LE sentenceId][mp3 bytes]
      if (ev.data instanceof ArrayBuffer) {
        appendChunk(ev.data);
        if (status === 'thinking') status = 'speaking';
        return;
      }

      const msg = JSON.parse(ev.data as string);

      // A cancelled turn's text or card must never show up late.
      if (msg.turnId !== undefined && msg.turnId <= cancelledTurn) return;

      switch (msg.type) {
        case 'session':
          sessionStorage.setItem('sessionId', msg.sessionId);
          break;

        case 'transcript_partial':
          partialText = msg.text;
          break;

        case 'transcript_final':
          finalText = msg.text;
          partialText = '';
          assistantText = "";
          cards = cards.filter((c) => KEEP_ACROSS_TURNS.has(c.type));
          resetPlayback(audioEl);
          status = 'thinking';
          break;

        case 'assistant_text':
          assistantText += msg.text;
          break;

        case 'ui_card':
          // Same card_id replaces the earlier card instead of showing it twice.
          placeCard(msg.card);
          break;

        case 'booking_update':
          // The calendar call's result. It has no turnId, so it arrives even if the turn was cut off.
          placeCard({ ...msg.card, data: { ...msg.card.data, text: msg.text } });
          break;

        case 'metric':
          if (msg.stage === 'rag_complete') metrics.ragMs = msg.ragLatencyMs;
          if (msg.stage === 'llm_first_token') metrics.llmTtftMs = msg.ttftMs;
          break;

        case 'tts_end':
          if (msg.isFirst && msg.firstAudioLatencyMs) {
            metrics.ttfaMs = msg.firstAudioLatencyMs;
          }
          markSentenceDone(msg.sentenceId);
          break;

        case 'done':
          metrics.totalMs = msg.totalMs;
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
          assistantText = '';
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

    // Reset state for new conversation session
    partialText = '';
    finalText = '';
    assistantText = '';
    cards = [];
    errorMsg = '';
    metrics = {};
    resetPlayback(audioEl);

    micActive = true;
    try {
      status = 'listening';
      await startMic((pcm: ArrayBuffer) => {
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(pcm);
        }
      });
      // Stopped while the permission prompt / worklet was still loading.
      if (!micActive) stopMic();
    } catch (e: any) {
      if (!micActive) return;
      micActive = false;
      errorMsg = e.message || 'Mic access denied';
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

  // ── Helpers ───────────────────────────────────────────────────────────────
  const statusLabel: Record<Status, string> = {
    idle: 'Idle',
    listening: 'Listening…',
    thinking: 'Processing…',
    speaking: 'Speaking…',
  };

  const statusColor: Record<Status, string> = {
    idle: 'bg-gray-700 text-gray-300',
    listening: 'bg-red-500/20 text-red-400 ring-1 ring-red-500/40',
    thinking: 'bg-blue-500/20 text-blue-400 ring-1 ring-blue-500/40',
    speaking: 'bg-emerald-500/20 text-emerald-400 ring-1 ring-emerald-500/40',
  };
</script>

<svelte:head>
  <title>Acme Voice AI</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet" />
</svelte:head>

<!-- Hidden audio element for MSE playback -->
<audio bind:this={audioEl} autoplay class="hidden"></audio>

<main class="min-h-screen bg-[hsl(222,47%,11%)] text-[hsl(210,40%,98%)] flex flex-col items-center justify-center p-6 gap-6">

  <!-- Header -->
  <div class="text-center">
    <h1 class="text-3xl font-semibold tracking-tight">Acme Voice AI</h1>
    <p class="text-sm text-[hsl(215,20%,55%)] mt-1">Low-latency RAG voice assistant</p>
  </div>

  <!-- Status badge -->
  <span class="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium transition-colors duration-200 {statusColor[status]}">
    {#if status === 'listening'}
      <span class="size-2 rounded-full bg-red-400 animate-pulse"></span>
    {:else if status === 'thinking'}
      <Loader size={12} class="animate-spin" />
    {:else if status === 'speaking'}
      <Volume2 size={12} />
    {:else}
      <span class="size-2 rounded-full bg-gray-500"></span>
    {/if}
    {statusLabel[status]}
  </span>

  <!-- Mic button -->
  <button
    onclick={toggleMic}
    class="relative flex items-center justify-center size-20 rounded-full transition-all duration-200 shadow-lg
      {status === 'listening'
        ? 'bg-red-500 hover:bg-red-600 shadow-red-500/30'
        : 'bg-[hsl(199,89%,48%)] hover:bg-[hsl(199,89%,42%)] shadow-[hsl(199,89%,48%)]/30'
      }"
    aria-label={micActive ? 'Stop listening' : 'Start listening'}
  >
    {#if micActive}
      <MicOff size={32} class="text-white" />
    {:else}
      <Mic size={32} class="text-white" />
    {/if}
    {#if status === 'listening'}
      <span class="absolute inset-0 rounded-full bg-red-500 animate-ping opacity-20"></span>
    {/if}
  </button>

  <!-- Cards -->
  <div class="w-full max-w-2xl flex flex-col gap-4">

    <!-- Partial transcript -->
    {#if partialText}
      <div class="rounded-xl bg-[hsl(222,47%,14%)] border border-[hsl(217,33%,22%)] p-4">
        <p class="text-xs font-medium text-[hsl(215,20%,55%)] mb-1 uppercase tracking-wider">Partial</p>
        <p class="text-sm text-[hsl(215,20%,75%)] italic">{partialText}</p>
      </div>
    {/if}

    <!-- Final transcript -->
    {#if finalText}
      <div class="rounded-xl bg-[hsl(222,47%,14%)] border border-[hsl(217,33%,22%)] p-4">
        <p class="text-xs font-medium text-[hsl(215,20%,55%)] mb-1 uppercase tracking-wider">You said</p>
        <p class="text-sm">{finalText}</p>
      </div>
    {/if}

    <!-- Assistant response -->
    {#if assistantText}
      <div class="rounded-xl bg-[hsl(222,47%,14%)] border border-[hsl(199,89%,48%)]/30 p-4">
        <p class="text-xs font-medium text-[hsl(199,89%,48%)] mb-1 uppercase tracking-wider">Assistant</p>
        <p class="text-sm leading-relaxed">{assistantText}</p>
      </div>
    {/if}

    <!-- Cards from tools (project detail, links) and booking -->
    {#each cards as card (card.card_id)}
      {#if card.type === 'project_detail'}
        <ProjectCard data={card.data} />
      {:else if card.type === 'link'}
        <LinkCard data={card.data} />
      {:else}
        <BookingCard {card} onAction={sendAction} />
      {/if}
    {/each}

    <!-- Error -->
    {#if errorMsg}
      <div class="rounded-xl bg-red-500/10 border border-red-500/30 p-4">
        <p class="text-xs font-medium text-red-400 mb-1 uppercase tracking-wider">Error</p>
        <p class="text-sm text-red-300">{errorMsg}</p>
      </div>
    {/if}

    <!-- Metrics -->
    {#if metrics.ttfaMs !== undefined || metrics.ragMs !== undefined}
      <div class="rounded-xl bg-[hsl(222,47%,14%)] border border-[hsl(217,33%,22%)] p-4">
        <p class="text-xs font-medium text-[hsl(215,20%,55%)] mb-3 uppercase tracking-wider">Latency</p>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {#if metrics.ragMs !== undefined}
            {@render Metric({ label: 'RAG', value: `${metrics.ragMs}ms` })}
          {/if}
          {#if metrics.llmTtftMs !== undefined}
            {@render Metric({ label: 'LLM TTFT', value: `${metrics.llmTtftMs}ms` })}
          {/if}
          {#if metrics.ttfaMs !== undefined}
            {@render Metric({ label: 'First Audio', value: `${metrics.ttfaMs}ms`, highlight: true })}
          {/if}
          {#if metrics.totalMs !== undefined}
            {@render Metric({ label: 'Total', value: `${metrics.totalMs}ms` })}
          {/if}
        </div>
      </div>
    {/if}

  </div>

</main>

<!-- Inline sub-component for metric tiles -->
{#snippet Metric({ label, value, highlight = false }: { label: string; value: string; highlight?: boolean })}
  <div class="flex flex-col items-center rounded-lg bg-[hsl(217,33%,17%)] p-3 gap-1">
    <span class="text-[10px] font-medium text-[hsl(215,20%,55%)] uppercase tracking-wider">{label}</span>
    <span class="text-base font-semibold {highlight ? 'text-[hsl(199,89%,48%)]' : ''}">{value}</span>
  </div>
{/snippet}
