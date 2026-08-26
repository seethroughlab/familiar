# Site

Plain static site for [familiar.seethroughlab.com](https://familiar.seethroughlab.com). Deployed to
**Cloudflare Pages** on push to `main` (see `.github/workflows/cloudflare-pages.yml`).

No generator and no build step: two HTML files and a stylesheet do not justify a toolchain
([ADR-0039](../docs/decisions/ADR-0039-the-website-is-rebuilt-in-place.md) point 1). Release notes,
a blog or rendered docs are what would reverse that — see point 6 before adding one.

## Local preview

The published site expects `./screenshots/` next to `index.html`, but the source-of-truth screenshots live at the repo root. For local preview, symlink them in:

```bash
ln -s ../screenshots site/screenshots
python3 -m http.server --directory site 8000
```

Then visit <http://localhost:8000>. The symlink is gitignored.

## Publishing

The workflow assembles `_site/` from `site/` plus the repo-root `screenshots/` directory, then
deploys it with `cloudflare/pages-action@v1` to the Cloudflare Pages project **`familiar-site`**,
using the `CF_API_TOKEN` and `CF_ACCOUNT_ID` secrets.

> **This section used to describe GitHub Pages** — a CNAME file the repository does not contain,
> and DNS pointing at `seethroughlab.github.io`. None of it was true after the Cloudflare
> migration. The workflow *was* named `pages.yml` with a job called Pages, which is presumably
> how it survived. Corrected under ADR-0039 point 7. Renaming the workflow would stop this
> happening again and has not been done.
