# The illustration set — brief

ADR-0039 point 4. Read that first; this is the working spec for producing the set, not the decision.

> **An illustration set is commissioned or drawn once, named, and used consistently.** Black cats,
> crows, and witchy-but-playful marks. SVG, inline where small, and theme-aware so the site can have
> a dark mode without a second set of files. This is called out as a decision because an
> illustration style adopted for a hero and then abandoned for every other section is worse than
> having none — the inconsistency reads as unfinished in a way plain typography never does.

## The one constraint that is easy to lose

**Ask for SVG source, not images.** A generator asked for "illustrations" will hand back PNGs, and a
PNG cannot be theme-aware — it bakes its colours in, so a light mode needs a second set of every
file, which is precisely what point 4 rules out. What is wanted is *SVG markup*, monochrome, drawing
its colour from the page.

Concretely, every mark must use `stroke="currentColor"` and no hardcoded hex anywhere. That one
property is what makes the set survive a theme change, sit correctly on a card or in a heading, and
go muted or bright by inheriting from the text beside it.

## The grammar

Every mark, without exception:

```
viewBox="0 0 24 24"     fill="none"            stroke="currentColor"
stroke-width="1.5"      stroke-linecap="round" stroke-linejoin="round"
```

- **No `id` attributes and no `<style>` blocks.** These are inlined into one page, so ids collide
  and a style block leaks into everything after it.
- **No `fill` other than `none`**, except where a shape is meant to read as solid — an eye's pupil,
  a cat's nose — and then `fill="currentColor"`.
- **Readable at 20px.** That is the size on a feature card. A mark that needs 48px to be legible is
  the wrong mark, however good it looks large.
- **One weight throughout.** The most common failure in a generated set is drift: some marks with
  fine detail and some with three thick strokes. They must look drawn by the same hand on the same
  day.

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

Fifteen. If the generator does better on some than others, keep the good ones and hand-draw the
rest — a set of twelve that match beats fifteen that do not.

## Naming and layout

One file, `site/assets/marks.svg`, containing a `<symbol>` per mark keyed `mark-<name>` — the names
in the table above. It is inlined into `index.html` at the top of `<body>` and each use is:

```html
<svg class="mark" aria-hidden="true"><use href="#mark-cat"></use></svg>
```

`aria-hidden` because every one of these sits beside a heading that already says what it is. A mark
that repeats the heading to a screen reader is noise.

## The reference mark

`mark-cat` is drawn and in place on "Bring your own assistant". **Give it to the generator as the
example to match** — matching a real mark produces a more consistent set than matching a
description, and it is already proven to sit correctly at 20px on a card.

## Checking the result

Before committing a generated set:

```bash
grep -o 'stroke="[^"]*"' site/assets/marks.svg | sort -u   # currentColor only
grep -c 'id="' site/assets/marks.svg                        # symbols only, no stray ids
grep -o 'fill="[^"]*"' site/assets/marks.svg | sort -u      # none, or currentColor
```

Then look at the page at 100% and squint. The test is not whether each mark is good; it is whether
any one of them looks like it came from somewhere else.
