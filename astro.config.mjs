import { defineConfig } from 'astro/config';

import cloudflare from '@astrojs/cloudflare';

// Cloudflare Pages deployment
// Update `site` to your actual Cloudflare Pages domain after deployment:
//   e.g. https://stock-radar.pages.dev
export default defineConfig({
  site: 'https://YOUR_PROJECT.pages.dev',
  base: '/',
  output: 'static',
  adapter: cloudflare(),
});