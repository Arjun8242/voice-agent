<script lang="ts">
  import { STAGE_NAMES, type Band, type ReportState } from '$lib/interview';

  // Covered and missed points are the framework's own words, picked by the server (interview/report.py).
  let { state }: { state: ReportState } = $props();

  const BAND_TONE: Record<Band, string> = {
    strong: 'bg-leaf border-2 border-ink',
    ok: 'bg-sun border-2 border-ink',
    weak: 'bg-red-500/20 text-red-700',
  };
</script>

{#snippet band(value: Band)}
  <span class="rounded-full px-2 py-0.5 text-xs font-medium {BAND_TONE[value]}">{value}</span>
{/snippet}

{#snippet list(title: string, items: string[], mark: string)}
  {#if items.length}
    <div>
      <h4 class="text-xs font-medium uppercase tracking-wider text-neutral-600 mb-1">{title}</h4>
      <ul class="flex flex-col gap-1 text-sm">
        {#each items as item, i (i)}
          <li><span aria-hidden="true">{mark}</span> {item}</li>
        {/each}
      </ul>
    </div>
  {/if}
{/snippet}

<section aria-labelledby="report-title" class="panel p-4 flex flex-col gap-4">
  <h2 id="report-title" class="text-lg font-semibold">Interview report</h2>

  {#if state.status === 'pending'}
    <p class="text-sm text-neutral-600" role="status">Preparing your report…</p>
  {:else if state.status === 'failed'}
    <p class="text-sm text-red-700" role="alert">The report could not be written this time. Your answers were not lost, but they were not reviewed.</p>
  {:else if state.report.reviews.length === 0}
    <p class="text-sm text-neutral-600">No answers were recorded, so there is nothing to review.</p>
  {:else}
    <ul class="flex flex-wrap gap-2" aria-label="Band per stage">
      {#each state.report.stages as stage (stage.kind)}
        <li class="flex items-center gap-2 text-sm">{STAGE_NAMES[stage.kind] ?? stage.kind} {@render band(stage.band)}</li>
      {/each}
    </ul>

    {@render list('Strengths', state.report.strengths, '✓')}
    {@render list('To work on', state.report.improvements, '→')}
    {@render list('Job requirements your resume did not show, asked about', state.report.gaps_touched, '!')}

    {#each state.report.reviews as review, i (i)}
      <article class="rounded-lg border-2 border-ink p-3 flex flex-col gap-3">
        <header class="flex items-center justify-between gap-2">
          <h3 class="text-sm font-medium">
            {i + 1}. {review.topic}
            <span class="text-xs text-neutral-600">· {STAGE_NAMES[review.kind] ?? review.kind}</span>
            {#if review.gap}<span class="ml-1 rounded px-1.5 py-0.5 text-xs bg-tangerine border border-ink">JD gap</span>{/if}
          </h3>
          {@render band(review.band)}
        </header>
        <p class="text-sm text-neutral-600"><span class="text-neutral-600">Q:</span> {review.question}</p>
        <p class="text-sm text-neutral-600"><span class="text-neutral-600">You:</span> {review.answer}</p>

        {@render list('Covered', review.covered, '✓')}
        {@render list('Missed', review.missed, '•')}
        {#if review.improvement}
          <p class="text-sm"><span class="text-neutral-600">Next time:</span> {review.improvement}</p>
        {/if}

        {#if review.corrected.length || review.read_by_meaning.length}
          <p class="text-xs text-neutral-600">
            Heard by speech recognition, not counted against you:
            {#each [...review.corrected, ...review.read_by_meaning] as term, j (j)}
              <span>{j ? '; ' : ''}heard “{term.heard}”, read as {term.read_as}</span>
            {/each}
          </p>
        {/if}

        {#if review.framework.key_points.length}
          <details class="text-sm">
            <summary class="cursor-pointer text-neutral-600">How to answer this question</summary>
            <div class="mt-2 flex flex-col gap-2">
              {@render list('A strong answer covers', review.framework.key_points, '•')}
              {@render list('Red flags', review.framework.red_flags, '✗')}
              {@render list('Likely follow-ups', review.framework.likely_followups, '?')}
            </div>
          </details>
        {/if}
      </article>
    {/each}
  {/if}
</section>
