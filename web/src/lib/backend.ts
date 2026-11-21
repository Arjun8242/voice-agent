/**
 * Where the voice server is, from Vite env vars (web/.env; see web/.env.example).
 * Development needs neither: the WebSocket goes to ws://localhost:3001 and the upload through the Vite proxy
 * (vite.config.ts). A deployed page sets VITE_WS_URL (wss://...) and VITE_API_URL (https://...); when the API is on
 * another origin, the server must list the page's origin in CORS_ORIGINS (backend/config.py).
 */

export interface BackendEnv {
  VITE_WS_URL?: string;
  VITE_API_URL?: string;
}

export function backendUrls(env: BackendEnv): { ws: string; upload: string } {
  const api = (env.VITE_API_URL ?? '').replace(/\/+$/, '');
  return { ws: env.VITE_WS_URL || 'ws://localhost:3001', upload: `${api}/interview/upload` };
}

// import.meta.env is undefined outside Vite (the node unit tests), which then get the development defaults
export const BACKEND = backendUrls((import.meta.env as BackendEnv | undefined) ?? {});
