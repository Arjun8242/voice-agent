/**
 * What the skills cards show, as plain functions of a card's data (SkillsCard.svelte and SkillCard.svelte draw them).
 */

import type { SkillEntry, SkillEvidence } from './cards.ts';
import { statusView } from './cardView.ts';

export type SkillGroup = { category: string; label: string; skills: SkillEntry[] };

/** Skills under their category, categories in the order they first appear. */
export function groupSkills(skills: SkillEntry[]): SkillGroup[] {
  const groups: SkillGroup[] = [];
  for (const entry of skills) {
    const group = groups.find((g) => g.category === entry.category);
    if (group) group.skills.push(entry);
    else groups.push({ category: entry.category, label: entry.category.replace('-', ' '), skills: [entry] });
  }
  return groups;
}

/** The small tag next to an evidence name: a project's status, or the role held in an experience. */
export function evidenceTag(evidence: SkillEvidence): string {
  if (evidence.kind === 'experience') return evidence.role ?? 'Experience';
  return evidence.status ? statusView(evidence.status).label : '';
}

/** The two letters on a single skill card's badge. */
export function badgeOf(skill: string): string {
  return skill.slice(0, 2);
}
