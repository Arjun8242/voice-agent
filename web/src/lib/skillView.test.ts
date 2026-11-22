// Run with `npm test` (Node's built-in runner).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { evidenceTag, groupSkills } from './skillView.ts';

test('skills are grouped by category in the order the categories first appear', () => {
  const groups = groupSkills([
    { skill: 'TypeScript', category: 'language', evidence: [] },
    { skill: 'Redis', category: 'backend', evidence: [] },
    { skill: 'Java', category: 'language', evidence: [] },
    { skill: 'Interpreter Design', category: 'computer-science', evidence: [] },
  ]);
  assert.deepEqual(groups.map((g) => [g.label, g.skills.map((s) => s.skill)]), [
    ['language', ['TypeScript', 'Java']],
    ['backend', ['Redis']],
    ['computer science', ['Interpreter Design']],
  ]);
});

test('a project shows its status and an experience shows the role, never a project status', () => {
  assert.equal(evidenceTag({ id: 'beacon', kind: 'project', name: 'Beacon', status: 'runnable_not_deployed' }), 'Runs locally');
  assert.equal(evidenceTag({ id: 'acme', kind: 'experience', name: 'Acme', role: 'Intern' }), 'Intern');
});
