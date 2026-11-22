/**
 * What the transcript cards show, as plain functions of a card's data (ProjectCard.svelte and LinkCard.svelte draw them).
 * Status words follow the knowledge base: only "shipped" may be called built.
 */

import type { ProjectDetailCard } from './cards.ts';

export type StatusView = { label: string; tone: 'shipped' | 'local' | 'wip' };

const STATUS_VIEWS: Record<string, StatusView> = {
  shipped: { label: '✓ Shipped', tone: 'shipped' },
  runnable_not_deployed: { label: 'Runs locally', tone: 'local' },
  in_progress: { label: 'In progress', tone: 'wip' },
  idea: { label: 'Idea', tone: 'wip' },
};

// Longer than this and the card shows a few lines with a "read more" toggle.
const COLLAPSE_AFTER_CHARS = 320;

export type ProjectLink = { key: 'repo' | 'live' | 'video'; label: string; href: string | null };

/** The pill for a project status; an unknown status is shown as written rather than hidden. */
export function statusView(status: string): StatusView {
  return STATUS_VIEWS[status] ?? { label: status, tone: 'wip' };
}

/** Whether the body text is long enough to start collapsed. */
export function needsCollapse(text: string): boolean {
  return text.length > COLLAPSE_AFTER_CHARS;
}

/** The three footer buttons in a fixed order; a missing link has href null so the card can grey it out. */
export function projectLinks(links: ProjectDetailCard['data']['links']): ProjectLink[] {
  return [
    { key: 'repo', label: 'repo', href: links.repo || null },
    { key: 'live', label: 'live demo', href: links.live || null },
    { key: 'video', label: 'video', href: links.video || null },
  ];
}

/** "https://github.com/x/" -> "github.com/x", the short form shown under a link's description. */
export function hostOf(url: string): string {
  return url.replace(/^https?:\/\//, '').replace(/\/$/, '');
}

/** Up to two capitals for the link's icon tile: "GitHub Profile" -> "GP". */
export function initials(label: string): string {
  return label
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();
}
