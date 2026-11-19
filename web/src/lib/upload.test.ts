// Run with `npm test` (Node's built-in runner).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { MAX_PDF_BYTES, checkPdf, outcomeFrom, uploadBody } from './upload.ts';

test('the body is what POST /interview/upload reads, with the PDF as base64', () => {
  const pdf = new TextEncoder().encode('%PDF-1.4 resume');
  const body = JSON.parse(uploadBody('0123456789abcdef0123456789abcdef', pdf, '  Backend engineer  '));
  assert.equal(body.session_id, '0123456789abcdef0123456789abcdef');
  assert.equal(Buffer.from(body.resume_pdf, 'base64').toString(), '%PDF-1.4 resume');
  assert.equal(body.job_description, 'Backend engineer');
});

test('a file that is not a PDF, or too large, is refused before upload', () => {
  assert.equal(checkPdf('resume.docx', 100), 'Choose a PDF file.');
  assert.equal(checkPdf('Resume.PDF', MAX_PDF_BYTES + 1), 'The PDF is larger than 5 MB.');
  assert.equal(checkPdf('resume.pdf', 100), null);
});

test('the reply becomes a plan preview, the server message, or a generic error', () => {
  const plan = { preview: "We'll cover Beacon and Redis.", topics: ['Beacon'], fallback: false };
  assert.deepEqual(outcomeFrom(200, plan), { ok: true, plan });
  const scanned = { detail: { code: 'too_little_text', message: 'The PDF has almost no text.' } };
  assert.deepEqual(outcomeFrom(422, scanned), { ok: false, message: 'The PDF has almost no text.' });
  assert.equal(outcomeFrom(500, null).ok, false);
  assert.equal(outcomeFrom(200, { topics: [] }).ok, false); // a reply without a preview is not a plan
});
