# ADR-0064: Visualizers Declare Affinity, and the Server Ranks Them

Status: accepted

Date: 2026-08-17

Extends [ADR-0034](ADR-0034-visualizers-are-drop-in-bundles.md), whose manifest this adds one
optional block to. Everything `0034` decided — the IIFE format, evaluation only inside the web view,
two sources, the refusal rules — stands unchanged. Independent of
[ADR-0062](ADR-0062-the-site-adopts-a-static-site-generator.md) and
[ADR-0063](ADR-0063-the-visualizer-api-is-published-for-outside-authors.md), and should ship before
them so the manifest is settled before it is published.

## Implementation

Points 1–10 shipped on `adr/open-visualizer-platform`, in four commits. The `familiar-apple` half —
the catalog carrying `affinity` so the native host can send candidates — is the remaining follow-up,
and `docs/WEB-PARITY.md` carries the row marked **not a blocker** until it lands, so shipping the
web half first does not extend the web player's countdown under
[ADR-0060](ADR-0060-the-players-removal-trigger-must-be-reachable.md) point 1.

**Point 9 needed no backend work**, which this ADR did not know. `GET /tracks/{id}` already
populates all fifteen `TrackFeatures` fields and `tracksApi.get` already wraps it. The trap was the
obvious fix: `playerStore.currentTrack` comes from `tracksApi.list`, which fills `features` only
when the caller passes `include_features`, and the only caller that does is the track-list browser.
Passing `currentTrack.features` would have worked on exactly one screen.

**Point 10's endpoint went under the existing `tracks` tag**, not a new `visualizers` one. That
avoids editing `VENDORED_TAGS` and the Swift generator config, and since `tracks` is already in the
generated surface the operation reaches the Apple clients on the next regeneration with no
cross-repo change.

Four things were decided here that the ADR left open:

1. **Unrecognised means excluded from the denominator, not scored zero.** Point 3 said "inert" and
   the arithmetic had to make it true: a typo in an optional field must not change a score at all.
   Nothing declared, and a track with no mood tags, both score neutral rather than last — but
   declaring something that does *not* fit can lose to declaring nothing, so there is no advantage
   in claiming everything.
2. **`music-video` declares no affinity, deliberately.** Point 4 says the built-ins declare too, and
   this one has nothing honest to say: it plays a video rather than drawing the audio, so no
   property of the analysis makes it more apt.
3. **`instrumentalness` and `speechiness` are not used as signals**, though they are the obvious
   choice for the two lyric visualizers. The detector finds speech rather than singing, so it does
   not separate an instrumental track from a sung one; the CLAP-derived `vocal/choir` tag is the
   better proxy. This is now recorded in `VISUALIZER_API.md` so a plugin author does not repeat it.
4. **A manual pick switches auto-select off.** Point 7 forbids silently overriding a chosen
   visualizer, and leaving the toggle on would have let the *next* track do exactly that.

**One defect this created and the ADR did not anticipate.** Auto-select introduces a second answer
to "which visualizer is on", and `FullPlayer` gates its whole layout on whether Music Video is
playing — read from the stored id, so an auto-selected Music Video would have drawn album art over
a playing video. Resolved with one shared `useActiveVisualizerId`; the lesson is the general one,
that adding a second source for an existing answer means auditing every reader of the first.

## Context

**A visualizer is currently a setting somebody picks once.** The whole of the state is one id, and
the two clients disagree about its default: the web app persists `visualizerId` and `glowLevel`
under the zustand key `familiar-visualizer` in `stores/visualizerStore.ts`, defaulting to
`reactive-terrain` per `components/Visualizer/constants.ts`; the Apple clients keep a per-profile
`visualizerID` in `UserDefaults` with `VisualizerChoice` in `ServerConfiguration.swift` defaulting
to `beat-tiles`. **There is no per-track association of any kind, on any client.** Nothing in
Familiar has ever asked which visualizer suits a song.

