import { defineConfig } from 'astro/config';

// Static output — the site builds to plain HTML/CSS with no server runtime
// (REQ-SITE-001.A1). Published to GitHub Pages as a project site at
// https://selvakumaresra.github.io/taskship/, so it serves under the `/taskship`
// base path. For a custom domain (e.g. taskship.dev) set base back to '/' and
// add a CNAME.
export default defineConfig({
  output: 'static',
  site: 'https://selvakumaresra.github.io',
  base: '/taskship',
});
