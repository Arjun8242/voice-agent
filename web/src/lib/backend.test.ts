// Run with `npm test` (Node's built-in runner).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { backendUrls } from './backend.ts';

test('a deployed page uses the configured server for both the WebSocket and the upload', () => {
  const urls = backendUrls({ VITE_WS_URL: 'wss://api.example.com', VITE_API_URL: 'https://api.example.com/' });
  assert.deepEqual(urls, { ws: 'wss://api.example.com', upload: 'https://api.example.com/interview/upload' });
});
