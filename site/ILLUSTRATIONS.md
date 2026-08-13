# Illustration prompts

Paste one at a time into Gemini. Each is self-contained — the style block is repeated in every
prompt on purpose, because a generator drifts within a few images once the description stops being
in front of it, and drift across the set is the one failure ADR-0039 point 4 actually cares about.

**Never ask for a transparent background.** Gemini returns JPEG, and JPEG has no alpha channel, so
the request is impossible to honour — and rather than refuse, it draws the grey Photoshop
checkerboard as actual pixels, because that is the visual signifier of transparency it has learned.
Fourteen of the first fifteen marks came back that way. The prompts below ask for **flat cyan**
instead: no mark uses cyan, and its nearest neighbour in the palette is the green accent, ~174 away
in RGB, so it keys out cleanly.

Cut the background off afterwards, which also crops, resizes and shrinks each file to about 10 KB:

```
uv run site/scripts/extract-marks.py --out site/assets/marks cat=path/to/download.jpeg
```

It reads the background off the image itself, so it handles both the cyan ones and the
checkerboards already generated. Keep the source JPEGs out of `site/` — everything there is copied
straight to Cloudflare, and they are 2 MB each.

Generate at **at least 1024x1024**, so a mark stays clean when it is shown at 40px.

---

## 1 · cat

