<script lang="ts">
  import Character from '$lib/components/Character.svelte';
  import type { CharacterKey } from '$lib/characters';
  import { reveal } from '$lib/reveal';

  // Who can talk to you: the two interviewers and recruiter mode's rep.
  const MEMBERS: { kind: CharacterKey; name: string; role: string; points: string[]; tagline: string; tint: string }[] = [
    {
      kind: 'sapwa', name: 'Sapwa', role: 'calm interviewer · master ji', tagline: 'for warming up', tint: '#e6f4cf',
      points: ['Acknowledges what you said before the next question', 'Gives a hint when you ask for one', 'Nudges gently if you go quiet'],
    },
    {
      kind: 'sheru', name: 'Sheru Bhai', role: 'strict interviewer · the boss', tagline: 'for the real thing', tint: '#fff0cf',
      points: ['Asks why you chose X over Y', 'Wants the exact mechanism or number', 'No hints. Silence is yours to use.'],
    },
    {
      kind: 'rep', name: 'the rep', role: 'recruiter mode', tagline: 'the other side of viva', tint: '#dff3ff',
      points: ['Talks to recruiters about Arjun, the builder', 'Answers only from his portfolio', "Always says it's an AI, and can book a call"],
    },
  ];
</script>

<div class="crew">
  {#each MEMBERS as member, i (member.kind)}
    <div class="member" style="background: {member.tint}" use:reveal>
      <Character kind={member.kind} followPointer seed={i} class="art" />
      <div class="nm">{member.name}</div>
      <div class="role">{member.role}</div>
      <ul>
        {#each member.points as point (point)}<li>{point}</li>{/each}
      </ul>
      <span class="tagline">{member.tagline}</span>
    </div>
  {/each}
</div>

<style>
  .crew { display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; }
  .member { border: 3px solid var(--color-ink); border-radius: 30px; padding: 20px 22px 24px; box-shadow: 7px 7px 0 var(--color-ink); transition: transform .2s; }
  .member:hover { transform: translateY(-6px) rotate(-1deg); }
  .member :global(.art) { width: 100%; height: 210px; display: block; }
  .nm { font-weight: 800; font-size: 34px; letter-spacing: -.04em; margin-top: 4px; }
  .role { font-weight: 700; font-size: 15px; margin: 4px 0 14px; }
  ul { list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }
  li { font-weight: 500; font-size: 15.5px; line-height: 1.4; padding-left: 26px; position: relative; }
  li::before { content: "✦"; position: absolute; left: 0; font-size: 15px; }
  .tagline { display: inline-block; margin-top: 16px; background: #fff; border: 2.5px solid var(--color-ink); border-radius: 999px; padding: 4px 12px; font-weight: 800; font-size: 13px; transform: rotate(-2deg); }
  @media (max-width: 980px) { .crew { grid-template-columns: 1fr; } }
</style>
