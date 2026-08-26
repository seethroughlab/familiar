# ADR-0040: Radio Comes to the Apple Clients

Status: accepted

Date: 2026-08-06

Extends [ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md).
Reverses [ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md) point 8's
"not user-configurable" for these clients.

Implementation:
- Accepted 2026-08-06 and built on `familiar-apple`. The Context's arithmetic held: no server
  change, no schema change, no generator change and no re-vendor. `queue` was already in the filter
  list with zero callers, and `ServerRadioSuggestionsSource` is that tag's first consumer since
  ADR-0028 emptied it.
- The split is `RadioSettings` (value), `RadioPolicy` (pure decisions — cadence, the `cursor + 2`
  offset, request building, both guards), `RadioController` (`@MainActor`, observes the player) and
  `FamiliarPlayer.insertSuggestion`, all in `FamiliarKit`; `ServerRadioSuggestionsSource` in `App/`
  translates and decides nothing. 27 unit tests plus a three-case live slice.
- **The controller keys on `trackEpoch`, not on the track id.** Point 13 did not anticipate this and
  it is the same trap ADR-0030 and ADR-0031 both hit: under `repeat one` the id never changes though
  the track genuinely restarts, and a queue holding one track twice in a row has the same problem,
  so an id-keyed cadence counter goes silent in exactly those cases. `trackEpoch` exists for this.
- **Point 5's marker needed a second set, which the ADR did not foresee.** `suggested` is what is in
  the queue *now* and drives the `✨` and the menu; `offeredThisSession` is everything ever
  suggested and is what the dedup consults. With one set, a rejected track — whose marker is removed
  as it leaves the queue — becomes eligible again and comes back round every few songs. The test
  that pins this rejects and then re-suggests.
- **Three wiring calls fail identically and silently**, and the tests found it before the app did.
  `attach(persist:initial:)`, `attach(source:)` and `observe(_:)` are each individually load-bearing,
  and the first draft of `RadioControllerTests` omitted the third: every `suggest()` returned quietly
  and six assertions failed at once. That is precisely what point 13's "a real listen is required"
  is about — all three omissions look identical from outside, and identical to radio being off.
  The test helper now wires all three and says why.
- Two runtime traps that the compiler cannot see were handled deliberately: `QueueView` is presented
  as a sheet on iOS and inherits nothing, so `radio` is handed over explicitly beside the four
  objects already there; and the macOS `Settings` scene is a separate hierarchy from the
  `WindowGroup`, so omitting it there would have trapped the moment the Playback pane was opened.
- Point 8's "never queued" is implemented as removal-first: the track leaves the queue whether or
  not the report succeeds, because a network failure must not leave a track sitting there that the
  listener has just said they do not want.
- The rejection's `context` turned out to be a **generated enum**, not a bare string, so `.radio`
  cannot be misspelled into silence the way the ranking profile's name can. The profile name is the
  one to watch: the live slice pins that `"RADIO"` returns a 400 rather than degrading quietly.
- Verified against the 26,396-track library on the NAS: suggestions decode and arrive in rank order,
  an unknown profile is a 400, and a rejection is accepted. 751 unit tests pass and both app targets
  build.
- **Not yet done: point 13's third layer.** A real listen — radio on, four tracks, a suggestion
  appearing with its marker, keep and reject both exercised — has not been performed. It is the one
  layer that cannot be automated and the one that matters most here, because every failure mode in
  this feature is silent by design.

## Context

Radio was reported missing — *"we used to have it and now I don't see it anymore"*. **Nothing was
removed.** It is intact in the web app and has never existed on the Apple clients, and that is worth
recording here because it is the second time a feature's absence from the native side has read as a
regression rather than as scope (the first was scrobbling, [ADR-0030](ADR-0030-scrobbling-is-the-servers-job.md)).

What exists in the web app today: `player/radio/radioController.ts` (231 lines) started from
`useAudioEngine.ts:274`, `stores/radioStore.ts` (24 lines, persisted to `familiar-radio`, **off by
default**), `components/Settings/RadioSettings.tsx` (47 lines) under Settings → Playback, and the
`✨` marker with keep/reject in `Queue/QueueView.tsx`. Its test is 383 lines. The server half is
finished: `POST /api/v1/queue/suggestions` ranks under the `radio` weight profile and answered
against the live 26,396-track library while this was being written.

