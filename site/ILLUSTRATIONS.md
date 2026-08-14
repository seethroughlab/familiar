# Illustration prompts

Paste one at a time into Gemini. Each is self-contained — the style block is repeated in every
prompt on purpose, because a generator drifts within a few images once the description stops being
in front of it, and drift across the set is the one failure ADR-0039 point 4 actually cares about.

The register is the **Welcome to Night Vale tour poster**: hand-inked line, crosshatch shading,
three inks in the light range on a black ground. Not the flat vector look of the novel cover, and
emphatically not the thick uniform outline the first set came back with.

**Ask for a pure black background, and never for a transparent one.** Gemini returns JPEG, which
has no alpha channel, so a request for transparency is impossible to honour — and rather than
refuse, it draws the grey Photoshop checkerboard as actual pixels. Fourteen of the first fifteen
came back that way. Black is also what makes the extraction exact: over a black ground a pixel is
its own colour times its coverage, so coverage is just how bright it got, and dividing that back out
recovers the ink. A one-pixel hatch line survives with correct partial alpha instead of being cut.

```
uv run site/scripts/extract-marks.py --out site/assets/marks --size 1024 cat=path/to/download.jpeg
```

The dark inside a shape becomes transparent, which is right: in this register the darkness is the
ground, so it should show the page rather than carry its own black rectangle onto a panel.

**These are meant to be used large.** Crosshatching turns to mud below about 80px, so the page
wants a few big illustrations rather than a grid of small icons. Generate at 2048 and don't plan on
a 40px feature-card icon — that is a different job, and this set will not do it.

**Do not reproduce the Night Vale eye-and-crescent.** It is their actual logo, on the book cover and
the merchandise. The register is fair to borrow; the mark is not. That is why there is no eye prompt
below — the cat's eyes carry it instead.

## Keeping the cat and the crow consistent

This is the part a generator is worst at, and prompt wording will not fix it. Two things that do:

1. **Get `cat` right first**, then attach that image to every later prompt as a style and character
   reference. Matching a real picture holds a set together far better than matching a description.
2. For the poses, ask for a **model sheet** — one image containing the same cat four times — and cut
   the poses apart afterwards. Consistency is then structural rather than hoped for. The prompt for
   that is `cat-poses` below.

---

## 1 · cat