> A flat vector illustration of a sitting black cat seen from the front, tail curled around its
> paws, drawn in a witchy but playful style — rounded shapes, no sharp horror. Thick confident
> outlines in warm violet (#a855f7), body filled near-black (#0a0a0a) with subtle violet rim light
> on one edge. Two calm almond eyes in pale green (#22c55e). Centred in a square frame with generous
> margin. Solid flat cyan (#00FFFF) background, one uniform colour edge to edge. Flat colour only — no gradients, no shading, no texture, no drop
> shadow, no text. Simple enough to read clearly at 40 pixels.

## 2 · cat-ear

> A flat vector illustration of a single black cat's ear, turned and tilted as if listening intently
> toward a sound off to one side, with three small concentric sound arcs beside it. Witchy but
> playful, rounded shapes. Thick confident outlines in warm violet (#a855f7), ear filled near-black
> (#0a0a0a), inner ear a muted rose. Sound arcs in pale green (#22c55e). Centred in a square frame
> with generous margin. Solid flat cyan (#00FFFF) background, one uniform colour edge to edge. Flat colour only — no gradients, no shading, no
> texture, no drop shadow, no text. Simple enough to read clearly at 40 pixels.

## 3 · paw-trail

> A flat vector illustration of three cat paw prints in a curving trail, walking away from the
> viewer and getting slightly smaller, as if one is leading to the next. Witchy but playful, rounded
> shapes. Paw prints filled near-black (#0a0a0a) with thick warm violet (#a855f7) outlines; the
> furthest print fades to violet only. Centred in a square frame with generous margin. Solid flat cyan (#00FFFF) background, one uniform colour edge to edge. Flat colour only — no gradients, no shading, no texture, no drop shadow, no text.
> Simple enough to read clearly at 40 pixels.

## 4 · crow

> A flat vector illustration of a crow in profile carrying a small vinyl record in its beak, wings
> tucked, standing alert. Witchy but playful, rounded shapes, characterful rather than menacing.
> Thick confident outlines in warm violet (#a855f7), body filled near-black (#0a0a0a) with a violet
> sheen mark on the wing. One pale green (#22c55e) eye. Centred in a square frame with generous
> margin. Solid flat cyan (#00FFFF) background, one uniform colour edge to edge. Flat colour only — no gradients, no shading, no texture, no drop
> shadow, no text. Simple enough to read clearly at 40 pixels.

## 5 · moon-phases

> A flat vector illustration of three moons in a horizontal row showing a crescent, a half and a
> full moon, evenly spaced and the same size. Witchy but playful. Thick confident outlines in warm
> violet (#a855f7); lit portions filled off-white (#fafafa), unlit portions filled near-black
> (#0a0a0a). Centred in a square frame with generous margin. Solid flat cyan (#00FFFF) background, one uniform colour edge to edge. Flat colour
> only — no gradients, no shading, no texture, no drop shadow, no text. Simple enough to read
> clearly at 40 pixels.

## 6 · constellation

> A flat vector illustration of a small constellation — six stars of varying sizes joined by thin
> straight lines into a loose cluster, like a star chart. Witchy but playful. Lines in warm violet
> (#a855f7); stars filled off-white (#fafafa) with violet outlines; two of the stars pale green
> (#22c55e). Centred in a square frame with generous margin. Solid flat cyan (#00FFFF) background, one uniform colour edge to edge. Flat colour
> only — no gradients, no shading, no texture, no drop shadow, no text. Simple enough to read
> clearly at 40 pixels.

## 7 · orb

> A flat vector illustration of a crystal ball resting on a small clawed stand, with three tiny
> stars floating inside the sphere. Witchy but playful, rounded shapes. Thick confident outlines in
> warm violet (#a855f7); sphere filled deep near-black (#0a0a0a) with a single off-white (#fafafa)
> crescent highlight; stand filled violet. Stars pale green (#22c55e). Centred in a square frame
> with generous margin. Solid flat cyan (#00FFFF) background, one uniform colour edge to edge. Flat colour only — no gradients, no shading, no
> texture, no drop shadow, no text. Simple enough to read clearly at 40 pixels.

## 8 · eye

> A flat vector illustration of a single stylised eye, almond shaped, with a small crescent moon as
> the pupil and three short eyelash strokes above. Witchy but playful, calm rather than staring.
> Thick confident outlines in warm violet (#a855f7); eye white filled off-white (#fafafa); pupil
> near-black (#0a0a0a). Centred in a square frame with generous margin. Solid flat cyan (#00FFFF) background, one uniform colour edge to edge. Flat
> colour only — no gradients, no shading, no texture, no drop shadow, no text. Simple enough to read
> clearly at 40 pixels.

## 9 · tuning-fork

> A flat vector illustration of a two-pronged tuning fork standing upright, with two small
> vibration arcs on each side of the prongs. Witchy but playful, rounded shapes. Thick confident
> outlines in warm violet (#a855f7); fork filled off-white (#fafafa); vibration arcs pale green
> (#22c55e). Centred in a square frame with generous margin. Solid flat cyan (#00FFFF) background, one uniform colour edge to edge. Flat colour
> only — no gradients, no shading, no texture, no drop shadow, no text. Simple enough to read
> clearly at 40 pixels.

## 10 · cauldron

> A flat vector illustration of a small round cauldron on three stubby legs, with a musical note
> rising out of it on a curl of vapour. Witchy but playful, rounded shapes. Thick confident outlines
> in warm violet (#a855f7); cauldron filled near-black (#0a0a0a); the brew inside and the rising
> note pale green (#22c55e). Centred in a square frame with generous margin. Solid flat cyan (#00FFFF) background, one uniform colour edge to edge.
> Flat colour only — no gradients, no shading, no texture, no drop shadow, no text. Simple enough to
> read clearly at 40 pixels.

## 11 · lantern

> A flat vector illustration of a small hanging lantern with a ring handle, glass panels, and a
> steady flame inside. Witchy but playful, rounded shapes. Thick confident outlines in warm violet
> (#a855f7); lantern frame filled near-black (#0a0a0a); glass panels a faint violet; flame pale
> green (#22c55e). Centred in a square frame with generous margin. Solid flat cyan (#00FFFF) background, one uniform colour edge to edge. Flat
> colour only — no gradients, no shading, no texture, no drop shadow, no text. Simple enough to read
> clearly at 40 pixels.

## 12 · key

> A flat vector illustration of an ornate old iron key seen side on, with a looping decorative bow
> at the top and two simple teeth at the bottom. Witchy but playful, rounded shapes. Thick confident
> outlines in warm violet (#a855f7); key filled off-white (#fafafa) with a near-black (#0a0a0a)
> keyhole shape cut into the bow. Centred in a square frame with generous margin. Solid flat cyan (#00FFFF) background, one uniform colour edge to edge. Flat colour only — no gradients, no shading, no texture, no drop shadow, no text.
> Simple enough to read clearly at 40 pixels.

## 13 · hearth

> A flat vector illustration of a small stone hearth or fireplace arch with a contented fire burning
> inside it. Witchy but playful, rounded shapes, warm rather than grand. Thick confident outlines in
> warm violet (#a855f7); stonework filled near-black (#0a0a0a); flames pale green (#22c55e).
> Centred in a square frame with generous margin. Solid flat cyan (#00FFFF) background, one uniform colour edge to edge. Flat colour only — no
> gradients, no shading, no texture, no drop shadow, no text. Simple enough to read clearly at 40
> pixels.

## 14 · moon-reel

> A flat vector illustration of a film reel seen face on, where the sprocket holes around its edge
> are crescent moon shapes instead of circles. Witchy but playful. Thick confident outlines in warm
> violet (#a855f7); reel filled near-black (#0a0a0a); crescent holes off-white (#fafafa); centre hub
> pale green (#22c55e). Centred in a square frame with generous margin. Solid flat cyan (#00FFFF) background, one uniform colour edge to edge. Flat
> colour only — no gradients, no shading, no texture, no drop shadow, no text. Simple enough to read
> clearly at 40 pixels.

## 15 · two-cats

> A flat vector illustration of two black cats sitting side by side facing the viewer, shoulders
> touching, their tails curling toward each other to meet in a loose heart shape at the bottom.
> Witchy but playful, rounded shapes. Thick confident outlines in warm violet (#a855f7); bodies
> filled near-black (#0a0a0a); four calm eyes in pale green (#22c55e). Centred in a square frame
> with generous margin. Solid flat cyan (#00FFFF) background, one uniform colour edge to edge. Flat colour only — no gradients, no shading, no
> texture, no drop shadow, no text. Simple enough to read clearly at 40 pixels.

---

## If a result drifts

The usual failures, and what to add to the prompt:

- **Too detailed to read small** — add *"extremely simplified, minimal detail, bold shapes only"*.
- **Came back on a checkerboard** — the prompt said "transparent" somewhere. It cannot be done in
  JPEG; ask for flat cyan. `extract-marks.py` will rescue the image either way.
- **Background is not one flat colour** — add *"the background must be a single uniform block of
  cyan, no gradient, no vignette, no shadow cast onto it"*.
- **Shaded or glossy** — add *"flat 2D vector art, completely flat fills, no lighting"*.
- **Wrong weight against the others** — name the one it should match: *"same line weight and level
  of detail as this"*, and attach an accepted mark.

Generate `cat` first and get it right. Once one is good, attach it to every subsequent prompt as the
style reference — matching a real image holds a set together far better than matching a description.
