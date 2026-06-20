import { defineConfig } from 'astro/config';

// Cloudflare Pages deployment
// Update `site` to your actual Cloudflare Pages domain after deployment:
//   e.g. https://stock-radar.pages.dev
export default defineConfig({
  site: 'https://YOUR_PROJECT.pages.dev',
  base: '/',
  output: 'static',
});