> A hand-inked illustration of a sitting black cat seen from the front, tail curled around its
> paws, ears alert, expression calm and knowing. Drawn in the style of a screen-printed indie tour
> poster: loose confident pen-and-brush line of varying weight, visibly drawn by hand, with breaks,
> overshoots and wobble — never a uniform traced outline. All shading built from crosshatching and
> stippling; no flat fills, no gradients, no airbrush. Three inks only — pale pink (#fce7f3) for
> highlights, magenta (#e879f9) for the body, violet (#a855f7) for the deepest tone. Every drawn
> element sits in that light range; black is negative space, never something drawn with. Solid pure
> black (#000000) background, edge to edge, nothing else in the frame. Centred with generous margin.
> No text, no lettering, no signature. Eerie but warm, deadpan rather than spooky.

## 2 · cat-poses

> A model sheet: the same hand-inked black cat drawn four times in one image, in a 2x2 grid, evenly
> spaced with clear black space between each — sitting front-on, walking in profile, curled asleep,
> and stretching with its back arched. Identical cat in every pose: same proportions, same face,
> same line weight. Drawn in the style of a screen-printed indie tour poster: loose confident
> pen-and-brush line of varying weight, visibly drawn by hand, with breaks and wobble, never a
> uniform traced outline. All shading built from crosshatching and stippling; no flat fills, no
> gradients. Three inks only — pale pink (#fce7f3), magenta (#e879f9), violet (#a855f7). Every drawn
> element sits in that light range; black is negative space. Solid pure black (#000000) background.
> No text, no labels, no borders between the poses. Eerie but warm, deadpan rather than spooky.

## 3 · cat-listening

> A hand-inked illustration of a black cat sitting in profile with its head tilted and one ear
> swivelled toward a sound off to the side, eyes half closed, utterly absorbed. Three faint arcs in
> the air beside the ear suggest the sound. Drawn in the style of a screen-printed indie tour
> poster: loose confident pen-and-brush line of varying weight, visibly drawn by hand, with breaks
> and wobble, never a uniform traced outline. All shading built from crosshatching and stippling; no
> flat fills, no gradients. Three inks only — pale pink (#fce7f3) for highlights, magenta (#e879f9)
> for the body, violet (#a855f7) for the deepest tone. Every drawn element sits in that light range;
> black is negative space. Solid pure black (#000000) background, edge to edge. Centred with
> generous margin. No text. Eerie but warm, deadpan rather than spooky.

## 4 · cat-curled

> A hand-inked illustration of a black cat curled asleep in a tight spiral on top of a small stack
> of vinyl records, nose tucked under its tail, entirely content. Drawn in the style of a
> screen-printed indie tour poster: loose confident pen-and-brush line of varying weight, visibly
> drawn by hand, with breaks and wobble, never a uniform traced outline. All shading built from
> crosshatching and stippling; no flat fills, no gradients. Three inks only — pale pink (#fce7f3)
> for highlights, magenta (#e879f9) for the body, violet (#a855f7) for the deepest tone. Every drawn
> element sits in that light range; black is negative space. Solid pure black (#000000) background,
> edge to edge. Centred with generous margin. No text. Eerie but warm, deadpan rather than spooky.

## 5 · crow

> A hand-inked illustration of a crow in profile standing alert, wings tucked, a small vinyl record
> held in its beak, one eye fixed on the viewer with obvious opinions. Drawn in the style of a
> screen-printed indie tour poster: loose confident pen-and-brush line of varying weight, visibly
> drawn by hand, with breaks, overshoots and wobble — never a uniform traced outline. Feathers built
> from directional hatching. All shading from crosshatching and stippling; no flat fills, no
> gradients. Three inks only — pale pink (#fce7f3) for highlights, magenta (#e879f9) for the body,
> violet (#a855f7) for the deepest tone. Every drawn element sits in that light range; black is
> negative space. Solid pure black (#000000) background, edge to edge. Centred with generous margin.
> No text. Eerie but warm, deadpan rather than spooky.

## 6 · crow-flight

> A hand-inked illustration of a crow in flight seen from the side, wings fully spread, carrying a
> small vinyl record in its beak, a few loose feathers trailing behind it. Drawn in the style of a
> screen-printed indie tour poster: loose confident pen-and-brush line of varying weight, visibly
> drawn by hand, with breaks and wobble, never a uniform traced outline. Flight feathers drawn as
> long confident strokes, shading from crosshatching; no flat fills, no gradients. Three inks only —
> pale pink (#fce7f3) for highlights, magenta (#e879f9) for the body, violet (#a855f7) for the
> deepest tone. Every drawn element sits in that light range; black is negative space. Solid pure
> black (#000000) background, edge to edge. Centred with generous margin. No text. Eerie but warm,
> deadpan rather than spooky.

## 7 · cat-and-crow

> A hand-inked illustration of a black cat and a crow side by side on a low ridge, the cat sitting
> upright and the crow perched beside it at the cat's shoulder height, both looking out at the same
> thing off to one side — companionable rather than confrontational. A thin crescent moon low behind
> them. This is the largest piece in the set, so allow more detail than the others. Drawn in the
> style of a screen-printed indie tour poster: loose confident pen-and-brush line of varying weight,
> visibly drawn by hand, with breaks, overshoots and wobble — never a uniform traced outline. All
> shading built from crosshatching and stippling; no flat fills, no gradients. Three inks only —
> pale pink (#fce7f3) for highlights, magenta (#e879f9) for bodies, violet (#a855f7) for the deepest
> tone. Every drawn element sits in that light range; black is negative space. Solid pure black
> (#000000) background, edge to edge. No text. Eerie but warm, deadpan rather than spooky.

## 8 · moon-phases

> A hand-inked illustration of three moons in a horizontal row — a thin crescent, a half moon and a
> full moon — evenly spaced and the same size, each with a cratered, hand-stippled surface. Drawn in
> the style of a screen-printed indie tour poster: loose confident pen-and-brush line of varying
> weight, visibly drawn by hand, with breaks and wobble, never a uniform traced outline. All shading
> built from crosshatching and stippling; no flat fills, no gradients. Three inks only — pale pink
> (#fce7f3) for the lit surface, magenta (#e879f9) for the mid tone, violet (#a855f7) for the
> deepest. Every drawn element sits in that light range; the unlit part of each moon is left as bare
> black negative space rather than drawn. Solid pure black (#000000) background, edge to edge. No
> text. Eerie but warm, deadpan rather than spooky.

## 9 · lantern

> A hand-inked illustration of a small hanging lantern with a ring handle, glass panels and a
> steady flame inside, hanging slightly crooked. Drawn in the style of a screen-printed indie tour
> poster: loose confident pen-and-brush line of varying weight, visibly drawn by hand, with breaks
> and wobble, never a uniform traced outline. The metal frame shaded with crosshatching, the light
> falling from the flame drawn as fine radiating strokes; no flat fills, no gradients. Three inks
> only — pale pink (#fce7f3) for the flame and the brightest glass, magenta (#e879f9) for the mid
> tone, violet (#a855f7) for the frame. Every drawn element sits in that light range; black is
> negative space. Solid pure black (#000000) background, edge to edge. Centred with generous margin.
> No text. Eerie but warm, deadpan rather than spooky.

## 10 · cauldron

> A hand-inked illustration of a small round cauldron on three stubby legs, with a single musical
> note rising out of it on a curl of vapour. Drawn in the style of a screen-printed indie tour
> poster: loose confident pen-and-brush line of varying weight, visibly drawn by hand, with breaks
> and wobble, never a uniform traced outline. The cauldron shaded with dense crosshatching, the
> vapour with light open strokes; no flat fills, no gradients. Three inks only — pale pink (#fce7f3)
> for the note and the brightest vapour, magenta (#e879f9) for the brew, violet (#a855f7) for the
> iron. Every drawn element sits in that light range; black is negative space. Solid pure black
> (#000000) background, edge to edge. Centred with generous margin. No text. Eerie but warm, deadpan
> rather than spooky.

## 11 · tuning-fork

> A hand-inked illustration of a two-pronged tuning fork standing upright, still ringing, with two
> loose vibration arcs on each side of the prongs. Drawn in the style of a screen-printed indie tour
> poster: loose confident pen-and-brush line of varying weight, visibly drawn by hand, with breaks
> and wobble, never a uniform traced outline. The metal shaded with fine parallel hatching along its
> length; no flat fills, no gradients. Three inks only — pale pink (#fce7f3) for the highlight down
> one edge, magenta (#e879f9) for the body, violet (#a855f7) for the vibration arcs. Every drawn
> element sits in that light range; black is negative space. Solid pure black (#000000) background,
> edge to edge. Centred with generous margin. No text. Eerie but warm, deadpan rather than spooky.

## 12 · constellation

> A hand-inked illustration of a small constellation — six stars of varying sizes joined by thin
> ruled lines into a loose cluster, like a hand-drawn star chart, with a scatter of tiny stipple
> dots around them. Drawn in the style of a screen-printed indie tour poster: loose confident
> pen-and-brush line of varying weight, visibly drawn by hand, with breaks and wobble, never a
> uniform traced outline. No flat fills, no gradients. Three inks only — pale pink (#fce7f3) for the
> brightest stars, magenta (#e879f9) for the rest, violet (#a855f7) for the joining lines. Every
> drawn element sits in that light range; black is negative space. Solid pure black (#000000)
> background, edge to edge. Centred with generous margin. No text. Eerie but warm, deadpan rather
> than spooky.

---

## If a result drifts

The usual failures, and what to add to the prompt:

- **Came back with a thick uniform outline** — the failure the first set had. Add *"no outline at
  all; the form is described by hatching and by the edge of the hatching, the way a woodcut or a pen
  drawing works"*.
- **Came back on a checkerboard** — the prompt said "transparent" somewhere. It cannot be done in
  JPEG. Ask for solid pure black.
- **The background is dark grey rather than black** — add *"the background must be pure #000000
  black, absolutely uniform, with no vignette, no texture and no glow around the subject"*. A lifted
  background lifts the whole matte with it, and the mark arrives faintly foggy.
- **Too clean, looks vector** — add *"visible ink texture, dry-brush breaks in the line, slightly
  uneven pressure, imperfect registration as if screen-printed"*.
- **Drew in black** — add *"nothing is drawn in black or dark grey; every mark on the page is pale
  pink, magenta or violet"*. Anything drawn dark mattes out as transparent.
- **The cat stopped looking like the cat** — attach the approved `cat` image and add *"same
  character, same proportions, same face as the reference"*.
