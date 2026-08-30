# ADR-0054: The Illustration Set Is Dark-Theme Only

Status: accepted

Date: 2026-08-13

Implementation:
- **Already built when ratified**, 2026-08-29, on `adr-0054-ratify-illustrations`. Fourteen marks
  live in `site/assets/marks/` as `.webp`, and `site/ILLUSTRATIONS.md` holds the prompts.
- Point 1 holds: the marks are full-colour raster on the site's single dark palette, with no
  `currentColor` and no light variants. Point 3's transparency was checked in the files themselves
  rather than assumed — every one is RGBA with a fully transparent corner and `alpha-min = 0`.
  Sizes are 2×-scale (479×689, 1024×510), and SVG is still what `icon.svg` and the App Store badge
  use.
- **Point 3 is honoured by a route the ADR did not anticipate, and `ILLUSTRATIONS.md` reads like it
  contradicts it.** That file says in bold: *"Ask for a pure black background, and never for a
  transparent one."* The reason is in `site/scripts/extract-marks.py` — **Gemini returns JPEG, which
  has no alpha channel**, so asked for transparency it *draws* the grey checkerboard, because that
  is the visual signifier it has seen. Those squares are real pixels and no prompt removes them. The
  prompt therefore asks for a ground the script can key, and the script produces the transparency
  the decision requires. The instruction that looks like a contradiction is what makes the point
  achievable.
- **Nine of the fourteen marks are unreferenced.** In use: `cat-and-crow` (hero), `crow-record`,
  `lantern`, `cat-curled`, `cat-sitting`. Unused: `cat-stretching`, `cat-walking`, `cauldron`,
  `constellation`, `crow-calling`, `crow-flight`, `crow-hopping`, `moon-phases`, `tuning-fork`.
  Recorded so nobody prunes them as dead assets — ADR-0055 point 5 turns features into five or six
  illustrated sections, and this is the reserve that pays for it. If `0055` is withdrawn, they
  become genuinely unused and the question is worth reopening.

Supersedes the theme-awareness clause of
[ADR-0039](ADR-0039-the-website-is-rebuilt-in-place.md) point 4. The rest of that point — one set,
drawn once, named, and used consistently — stands unchanged and is the part that mattered.

## Context

ADR-0039 point 4 asked for marks that are "SVG, inline where small, and theme-aware so the site can
have a dark mode without a second set of files." In practice that meant every mark drawing with
`currentColor` and hardcoding no colour at all.

**The premise was never true.** The site has no light mode: `site/assets/site.css` defines a single
dark palette with no `prefers-color-scheme` block and no theme toggle. Familiar itself is dark —
the Mac app, the phone, the web app. Nothing is planned that would change that, so the requirement
was insuring against a mode nobody intends to build.

The cost of that insurance turned out to be the whole visual register. A `currentColor` mark is
monochrome by construction: one flat colour, inherited. That is exactly right for an icon and
exactly wrong for the "black cats, crows, witchy-but-playful" the same point asks for — charm in an
illustration lives in colour, weight and contrast, none of which a single inherited stroke colour
can carry. Point 4 was, in effect, asking for two incompatible things and getting the icon.

It also closed off the practical route to producing them. A generator asked for illustrations
returns raster; raster cannot inherit a colour, so `currentColor` ruled the whole approach out and
left hand-authored SVG paths as the only option — which is where the drawing is weakest.

## Decision

1. **The illustration set is dark-theme only, and may use colour.** No `currentColor` requirement,
   no light-mode variants, no second set of files — because there is no second theme to serve.

2. **The marks are still one named set, drawn once, and used consistently.** This is the part of
   point 4 that was load-bearing, and it survives intact: a style adopted for a hero and abandoned
   for every other section still reads as unfinished.

3. **Raster is permitted where it earns its place**, at 2× for the displays this will be read on,
   with a transparent background so a mark sits on any panel the site has. SVG stays preferred for
   anything simple enough to be drawn as paths, because it is smaller and stays sharp.

4. **A mixed set is not permitted.** Filled colour illustrations beside monochrome stroked icons is
   the inconsistency point 4 exists to prevent, arriving by a different route. Whichever register
   the set commits to, all of it commits.

5. **If a light mode is ever built, this is what has to be revisited** — not silently worked around
   with filters or opacity. The set would need redrawing or a second variant, and that cost is
   accepted here rather than discovered then.

## Alternatives Considered

- **Keep `currentColor` and accept monochrome marks.** Cheapest, and genuinely correct for an icon
  set. Rejected because it is not what point 4 asked for: black cats and crows drawn as single-weight
  monochrome strokes are pictograms, and the reference mark drawn under that constraint proved it —
  competent, and not charming.

- **Author light and dark variants of each mark.** Keeps colour and keeps theme support. Rejected as
  paying twice for a mode that does not exist, and as the exact "second set of files" point 4 was
  written to avoid — the requirement inverted rather than dropped.

- **Colour illustrations with a CSS filter for a hypothetical light mode.** No second set, some
  colour. Rejected because filtered illustration looks like filtered illustration, and a mode nobody
  has planned is not worth constraining every mark's palette.

- **Do nothing and leave point 4 unfulfilled.** Defensible — the ADR itself predicted this is the
  part most likely to be left undone, and an unstarted illustration set is a better state than a
  half-done one. Rejected because the constraint, not the effort, was what had stalled it.

## Consequences

- **Positive:** the set can be produced the way illustration is normally produced, including by
  generation, rather than only as hand-authored paths.
- **Positive:** colour, weight and contrast are available, which is most of what separates an
  illustration from an icon.
- **Tradeoff:** a mark's colour is now fixed rather than inherited. `currentColor` was not only about
  themes — it is why one file could sit in a heading in accent purple and in a muted footnote in
  grey. Reusing a mark at two weights now needs two versions, or looks wrong at one of them.
- **Tradeoff:** raster marks are heavier than paths and do not scale beyond their 2× rendering. The
  page is already carrying five screenshots, so this is a real budget rather than a rounding error.
- **Tradeoff:** a light mode becomes a redraw rather than a no-op. Point 5 exists so that is a known
  price and not a surprise.
- **Follow-up:** `site/ILLUSTRATIONS.md` is the working brief and must be rewritten to match, since
  its grammar section is built entirely on the constraint this removes.
- **Follow-up:** `mark-cat` was drawn as the reference under the old constraint. It is either
  redrawn in the new register or dropped — a stroked monochrome cat sitting beside a colour set is
  point 4's own failure mode.
