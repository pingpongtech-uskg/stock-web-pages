import { defineConfig } from 'astro/config';

// GitHub Pages deployment
// Canonical site: https://pingpongtech-uskg.github.io/stock-web-pages/
export default defineConfig({
  site: 'https://pingpongtech-uskg.github.io/stock-web-pages/',
  base: '/',
  output: 'static',
});