**The analysis half of the visualizer contract is already built and connected to nothing.**
`VisualizerProps` declares `features: TrackFeatures | null`; `AudioVisualizer` defaults it to
`null` and forwards it to the chosen visualizer. **Neither call site passes it.** `FullPlayer.tsx`
supplies `track`, `artworkUrl`, `lyrics`, `isPlaying`, `currentTime` and `duration`;
`EmbedVisualizer.tsx` supplies `track`, `artworkUrl`, `isPlaying` and `currentTime` — and no
`lyrics` either. `ReactiveTerrain` is the only visualizer that reads `features`, for `valence` and
`energy`, and therefore always takes its `?? 0.4` and `?? 0.5` fallbacks. The documented,
first-class, analysis-driven half of the API has never run.

`EmbedVisualizer` is worse than the summary suggests: it constructs a partial `Track` with an
`as Track` cast from `{id, title, artist, album}`, so on the surface the Apple clients actually
use, **no analysis reaches a visualizer at all**. This is the "consumer with no producer" shape,
and it means a feature that matches visualizers to songs must first make the song's analysis
present on the surface where the matching would be visible.

**The vocabulary to match against already exists and is already computed.**
`backend/app/services/mood_tags.py` holds **48 CLAP descriptors — 16 mood, 16 genre, 8
instrumentation, 8 energy** — scored by cosine similarity between a track's CLAP audio embedding
and pre-computed text embeddings of each descriptor, and stored on `TrackAnalysis.mood_tags` as
JSONB with a GIN index (`ix_track_analysis_mood_tags`). Beside it, `ANALYSIS_FEATURE_COLUMNS` lists
28 typed columns including `energy`, `valence`, `bpm`, `danceability`, `brightness` and
`instrumentalness`, several separately B-tree indexed. Nothing new has to be extracted or analysed
for this feature; the numbers are on disk for every analysed track.

Two pieces of prior art are worth naming so they are not re-derived.
`services/smart_playlists.py` already implements tag matching against this exact column, through a
`mood_tag` pseudo-field that compiles to a JSONB containment test. And `services/generative_art.py`
already maps aggregated `TrackAnalysis` features onto visual output, deterministically, to render
album art — features-to-visuals is not a new idea in this codebase.

**There is a seam for this with nothing on either end.**
`backend/app/services/playback_commands.py` declares `"visualizer"` in `KNOWN_CAPABILITIES`, the
command-channel vocabulary of [ADR-0044](ADR-0044-mcp-clients-actuate-playback-through-a-command-channel.md)
and [ADR-0053](ADR-0053-the-command-channel-drives-and-observes-the-interface.md). Nothing in the
backend emits a visualizer command and nothing handles one; the string appears once in the entire
repository. It was declared in anticipation and never used.

**[ADR-0029](ADR-0029-the-server-stores-no-listener-preferences.md) constrains the shape of any
server-side answer, and it is the reason this ADR looks the way it does.** Point 4: the server
stores no listener preferences, and the chosen visualizer is one. Point 5 is the harder
constraint — device identity stays uninvented, `Profile.device_id` has no readers, and *"anything
device-scoped is local by construction, because the server has no key to file it under."* **The
server therefore cannot know which visualizers a given device has installed**, because `0034` point
4 puts local bundles in a directory on that device and tells the server nothing about them.

## Decision

1. **`familiar-plugin.json` gains an optional `affinity` block, declared by the author.** It carries
   tags the visualizer suits and ranges over the numeric feature columns — the shape a picker would
   need to explain its choice. Author-declared rather than derived, because the author is the only
   party that knows a visualizer needs lyrics, or looks wrong below 90 bpm.

2. **The block is optional, and `apiVersion` stays 1.** Stated explicitly because `0034` point 7
   refuses any manifest declaring a version the host does not implement — and, as implemented,
   refuses one declaring no version at all. Bumping to 2 for an additive field would refuse every
   bundle that exists, including both working samples, to add a feature none of them uses.

