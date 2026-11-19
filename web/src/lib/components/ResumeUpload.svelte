<script lang="ts">
  import { MAX_JD_CHARS, uploadResume, type PlanPreview } from '$lib/upload';

  // The interview is planned from this upload; Start stays off until the server has a plan (onready).
  let {
    sessionId,
    disabled,
    onready,
  }: { sessionId: string; disabled: boolean; onready: (plan: PlanPreview) => void } = $props();

  let file = $state<File | null>(null);
  let jobDescription = $state('');
  let busy = $state(false);
  let error = $state('');
  let plan = $state<PlanPreview | null>(null);

  async function analyse() {
    if (!file || !sessionId) return;
    busy = true;
    error = '';
    const outcome = await uploadResume(sessionId, file, jobDescription);
    busy = false;
    if (!outcome.ok) {
      error = outcome.message;
      return;
    }
    plan = outcome.plan;
    onready(outcome.plan);
  }
</script>

<div class="upload">
  {#if plan}
    <p class="note ready" role="status">
      ✓ {plan.preview}
      {#if plan.fallback}<span> We could not read every detail, so the questions are about your resume in general.</span>{/if}
    </p>
  {:else if busy}
    <p class="note" role="status">Analysing your resume against the role…</p>
  {:else if error}
    <p class="note bad" role="alert">{error}</p>
  {/if}

  <label class="cta" class:off={disabled || busy}>
    <input
      type="file"
      accept=".pdf,application/pdf"
      class="sr-only"
      disabled={disabled || busy}
      onchange={(e) => { file = e.currentTarget.files?.[0] ?? null; plan = null; error = ''; }}
    />
    {file ? `📄 ${file.name}` : 'upload résumé ✦'}
  </label>

  {#if file}
    <details class="jd">
      <summary>add a job description (optional)</summary>
      <textarea
        bind:value={jobDescription}
        maxlength={MAX_JD_CHARS}
        rows="4"
        disabled={disabled || busy}
        placeholder="Paste the job description to practise for that role."
        class="field"
      ></textarea>
    </details>
    <button class="btn btn-sm analyse" onclick={analyse} disabled={!sessionId || disabled || busy}>
      {plan ? 'analyse again' : 'analyse résumé →'}
    </button>
  {:else}
    <p class="hint">pdf only · job description optional · deleted after</p>
  {/if}
</div>

<style>
  .upload { display: flex; flex-direction: column; gap: 10px; }
  .cta { display: block; text-align: center; border: 3px solid var(--color-ink); background: var(--color-ink); color: #fff; border-radius: 18px; padding: 17px; font-weight: 800; font-size: 19px; box-shadow: 6px 6px 0 var(--c, var(--color-leaf)); cursor: pointer; transition: transform .1s, box-shadow .1s; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cta:active { transform: translate(4px, 4px); box-shadow: 2px 2px 0 var(--c, var(--color-leaf)); }
  .cta:focus-within { outline: 3px solid var(--color-sky); outline-offset: 3px; }
  .cta.off { opacity: .5; cursor: not-allowed; }
  .hint { text-align: center; font-weight: 600; font-size: 12px; color: #666; margin: 0; }
  .note { margin: 0; font-weight: 600; font-size: 14px; border: 2.5px solid var(--color-ink); border-radius: 14px; padding: 8px 12px; background: var(--color-cream); }
  .note.ready { background: #dff7d6; }
  .note.bad { background: #ffe0ec; }
  .jd summary { cursor: pointer; font-weight: 700; font-size: 14px; }
  .jd textarea { margin-top: 8px; resize: vertical; }
  .analyse { align-self: center; }
</style>
