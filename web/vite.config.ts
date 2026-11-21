import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	// the resume upload goes to the backend, as the WebSocket does (ws://localhost:3001)
	// allowedHosts: Vite rejects unknown Host headers, which a Cloudflare tunnel URL would be
	server: { allowedHosts: ['.trycloudflare.com'], proxy: { '/interview': 'http://localhost:3001' } }
});
