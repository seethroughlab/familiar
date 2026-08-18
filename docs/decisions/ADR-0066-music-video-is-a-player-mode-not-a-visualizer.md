# ADR-0066: Music Video Is a Player Mode, Not a Visualizer

Status: proposed

Date: 2026-08-18

Extends [ADR-0034](ADR-0034-visualizers-are-drop-in-bundles.md) by removing something from the set
it governs. The drop-in format, the two sources and the refusal rules are untouched; what changes is
that one of the five compile-time visualizers stops being one.

## Context

**`music-video` is in the visualizer registry and is not a visualizer.** It plays a YouTube video
instead of drawing the audio. That has been true since it was written, and it has been paid for in
four separate places — none of which looked like a symptom on its own.

- **It is the only visualizer id special-cased anywhere.** `FullPlayer.tsx` reads `isMusicVideo` in
  three places to decide whether to show inline artwork and what the content area contains. No other
  visualizer needs the surrounding interface to behave differently; a grep for the other four ids
  outside the registry, the picker and their tests returns nothing.
- **It is the only one registered `usesMetadata: false`.** It uses neither the artwork nor the
  analysis nor the lyrics — that is to say, nothing `VisualizerProps` exists to provide.
- **It is the only one that cannot declare affinity.**
  [ADR-0064](ADR-0064-visualizers-declare-affinity-and-the-server-ranks-them.md) shipped it with no
  affinity block on purpose, and said why: *"it plays a video rather than drawing the audio, so no
  property of the analysis makes it more apt — it is a different way of watching, not a scene that
  suits some music."* That is a description of something that does not belong in the set, written
  while adding a feature to the set.
- **It is the only one that reaches outside the plugin API**, importing `stores/playerStore` for the
  playhead.

**That last one is a live defect, not only a smell.** `MusicVideo` reads `currentTime` from
`playerStore`, and on the visualizer surface that store is never mounted — `renderVisualizer.tsx`
starts no player, because [ADR-0017](ADR-0017-the-embedded-surface-gets-a-null-audio-engine.md)
gives that page a null audio engine. So the value is 0 for the length of every track, and Music
Video's sync has been broken on the Mac and the phone since
[ADR-0033](ADR-0033-the-embed-bridge-gains-a-return-channel.md) put it there. `VisualizerProps`
already carries `currentTime`, correctly, on both surfaces.

**The feature underneath is real and larger than its one affordance.** `backend/app/api/routes/videos.py`
serves five endpoints — search, status, download, stream and delete — against
`backend/app/services/video.py`. All of that is reachable only by choosing a visualizer, which is
also the only way to *stop* watching, and which competes for a menu whose other entries are scenes.

**This was noticed from the outside.** The prompt was a question about why the visualizer folder did
not contain every visualizer, and the answer kept having to except this one.

## Decision

1. **The full player has three backgrounds, not two: artwork, a visualizer, or the music video.**
   `showsVisualizer` becomes a three-state mode rather than a boolean. This is what the interface
   already does — `isMusicVideo` exists precisely because the video needs different treatment — and
   it stops being expressed as a special case inside the visualizer that is not one.

2. **`music-video` leaves the visualizer registry.** Four built-ins remain: `reactive-terrain`,
   `beat-tiles`, `lyrics` and `lyric-storm`. Its id stops being reserved against plugins, and the
   ranking of [ADR-0064](ADR-0064-visualizers-declare-affinity-and-the-server-ranks-them.md) stops
   carrying a candidate that can never be scored.

3. **The video reads the playhead from the same place every visualizer does.** Whatever hosts it
   takes `currentTime` from the player on the web app and from the analysis frames when embedded —
   the two sources `VisualizerProps` already reconciles — rather than from `playerStore`, which is
   absent on the surface where the Apple clients run it. This is the defect above, and fixing it is
   part of this rather than a follow-up.

4. **It is a mode on every client, or it is browser-only and says so.** The `videos` tag is not in
   the generated surface, so the Apple clients reach the feature solely through the embedded page
   today. Whichever way this lands, `docs/WEB-PARITY.md` gets a row for it — it currently has none,
   which is how a feature with five endpoints came to have its reachability undiscussed.

5. **Nothing about the backend changes.** No endpoint moves, no route is renamed, no data migrates.
   This is a decision about where a feature is reached from, and the argument for it is that the
   present answer costs a special case in the player and an exception in every rule about
   visualizers.

## Alternatives Considered

- **Leave it where it is.** It works, people can find it, and moving it is churn against a feature
  nobody has complained about. Genuinely the cheapest option, and it is what has been chosen by
  default four times — once for each of the exceptions above. Rejected because the cost is not
  static: [ADR-0068](ADR-0068-built-in-visualizers-ship-as-drop-in-bundles.md) would have to convert
  it into a standalone bundle that needs the player store, which would force playback state into a
  public plugin API for the sake of one entry that is not a visualizer.

- **Keep it a visualizer but give it a real affinity block**, so at least it ranks. Rejected because
  there is no honest block to write: no property of a track's analysis makes a video more or less
  apt, which is the same reason `ADR-0064` shipped it declaring nothing.

- **Make it a fourth "source" of visualizers — a video plugin type**, alongside `visualizer` and the
  excluded `browser`. Rejected as the wrong axis: a plugin type describes who wrote something, and
  the problem here is what the thing *is*. It would also reopen `ADR-0034` point 9's boundary for a
  first-party feature, which is the argument that boundary exists to prevent.

- **Move it out of the full player entirely — a separate screen for music videos.** Arguably the
  most honest reading of "core feature", and it would give the five endpoints a surface of their
  own. Rejected as more than this decision needs: the video is something you watch *while a track
  plays*, so it belongs where the player is. A screen of its own is a product decision that can be
  made later on top of this one, and does not have to be made to fix the special-casing.

## Consequences

- **Positive:** Three special cases leave `FullPlayer`. The player says what it is showing instead
  of inferring it from which visualizer is selected.
- **Positive:** Music Video's playhead works when embedded, for the first time since it was
  embedded.
- **Positive:** Every rule about visualizers loses its exception — `usesMetadata`, affinity, the
  plugin API boundary, and the reserved-id list all become uniform over four entries.
- **Positive:** [ADR-0067](ADR-0067-the-plugin-api-exposes-what-a-first-party-visualizer-uses.md)
  gets substantially smaller, because the only built-in needing `playerStore` and the API client is
  the one leaving.
- **Tradeoff:** A listener who reaches Music Video by picking it from the visualizer menu will look
  for it there and not find it. That is a real relearning cost for the one affordance this feature
  has ever had.
- **Tradeoff:** `showsVisualizer` becomes a three-state value stored where a boolean was, per
  profile, on both platforms. An old stored `true` has to mean "visualizer" and not "video".
- **Tradeoff:** The native menu currently toggles the visualizer on press and picks one on hold.
  A third mode has to fit that shape without turning one glyph into three questions.
- **Follow-up:** Whether music videos become a destination of their own, per the rejected
  alternative. Five endpoints with one affordance is the kind of imbalance that usually means yes,
  and this ADR deliberately does not decide it.
- **Follow-up:** `docs/WEB-PARITY.md` has no row for music videos at all, and the `videos` tag is
  browser-only. Point 4 requires the row; whether the ❌s in it are blockers under
  [ADR-0060](ADR-0060-the-players-removal-trigger-must-be-reachable.md) is a separate question that
  the row will make askable.