**The generated surface does not need widening, and the reason is a footnote from ADR-0028.**
`queue_suggestions` carries the `queue` tag, and `queue` is in
`Sources/FamiliarAPI/openapi-generator-config.yaml`. ADR-0028 point 4 took the Apple clients out of
the server session and its follow-up recorded the leftover: *"the `queue` tag stays in the
generator's filter list, so `queueGetPlaybackSession` and its siblings are still generated with no
callers."* Verified — there are **zero** callers of any `queue*` operation in `App/` or
`Sources/FamiliarKit/`. Radio would be the tag's first consumer since ADR-0028 emptied it, which
turns a follow-up that read as debt into the thing that makes this cheap.

Note what does *not* come along: `ambient` is a separate tag and is **not** generated, being outside
ADR-0001 point 5's v1 scope. ADR-0005's one-engine design is what lets radio arrive without ambient
arriving with it.

**Four things about the native player constrain the design, and none of them are guesses.**

- **`PlayableTrack` has no room for a mark.** Five fields — `id`, `streamURL`, `title`, `artist`,
  `album` — and its doc comment states the rule deliberately: *"`FamiliarKit` does not depend on
  `FamiliarAPI` … nothing about playing audio requires a schema type."*
- **There is no insert-at-offset.** `playNext(_:)` inserts at `cursor + 1`
  (`FamiliarPlayer.swift:485`) and `addToQueue(_:)` appends or scatters (`:504`). ADR-0005's
  `INSERT_OFFSET = 2` exists because *"a suggestion that displaces the very next track reads as the
  app overriding them"*, and neither primitive lands there.
- **The web's shuffle defect cannot occur here.** `familiar` #31 fixed suggestions landing last in
  play order under shuffle: the web keeps a separate `shuffleOrder` array, so `addToQueue` needed a
  second position argument and without it a suggestion inserted "two ahead" went to the bottom of
  the list and was never reached. The native player permutes `queue` itself — `queue` **is** the
  play order and `logicalQueue` holds the original — so one index is both. `playNext` already shows
  the whole pattern, including keeping `logicalQueue` in step in each shuffle state.
- **There is no rejection path, and it does not fit the one that exists.** `ListeningReporter`
  sends `/played`, `/skipped` and `/started`. `QueuedListenEvent` carries `playedSeconds`,
  `trackDuration`, a `reason` and a `PlaybackStopReason` of `natural`/`user`/`error`. **A rejection
  is not a playback stop** — it is a judgement about a track that never played — so the offline
  queue's model has nowhere to put one.

**Two premises in ADR-0005 have drifted from what shipped**, recorded so nobody re-derives them.
Point 5 says the endpoint takes *"the current track, recent track and artist IDs"*; the shipped
`SuggestionsRequest` takes `recent_track_ids: list[UUID]` and `recent_artist_names: list[str]` —
names, not ids. And the profile's wire value is lowercase `radio`; `RADIO` is the Python constant
(`ranking_profiles.py:92`, with `name="radio"` at `:93`). A client sending `"RADIO"` gets a 400
naming both valid values, which is a good error but only if you read it.

## Decision

1. **Radio is built natively, on both platforms.** There is no screen to weigh, so ADR-0016 point
   1's embed test does not apply — radio is a controller, not a surface. Both platforms rather than
   the Mac first: ADR-0031 point 7 kept casting off the phone for a measured battery cost (a full
   decode running silently), and radio has no equivalent. The phone is the listening path
   (ADR-0013 point 2), so it is the surface radio is *most* for.

2. **The controller lives in `FamiliarKit` and holds cadence and insertion policy only.** No scoring
   on any client, ever — that is ADR-0005's entire point, and the reason ambient was not forked in
   the first place. `swift test` cannot see `App/`, and cadence, offset and the "already queued
   nearby" rule are exactly the decisions that belong in the package.

3. **The generated surface does not widen.** `queue` already carries `queue_suggestions`. No new
   tag, no lint burn-down, no `openapi.json` re-vendor — the same position ADR-0035 was in, and for
   the same reason.

4. **Radio is online-only, and the toggle says so.** With no server there is no ranking, and radio
   goes quiet rather than inserting an arbitrary track. A random insertion looks exactly like the
   feature working, which is the rule ADR-0035 point 6 set and ADR-0032 point 5 states generally.
   The offline manifest is considered and deferred below; this is a cost accepted in writing, not
   an oversight.

