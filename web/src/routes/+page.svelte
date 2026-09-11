<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { startMic, stopMic } from '$lib/mic';
  import { initPlayback, appendChunk, signalDone, resetPlayback } from '$lib/playback';
  import { Mic, MicOff, Volume2, Loader } from '@lucide/svelte';

  // ── State ────────────────────────────────────────────────────────────────
  type Status = 'idle' | 'listening' | 'thinking' | 'speaking';

  let status = $state<Status>('idle');
  let partialText = $state('');
  let finalText = $state('');
  let assistantText = $state('');
  let errorMsg = $state('');
  let metrics = $state<{ ttfaMs?: number; ragMs?: number; geminiTtftMs?: number; totalMs?: number }>({});

  let ws: WebSocket | null = null;
  let audioEl: HTMLAudioElement;

  const WS_URL = 'ws://localhost:3001';

  // ── WebSocket ─────────────────────────────────────────────────────────────
  function connectWS() {
    ws = new WebSocket(WS_URL);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => { errorMsg = ''; };
    ws.onerror = () => { errorMsg = 'WebSocket error — is the server running on :3001?'; };
    ws.onclose = () => { if (status !== 'idle') status = 'idle'; };

    ws.onmessage = (ev) => {
      // Binary = MP3 audio frame [u32LE sentenceId][mp3 bytes]
      if (ev.data instanceof ArrayBuffer) {
        appendChunk(ev.data);
        if (status === 'thinking') status = 'speaking';
        return;
      }

      const msg = JSON.parse(ev.data as string);

      switch (msg.type) {
        case 'transcript_partial':
          partialText = msg.text;
          if (status === 'listening') status = 'thinking';
          break;

        case 'transcript_final':
          finalText = msg.text;
          partialText = '';
          break;

        case 'assistant_text':
          assistantText += msg.text;
          break;

        case 'metric':
          if (msg.stage === 'rag_complete') metrics.ragMs = msg.ragLatencyMs;
          if (msg.stage === 'gemini_first_token') metrics.geminiTtftMs = msg.ttftMs;
          break;

        case 'tts_end':
          if (msg.isFirst && msg.firstAudioLatencyMs) {
            metrics.ttfaMs = msg.firstAudioLatencyMs;
          }
          break;

        case 'done':
          metrics.totalMs = msg.totalMs;
          signalDone();
          status = 'idle';
          break;

        case 'error':
          errorMsg = msg.message;
          status = 'idle';
          break;
      }
    };
  }

  // ── Mic toggle ───────────────────────────────────────────────────────────
  async function toggleMic() {
    if (status === 'listening') {
      stopMic();
      status = 'idle';
      return;
    }

    // Reset state for new turn
    partialText = '';
    assistantText = '';
    errorMsg = '';
    metrics = {};
    resetPlayback(audioEl);

    try {
      status = 'listening';
      await startMic((pcm: ArrayBuffer) => {
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(pcm);
        }
      });
    } catch (e: any) {
      errorMsg = e.message || 'Mic access denied';
      status = 'idle';
    }
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────
  onMount(() => {
    initPlayback(audioEl);
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
    aria-label={status === 'listening' ? 'Stop listening' : 'Start listening'}
  >
    {#if status === 'listening'}
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
          {#if metrics.geminiTtftMs !== undefined}
            {@render Metric({ label: 'LLM TTFT', value: `${metrics.geminiTtftMs}ms` })}
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
