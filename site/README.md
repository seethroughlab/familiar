# Site

Plain static site for [familiar.seethroughlab.com](https://familiar.seethroughlab.com). Deployed to
**Cloudflare Pages** on push to `main` (see `.github/workflows/cloudflare-pages.yml`).

No generator and no build step: four HTML pages, a stylesheet and one small script do not justify a toolchain
([ADR-0039](../docs/decisions/ADR-0039-the-website-is-rebuilt-in-place.md) point 1). Release notes,
a blog or rendered docs are what would reverse that — see point 6 before adding one.

## What is here

- `index.html`, `faq.html`, `privacy.html` — written by hand. They share one nav and one footer;
  `e2e/pages.spec.ts` checks they still do.
- `visualizers.html` — **generated** from `docs/VISUALIZER_API.md` by `scripts/render-docs.py`
  (ADR-0103). Edit the Markdown and re-render; never edit the HTML.
- `assets/install.js` — the install section's two choosers (ADR-0143). It only hides; with no
  JavaScript every path is shown.
- `e2e/` — Playwright tests, run by CI's **Site Test** job:
  `cd packages/web && npx playwright test --config=../../site/playwright.config.ts`.
- `scripts/check-claims.py` — the mechanical half of `docs/SITE-CLAIMS.md`, run before and after
  every deploy.

## Local preview

The published site expects `./screenshots/` next to `index.html`, but the source-of-truth screenshots live at the repo root. For local preview, symlink them in:

```bash
ln -s ../screenshots site/screenshots
python3 -m http.server --directory site 8000
```

Then visit <http://localhost:8000>. The symlink is gitignored.

## Publishing

The workflow assembles `_site/` from `site/` plus the repo-root `screenshots/` directory, then
deploys it with `cloudflare/wrangler-action@v4` (`wrangler pages deploy`; `pages-action` was withdrawn in September 2026) to the Cloudflare Pages project **`familiar-site`**,
using the `CF_API_TOKEN` and `CF_ACCOUNT_ID` secrets.

> **This section used to describe GitHub Pages** — a CNAME file the repository does not contain,
> and DNS pointing at `seethroughlab.github.io`. None of it was true after the Cloudflare
> migration. The workflow *was* named `pages.yml` with a job called Pages, which is presumably
> how it survived. Corrected under ADR-0039 point 7. Renaming the workflow would stop this
> happening again and has not been done.