5. **A suggestion is marked, and the mark lives with the controller rather than on
   `PlayableTrack`.** The controller already tracks inserted ids to avoid stacking duplicates; the
   queue view asks it. This keeps a recommendation concept out of the audio layer's value type,
   which deliberately knows nothing about the API or about *why* a track is queued. The consequence
   is deliberate: marks do not survive relaunch, because ADR-0028's snapshot stores `PlayableTrack`.
   A suggestion that survived a quit was not rejected, and treating it as an ordinary queue entry is
   the honest reading.

6. **Insertion is at `cursor + 2`, through one new primitive shaped like `playNext`.** Not a
   generalised "insert at arbitrary index": the offset is a policy decision from ADR-0005, and the
   primitive should carry it rather than let each caller pick. It maintains `logicalQueue` in both
   shuffle states exactly as `playNext` does, so a suggestion is not lost when shuffle is switched
   off.

7. **Keep and reject are both offered, and reject reports `POST /tracks/{track_id}/rejected`.**
   ADR-0005 point 7 is load-bearing — a suggestion the listener cannot identify as one cannot be
   evaluated by them or learned from — so the marker and the two actions ship together or not at
   all. Rejection is weighted more heavily than a skip in the ranker because it is a stated
   judgement rather than an ambiguous one.

8. **A rejection is sent best-effort and never queued.** Unlike a play or a skip it has nowhere to
   live: `QueuedListenEvent` models a playback stop, and widening it to carry a judgement about a
   track that never played would change its shape for one caller. A dropped rejection costs a
   slightly worse ranking later, not a lost listening record — which is the opposite of the
   trade ADR-0030 point 7 made about now-playing, and for the same kind of reason: what the event
   *is* decides whether it is worth queueing.

9. **The toggle is device-local and lives in `PlaybackSettingsView`.** ADR-0029 settles where: the
   server stores no listener preferences. `PlaybackSettingsView` is one pane used by both
   `SettingsWindow` and `PhoneSettingsView`, so both platforms get it from one place — and the web
   app keeps its own answer, as ADR-0029 point 4 established for auto-download.

10. **Off by default**, matching the web and for the web's stated reason: radio inserts tracks the
    listener did not choose into a queue they are already enjoying, so turning it on should be their
    decision.

11. **The cadence is a setting, which reverses ADR-0005 point 8 for these clients.** That point
    fixed N at 4 and rejected a setting *"on the grounds that a preference nobody finds does not
    help"*, leaving N *"to be revisited once ADR-0004 data shows whether 4 is right"*. **That
    condition has not been met** — feedback only became trustworthy on 2026-08-01 (see ADR-0004's
    `FEEDBACK_TRUSTWORTHY_SINCE`) — and this reverses the decision anyway, as a change of mind
    rather than as a satisfied precondition. The reasoning: a listener who can turn radio on can
    reasonably say how often, and making them wait on a tuning exercise to change a number that is
    wrong for their library is the worse failure. The default stays 4, so nobody who ignores it sees
    a change, and the argument point 8 actually made is answered by placing the control next to the
    toggle rather than in a pane of its own.

12. **Radio runs wherever the player runs, including CarPlay, and there is no reject affordance
    there.** A suggestion appearing in the CarPlay queue is coherent; a keep/reject decision at
    speed is not. Stating it here so the absence is a decision rather than something discovered.

13. **Verification is in three layers.** Cadence, offset, the duplicate guard and the "already
    queued nearby" rule are pure and unit-tested in `FamiliarKit`. The endpoint is exercised by a
    live slice against a real server, as the weighted-shuffle slice is. And a real listen is
    required, because a suggestion that never gets inserted is invisible from inside a test — the
    controller stays silent on failure by design (point 4), which is exactly the condition that
    hides a broken one.

## Alternatives Considered

**Leave radio web-only.** Defensible on use: it is opt-in, off by default, and there is no evidence
anyone has been running it. Rejected on the same argument ADR-0030 made about scrobbling — ADR-0001
makes the Apple clients the listening path, so a listening feature that exists only in the browser
is absent from where the listening happens. It is also the shape of question that prompted this ADR,
which suggests the absence is felt.

