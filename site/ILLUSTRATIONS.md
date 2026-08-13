# The illustration set — brief

ADR-0039 point 4, as amended by [ADR-0054](../docs/decisions/ADR-0054-the-illustration-set-is-dark-theme-only.md).
Read those first; this is the working spec for producing the set, not the decision.

> **An illustration set is commissioned or drawn once, named, and used consistently.** Black cats,
> crows, and witchy-but-playful marks. […] This is called out as a decision because an illustration
> style adopted for a hero and then abandoned for every other section is worse than having none —
> the inconsistency reads as unfinished in a way plain typography never does.

**ADR-0054 dropped the theme-awareness requirement.** The site has no light mode and none is
planned, and demanding `currentColor` made every mark monochrome — which is right for an icon and
wrong for a black cat. Colour is available. What survives, and what actually matters, is that the
set is one set.

## The register — decide this once, before generating anything

Everything below hangs off a single choice, and **the set must commit to one of these entirely.**
Colour illustrations beside monochrome stroked icons is point 4's failure mode arriving by a
different route.

**A. Drawn illustrations, in colour.** Raster, generated or painted. This is the register that gets
you charm — a cat with an expression rather than a cat-shaped outline. Heavier files, fixed at their
rendered size.

**B. Flat vector marks, in colour.** SVG paths with two or three fills from the site palette. Sharper,
far smaller, and consistent almost for free, but limited to shapes that can be described as paths —
which in practice means the tools read better than the animals.

There is no wrong answer, only a wrong mixture. **Pick one and produce all fifteen in it.**

## If you go with A — raster

- **2×** for the displays this is read on. A mark shown at 20px is generated at 40px; a hero mark at
  120px is generated at 240px.
- **Transparent background, always.** The site's panels are `#18181b` on a `#0a0a0a` page, so a mark
  with a baked background will show its own rectangle on one of them.
- **PNG.** These are flat-ish art with hard edges and transparency, which is what PNG is for; JPEG
  will fringe the edges and cannot carry alpha.
- Watch the total. The page already carries five screenshots; fifteen marks at 40px cost nothing,
  fifteen at 240px do not.

## If you go with B — vector

```
viewBox="0 0 24 24"     stroke-linecap="round"    stroke-linejoin="round"
```

- Fills from the palette below. Strokes only where a line is the drawing.
- **No `id` attributes and no `<style>` blocks.** These are inlined into one page, so ids collide and
  a style block leaks into everything after it.
- **Readable at 20px**, which is the size on a feature card.

## The palette

Taken from `site/assets/site.css`, so the marks belong to the page rather than sitting on it.

| | |
|---|---|
| page | `#0a0a0a` |
| panel | `#18181b` |
| text | `#fafafa` |
| muted | `#71717a` |
| purple | `#a855f7` |
| green | `#22c55e` |
| blue | `#3b82f6` |
| red | `#f87171` |

Purple is the closest thing Familiar has to a signature; it is the safest lead for a witchy set.
Anything that needs to read as *live* — playing, listening, connected — takes green.

## The motifs

A *familiar* is a witch's animal companion, which is the idea the whole set hangs off. Animals for
the things that act on your behalf; tools for the things you operate.

| Mark | Where it goes | Why |
|---|---|---|
| `cat` | Bring your own assistant | The familiar itself. The one mark that could carry the hero. |
| `cat-ear` | Semantic audio search | Listening, turned toward a sound. Not a magnifying glass. |
| `paw-trail` | Find similar | Three prints leading off — one track leading to the next. |
| `crow` | Discover / new releases | The bird that brings you things. |
| `moon-phases` | Mood Grid | Three phases in a row. Moods as a spectrum, not categories. |
| `constellation` | Music Map | Stars with lines drawn between them; that *is* the map. |
| `orb` | 3D Explorer | A scrying sphere on a stand. Depth, and looking into it. |
| `eye` | CLAP embeddings | What the analysis does: listens once, and knows. |
| `tuning-fork` | Musical features | The one honest instrument in a set of magic. |
| `cauldron` | Smart playlists | A rule set, brewing, filling itself. |
| `lantern` | Offline | Light you carry when there is no supply. |
| `key` | Remote access | Tailscale, a password on a session. |
| `hearth` | Community cache | Shared warmth, nothing personal given away. |
| `moon-reel` | Music videos | A film reel whose sprockets are a crescent. |
| `two-cats` | Listening sessions | Two familiars, one fire. Company. |

Fifteen. If the generator does better on some than others, keep the good ones and commission the
rest — a set of twelve that match beats fifteen that do not.

## Naming and placement

Named as in the table. Raster goes to `site/assets/marks/<name>.png`; vector goes into
`site/assets/marks.svg` as a `<symbol id="mark-<name>">`, inlined at the top of `<body>` so a `<use>`
costs no request.

Each use sits in the heading it belongs to and carries `alt=""` or `aria-hidden="true"` — every mark
is beside a heading that already says what it is, and repeating that to a screen reader is noise.

## Before committing a generated set

Look at the page at 100% and squint. The test is not whether each mark is good; it is whether any
one of them looks like it came from somewhere else — different weight, different palette, different
level of detail. That is the only failure point 4 actually cares about.

Then check the obvious mechanical things: transparent backgrounds on every raster mark, no baked
panel colour, and nothing so fine it disappears at 20px.

## The reference mark

`mark-cat` in `site/assets/marks.svg` was drawn under the old monochrome constraint. **It is a
grammar reference, not a style reference** — useful for weight and framing, and superseded the
moment the set commits to a register. ADR-0054's last follow-up is to redraw or drop it, because a
stroked monochrome cat beside a colour set is exactly what point 4 forbids.
