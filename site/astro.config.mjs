import { defineConfig } from 'astro/config';

// Static output — the site builds to plain HTML/CSS with no server runtime
// (REQ-SITE-001.A1).
export default defineConfig({
  output: 'static',
  site: 'https://taskship.dev',
});