**Port the offline manifest reader too, so radio works offline.** Genuinely attractive, and the
strongest case against point 4: the Apple clients are the downloads-first surface (ADR-0009), so
offline is where radio would matter most, and ADR-0006's `radio` manifest variant has been generated
and consumed by nothing since it landed. Rejected on cost for now. It needs local storage for the
neighbour lists, a refresh policy, and the rule that a suggestion must be filtered against what is
*actually downloaded* rather than what the manifest was built from — a distinction ADR-0006 already
got wrong once, reading `cachedTracks` (metadata) where it meant `offlineTracks`. Point 4 degrades
honestly meanwhile, and this is recorded as a follow-up rather than as settled.

**Put the `suggested` flag on `PlayableTrack`.** One field, and it would survive ADR-0028's snapshot
for free, which is the one thing point 5 gives up. Rejected because it puts a recommendation concept
into the audio layer's value type, whose doc comment exists to keep schema and playback apart. The
next thing wanting a per-entry annotation would add a second field on the same reasoning, and
`PlayableTrack` would become the queue's metadata bag.

**Offer suggestions as a separate "up next" strip rather than inserting into the queue.** No queue
mutation, no offset question, no marker-lifetime question, and a rejection becomes "did not pick it".
Rejected because it is a different feature: ADR-0005 point 6 chose insertion deliberately, and the
thing being copied from Spotify is that a track you did not choose *arrives*. A strip asks the
listener to choose, which is what the rest of the app already does.

**Reuse `playNext` at `cursor + 1` and skip the new primitive.** Zero new player surface. Rejected
by ADR-0005's own reasoning for `INSERT_OFFSET = 2`: displacing the very next track reads as the app
overriding the listener, which is the opposite of a suggestion.

**Keep the cadence a constant, as ADR-0005 point 8 says.** The more disciplined answer, and it has a
real argument now that ADR-0004's data has finally started accumulating: a setting lets each listener
tune around a number nobody has yet measured, which is how a wrong default survives. Rejected on the
listener's explicit request, and recorded in point 11 as a change of mind so the reversal is legible.

**Make the cadence a setting in the web app too, in the same change.** Consistency, and it would
avoid the divergence point 11 creates. Rejected as scope: this ADR is about the Apple clients, the
web's control has shipped and works, and changing both at once would put a UI change in the web app
inside an ADR nobody would look in for it. Recorded as a follow-up instead.

## Consequences

- **Positive.** The one feature that made daily listening feel like Spotify reaches the clients where
  the listening happens, with no server change, no schema change and no generated-surface widening.
- **Positive.** ADR-0028's leftover `queue` tag gets a consumer, so the follow-up that read as debt
  is answered by use rather than by deletion.
- **Positive.** The web's shuffle-order defect (`familiar` #31) cannot recur, because the native
  queue has one order rather than two. That is a class of bug removed by the existing design rather
  than by a guard.
- **Positive.** Point 2 keeps every ranking decision server-side, so radio on three clients is still
  one scorer — which is what ADR-0005 was written to protect and what makes a fourth client free.
- **Tradeoff.** **Radio does not work offline**, on the clients most likely to be offline. This is
  the second feature after embedded Discover with no offline story, and unlike Discover it has a
  known route to fixing it that is simply not being taken yet.
- **Tradeoff.** The suggestion marker does not survive a relaunch, so a suggestion sitting in the
  queue when the app quits comes back as an ordinary track with no keep/reject. Point 5 argues this
  is the honest reading; someone will still notice it.
- **Tradeoff.** A rejection made while offline is dropped rather than queued (point 8), so the
  ranker learns nothing from it. Every other listening event this app produces survives the network
  being away.
- **Tradeoff.** **The two clients now disagree about the insertion cadence** — the web's is a
  constant, the Apple clients' is a setting. Anyone comparing them will find radio behaving
  differently on one profile, and this ADR is the only place that says why.
- **Follow-up.** The offline manifest reader, per the second alternative. ADR-0006's `radio` variant
  is generated and has never been consumed by an Apple client.
- **Follow-up.** Bring the cadence setting to the web app so point 11's divergence closes.
- **Follow-up.** ADR-0005 point 8's actual open question — *is 4 right?* — remains open and is not
  answered by making it configurable. The tuning query must still apply
  `FEEDBACK_TRUSTWORTHY_SINCE`.
- **Follow-up.** ADR-0005 point 5's description of the request body is wrong in two places (see the
  Context). Its Decision is not edited; the correction belongs with the implementation record.
