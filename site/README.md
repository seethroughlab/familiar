# Site

Plain static site for [familiar.seethroughlab.com](https://familiar.seethroughlab.com). Published via GitHub Pages on push to `main` (see `.github/workflows/pages.yml`).

## Local preview

The published site expects `./screenshots/` next to `index.html`, but the source-of-truth screenshots live at the repo root. For local preview, symlink them in:

```bash
ln -s ../screenshots site/screenshots
python3 -m http.server --directory site 8000
```

Then visit <http://localhost:8000>. The symlink is gitignored.

## Publishing

The Pages workflow copies `site/` plus the repo-root `screenshots/` directory into `_site/`, writes the CNAME, and deploys. DNS: `familiar.seethroughlab.com` CNAME → `seethroughlab.github.io`.
