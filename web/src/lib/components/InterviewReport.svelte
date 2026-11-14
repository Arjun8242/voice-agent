<script lang="ts">
  import type { ReportState } from '$lib/interview';

  // Every quote shown here was checked by the server against the project notes (interview/evaluate.py).
  let { state }: { state: ReportState } = $props();

  const SCORE_TONE: Record<number, string> = {
    1: 'bg-red-500/20 text-red-300',
    2: 'bg-orange-500/20 text-orange-300',
    3: 'bg-yellow-500/20 text-yellow-200',
    4: 'bg-emerald-500/20 text-emerald-300',
    5: 'bg-emerald-500/30 text-emerald-200',
  };
</script>

{#snippet quoted(title: string, items: { text: string; quote: string }[], mark: string)}
  {#if items.length}
    <div>
      <h4 class="text-xs font-medium uppercase tracking-wider text-[hsl(215,20%,55%)] mb-1">{title}</h4>
      <ul class="flex flex-col gap-2">
        {#each items as item, i (i)}
          <li class="text-sm">
            <span aria-hidden="true">{mark}</span> {item.text}
            <blockquote class="mt-1 ml-5 border-l-2 border-[hsl(217,33%,30%)] pl-2 text-xs italic text-[hsl(215,20%,60%)]">
              “{item.quote}”
            </blockquote>
          </li>
        {/each}
      </ul>
    </div>
  {/if}
{/snippet}

<section aria-labelledby="report-title" class="rounded-xl bg-[hsl(222,47%,14%)] border border-[hsl(217,33%,22%)] p-4 flex flex-col gap-4">
  <h2 id="report-title" class="text-lg font-semibold">Interview report</h2>

  {#if state.status === 'pending'}
    <p class="text-sm text-[hsl(215,20%,65%)]" role="status">Preparing your report…</p>
  {:else if state.status === 'failed'}
    <p class="text-sm text-red-300" role="alert">The report could not be written this time. Your answers were not lost, but there is no score for them.</p>
  {:else if state.report.reviews.length === 0}
    <p class="text-sm text-[hsl(215,20%,65%)]">No answers were recorded, so there is nothing to score.</p>
  {:else}
    <p class="text-sm">
      Average score <strong class="text-base">{state.report.average_score}</strong> / 5 over
      {state.report.reviews.length} {state.report.reviews.length === 1 ? 'answer' : 'answers'}.
    </p>

    {#if state.report.tips.length}
      <div>
        <h3 class="text-sm font-medium mb-1">Tips for next time</h3>
        <ol class="list-decimal ml-5 flex flex-col gap-1 text-sm">
          {#each state.report.tips as tip, i (i)}
            <li>{tip}</li>
          {/each}
        </ol>
      </div>
    {/if}

    {#each state.report.reviews as review, i (i)}
      <article class="rounded-lg border border-[hsl(217,33%,22%)] p-3 flex flex-col gap-3">
        <header class="flex items-center justify-between gap-2">
          <h3 class="text-sm font-medium">{i + 1}. {review.topic}</h3>
          <span class="rounded-full px-2 py-0.5 text-xs font-medium {SCORE_TONE[review.score] ?? ''}">{review.score} / 5</span>
        </header>
        <p class="text-sm text-[hsl(215,20%,75%)]"><span class="text-[hsl(215,20%,55%)]">Q:</span> {review.question}</p>
        <p class="text-sm text-[hsl(215,20%,75%)]"><span class="text-[hsl(215,20%,55%)]">You:</span> {review.answer}</p>

        {@render quoted('Got right', review.correct_points.map((p) => ({ text: p.point, quote: p.quote })), '✓')}
        {@render quoted('Missed', review.missing_points.map((p) => ({ text: p.point, quote: p.quote })), '•')}
        {@render quoted('Not what the notes say', review.incorrect_claims.map((c) => ({ text: c.claim, quote: c.quote })), '✗')}

        {#if review.unverifiable_claims.length}
          <div>
            <h4 class="text-xs font-medium uppercase tracking-wider text-[hsl(215,20%,55%)] mb-1">Not covered by the notes</h4>
            <ul class="flex flex-col gap-1 text-sm text-[hsl(215,20%,70%)]">
              {#each review.unverifiable_claims as claim, j (j)}
                <li>? {claim}</li>
              {/each}
            </ul>
          </div>
        {/if}
      </article>
    {/each}
  {/if}
</section>