3. **The matcher scores what it recognises and ignores the rest.** A tag outside the 48-descriptor
   vocabulary, or a range over a column that does not exist, is inert — it contributes nothing and
   refuses nothing. `0034`'s refusal taxonomy is for bundles that *cannot run*; a tag the server
   does not understand is not that, and refusing a working visualizer over a typo in an optional
   field would be the worst trade in the feature. The ignored entries are surfaced in the picker,
   reusing the refusal display `0034` already built, so an author can see what did not land.

4. **The five built-in visualizers declare affinity too.** Otherwise the ranker holds five
   unlabelled candidates and one labelled plugin, and the plugin wins every track by default — a
   scoring artefact that would be indistinguishable from favouritism, and one that gets worse the
   better the built-ins are.

5. **The client sends its candidates and the server ranks them.** The client posts the visualizer
   ids and affinity blocks it actually has loaded, together with a track id; the server scores them
   against that track's `TrackAnalysis` and returns an ordering with a reason per entry. **This is
   forced by `ADR-0029` point 5 rather than preferred**: the server has no device identity, so it
   cannot know what is installed, and a ranking over visualizers the listener does not have is not
   a ranking. The catalog the page already publishes as `window.__familiarVisualizers` is the
   source of that list.

6. **The server stores nothing.** The endpoint is a pure function of the posted candidates and the
   track's analysis. The chosen id, and whether auto-select is on at all, stay on the device as
   listener preferences under `ADR-0029` point 4. A server that ranked *and remembered* would
   reopen `0029` for a screensaver.

7. **Auto-select is a mode, off by default, beside the existing manual choice.** A listener who has
   picked a visualizer has expressed a preference, and silently overriding it is not a feature. The
   manual picker keeps working exactly as it does now.

8. **The choice is made when a track starts and holds for that track.** No mid-song switching: a
   three.js scene tearing down and rebuilding halfway through a song is more disruptive than an
   imperfect match is dull, and `TrackAnalysis.section_count` would make it tempting. A hysteresis
   rule keeps the current visualizer through a run of similar tracks unless another scores
   meaningfully higher, so a playlist of near-ties does not alternate between two of them.

9. **`VisualizerProps.features` is wired at both call sites as part of this work**, and
   `EmbedVisualizer` stops constructing a partial `Track` by cast. This is a decision point rather
   than an implementation detail because it is the prerequisite for everything above, because it is
   currently invisible, and because it is worth doing on its own: it makes the documented API real
   for hand-picked visualizers whether or not anything ever auto-selects.

10. **The endpoint is typed and joins the generated surface**, per
    [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md) points 2 and 4 — a real Pydantic
    response model, no bare `dict`, a tag, and no addition to the lint's burn-down list. The
    `"visualizer"` capability already declared in `playback_commands.py` is **left alone**: this is
    a client asking a question and getting an answer, not the server actuating a client, which is
    what the command channel is for.

## Alternatives Considered

- **Enforce a closed vocabulary, refusing any manifest whose affinity tags are not among the 48
  descriptors.** Every declaration would then be checkable, matchable and consistent, and authors
  would get an error at install time rather than silence. Rejected because it refuses a working
  visualizer for a soft reason: `0034`'s refusals are reserved for bundles that cannot run, and a
  misspelled optional tag is not that. Point 3 gets the same guidance from the picker without the
  refusal.

- **Embed each visualizer's description with CLAP's text encoder and rank by cosine similarity
  against the track's own embedding.** Genuinely elegant, needs no new manifest field at all, and
  costs almost nothing to build — `mood_tags.py` already computes exactly this shape of similarity
  against pre-computed text embeddings. Rejected because an author can neither predict nor control
  the result, and has no way to say "never use me for solo piano". A declared block is a contract
  the author can reason about; an embedding of their marketing copy is a guess they cannot correct.

- **Learn the match from what listeners actually keep on, per
  [ADR-0004](ADR-0004-listening-feedback-is-event-sourced.md)'s shape.** Needs no declarations,
  cannot be gamed by an author's optimism, and would get better over time. Rejected because it is
  cold at launch and there is no event stream for visualizer choice to make it warm — and `0004`'s
  own history is the measure of that cost, since `play_events` only became trustworthy on
  2026-08-01, months after the events started accumulating. Worth naming as the eventual refinement
  over declared tags rather than as a rejected idea.

- **Match on the client, from features the server already serves.** Works offline, needs no new
  endpoint, and the client is the only party that already knows what it has installed — which is
  the real objection to point 5. Rejected because the scoring rule would then exist in TypeScript
  and in Swift, and `0034` states the consequence from experience: *"Two copies of that rule in two
  languages is how the picker comes to disagree with what actually loaded."*

- **Derive affinity by inspecting the bundle.** No author burden at all. Rejected because an IIFE
  evaluated with `new Function` offers nothing meaningful to inspect, and a heuristic over minified
  source would be wrong in ways nobody could debug.

- **Let the LLM pick, through the MCP server of
  [ADR-0043](ADR-0043-the-llm-surface-is-an-mcp-server.md).** It already has the analysis tools and
  would give better-than-mechanical answers. Rejected because it makes a screensaver depend on a
  configured model and a network round trip per track, for a decision that has to be right within
  the first second of playback.

## Consequences

- **Positive:** Point 9 makes the documented `features` half of the visualizer API real for the
  first time, on both surfaces, whether or not auto-selection is ever switched on.
- **Positive:** Nothing new is analysed, extracted or migrated. Every input already exists on
  `TrackAnalysis` for every analysed track, and `FEATURES_VERSION` is untouched.
- **Positive:** A visualizer becomes a thing that can be *right for a song*, which is the argument
  for writing one — and it lands before `ADR-0063` publishes an invitation to write them.
- **Tradeoff:** Self-reported affinity will over-claim, and nothing can check it. This is the same
  shape as `0034` point 3's unenforceable contract about bundled React, and the only defence is the
  same one: documentation, plus the fact that an over-claiming visualizer is mostly punished by
  looking wrong.
- **Tradeoff:** A new endpoint is a new client-facing contract under `ADR-0007`, and casual changes
  to it get more expensive from the day it is generated.
- **Tradeoff:** The two disagreeing defaults — `reactive-terrain` in the browser, `beat-tiles` on
  the Apple clients — become visible the moment anything reasons about which visualizer is *right*.
  This ADR surfaces that disagreement without resolving it.
- **Tradeoff:** A track with no analysis, or one still awaiting a features re-run, has nothing to
  rank against. The behaviour has to be "keep the current visualizer", not "pick arbitrarily", and
  on a large library mid-sync that will be a meaningful fraction of tracks.
- **Follow-up:** The catalog published as `window.__familiarVisualizers` must carry the affinity
  block for the native host to forward it, which extends `VisualizerCatalog.swift` and the
  `evaluateJavaScript` probe `0034` added rather than adding a message handler. *The page half is
  done — the catalog carries `affinity`; the Swift half is what remains.*
- **Follow-up:** ~~`docs/VISUALIZER_API.md` documents the manifest and will need the `affinity`
  block before `ADR-0063` publishes it.~~ — done, along with the three defects that ADR names: the
  six absent components, `useAudioAnalyser`'s three sources, and the fifth reserved id. The 48-tag
  vocabulary is listed there and was verified against `mood_tags.DESCRIPTORS` at write time.
- **Follow-up:** The `"visualizer"` entry in `KNOWN_CAPABILITIES` remains declared and unused after
  this ADR, per point 10. It should either acquire a producer or be removed, and this is the second
  time it has been looked at and left.
