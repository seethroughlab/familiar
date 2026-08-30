# ADR-0030: Scrobbling Is the Server's Job

Status: accepted — point 1's "no client learns that Last.fm exists" superseded by
[ADR-0100](ADR-0100-connecting-an-account-happens-in-the-listeners-app.md)
Date: 2026-08-05

Extends [ADR-0004](ADR-0004-listening-feedback-is-event-sourced.md)

Implementation:
- Accepted 2026-08-05 and shipped the same day. Server half on `familiar` #103; point 6's client
  call on `familiar-apple` #74.
- Point 2's threshold rule is `backend/app/services/scrobble_policy.py` — pure, 40 lines, covered by
  `backend/tests/test_scrobble_policy.py` including the 60%-then-skipped case that distinguishes
  this design from the first draft. Point 4's out-of-band guarantee is
  `backend/app/services/scrobble_dispatch.py`, called from `/played` and `/skipped` in
  `api/routes/tracks/playback.py`. Point 6's `POST /tracks/{id}/started` is at `playback.py:346`.
- Point 5 was paid: `useScrobbling.ts` lost its scrobble call, and **six tests went with it rather
  than being made to pass**. The file records where that coverage moved and why, which is the part
  worth keeping — a deleted test is otherwise indistinguishable from a forgotten one.
- Point 8 held exactly: the Apple clients got scrobbling with no scrobbling code at all, and the
  start signal was one call on a tag they already had. On the client it is keyed on `trackEpoch`
  rather than the track id — the counter ADR-0031 added — because under `repeat one`, and in a queue
  holding one track twice in a row, the id never changes though the track genuinely restarts, and an
  id-keyed task falls silent in exactly those cases. Point 7's "never queued" is honoured by the
  reporter sending it directly rather than through `ListeningEventQueue`.
- Point 10's third layer was performed against the real account, in both directions: a `/started`
  call put a track up as NOW PLAYING, and scrobbles landed. The account's last scrobble before this
  was 31 July, which is the measure of what the gap cost.
- **Follow-ups.** `POST /tracks/{id}/started` still has one consumer. The Apple track-start hook
  the second follow-up asked for is now wired, via `trackEpoch` as predicted.

## Context

**Playing music in the Mac or iPhone app contributes nothing to Last.fm.** The same album played in a
browser scrobbles normally. Nothing anywhere says so.

The server has had the capability all along. `backend/app/services/lastfm.py` holds `scrobble` and
`update_now_playing`, and `get_stored_session` reads a per-profile session out of the database. Only
the `/lastfm/*` routes call any of it, and the web client is the only thing that calls those — from
`hooks/useScrobbling.ts`, which implements Last.fm's rules directly: at least 30 seconds played, then
a scrobble at `min(duration / 2, 4 minutes)`, once per play.

**A premise worth correcting before it is assumed.** `POST /tracks/{id}/played` looks like it might
scrobble as a side effect — the native reporter calls it and its docstring mentions scrobble
thresholds. It does not. It increments `play_count`, updates `last_played_at` and writes a
`completed` `PlayEvent`; the mention of thresholds describes *when a client should call it*.

**This ADR previously decided the opposite, and the reasoning did not survive being questioned.**
The first version had each Apple client scrobble for itself, widening the generated surface to
`lastfm` to do it. It rejected server-side scrobbling on two grounds, and both were weaker than they
read:

- *"ADR-0004 keeps `recordPlay` as the taste signal, whose threshold should move independently of
  Last.fm's rules."* That is an argument against **coupling the two thresholds**, not against the
  server owning the work. The server can compute Last.fm's rule from the event it already receives,
  ignoring entirely which endpoint delivered it.
- *"The web already calls both endpoints, so the server doing it too would double-scrobble."* True,
  and a migration rather than a principle: the web's call is deleted in the same change.

**What the events already carry settles it.** Both `/played` and `/skipped` accept `played_seconds`,
`track_duration`, `completion_ratio` and `started_at`. That is everything Last.fm needs, from every
client, including clients replaying a queue built while offline — `started_at` exists precisely
because an event reporting the moment it was uploaded misdates the only listening that needed
queueing.

**And the client-side design had a gap this one does not.** Last.fm scrobbles at half a track;
Familiar's `play_count` means *played to the end* (ADR-0004 point 4 keeps skips off the aggregate
deliberately). A track abandoned at 60% is therefore a **skip** to Familiar and a **scrobble** to
Last.fm. A design hanging off the play report alone silently misses those; the server sees
`/skipped` too.

The one thing that genuinely cannot move is now-playing. `/played` and `/skipped` both fire at the
*end* of a track, so **the server has no track-start signal at all** — and no rearrangement of
existing endpoints produces one.

## Decision

1. **The server scrobbles, from the listening events it already receives.** No client learns that
   Last.fm exists. `/played` and `/skipped` both feed it, because Last.fm's threshold and Familiar's
   definition of a play are different questions about the same event.

2. **Last.fm's thresholds are computed independently of ADR-0004's.** At least 30 seconds played,
   and `played_seconds >= min(track_duration / 2, 240)` — evaluated from the event's own fields,
   never from which endpoint delivered it. This is what keeps ADR-0004's play threshold free to move
   for reasons that have nothing to do with Last.fm, which is the one objection worth preserving
   from the first draft.

3. **`started_at` is the scrobble timestamp.** The API accepts a backdated timestamp
   (`timestamp = request.timestamp or int(time.time())`), so an event replayed from an offline queue
   scrobbles at the moment the listening actually happened. Offline listening therefore scrobbles
   correctly with no client-side work at all — the native `ListeningEventQueue` already holds up to
   1,000 events across launches and drains them with their original times.

4. **Scrobbling never fails, delays or alters a listening event.** It is out of band and
   best-effort. A Last.fm outage, an expired session, or a track missing an artist must not turn
   `/played` into an error: the listening record is the thing that matters and it is already written.

5. **The web client's own scrobbling is removed in the same change.** `useScrobbling`'s scrobble call
   goes, or every browser play scrobbles twice. This is the migration cost of the decision, and it is
   paid here rather than deferred.

6. **A new `POST /tracks/{id}/started`** — the track-start signal the server has never had. Clients
   call it when a track begins; the server forwards it to Last.fm as now-playing.

   Deliberately **not** `/lastfm/now-playing` reused. A client saying "this track just started" is a
   fact about listening, not about an integration, and the server is free to do more with it later.
   It also keeps the Apple clients from needing the `lastfm` tag for one cosmetic ping.

7. **Now-playing is never queued.** One replayed from an offline outbox an hour later is a lie about
   the present, and Last.fm expires it in minutes regardless. It is sent if it can be sent and
   dropped otherwise — unlike scrobbles, which are historical facts and stay true.

8. **The generated surface does not widen.** `tracks` is already generated, so the Apple clients get
   scrobbling with **no client change at all**, and the start signal is one call on a tag they
   already have. The first draft widened the surface to `lastfm` and noted in its own Consequences
   that "widen for one feature" was a pattern worth watching; this avoids the cost rather than
   justifying it.

9. **Connecting an account stays in the web app.** `/lastfm/auth` and `/lastfm/callback` are an OAuth
   round trip — server configuration done once, which ADR-0013 point 4 keeps out of a second editor.

10. **Verification is in three layers.** The threshold rule is pure and unit-tested against event
    payloads, including the 60%-then-skipped case that distinguishes this design from the first
    draft. The out-of-band guarantee is tested by making the Last.fm call fail and asserting
    `/played` still returns 200 and still writes its `PlayEvent`. And a real scrobble is confirmed by
    hand against a connected account, because nothing inside the app looks different whether or not
    it landed.

## Alternatives Considered

**Each client scrobbles for itself.** The first version of this ADR, described above. Not absurd — it
puts the decision next to the playback it describes, and the native `ListeningEventQueue` would have
carried offline scrobbles neatly. Rejected because it needs the generated surface widened for one
integration, needs the same logic in every current and future client, and misses the
60%-then-skipped case unless each client also learns to scrobble from its own skip reports.

**Scrobble only from `/played`.** Simpler: one endpoint, one rule. Rejected because it silently
under-reports. Familiar's play means "reached the end", Last.fm's means "half", and the gap between
them is a track someone listened to most of and then skipped — ordinary listening, not an edge case.

**Queue now-playing alongside scrobbles, for symmetry.** Rejected on the merits: the two have
different truth conditions. A scrobble is a historical fact and stays true; a now-playing is a claim
about this moment and rots in minutes.

**Reuse `/lastfm/now-playing` for the start signal.** Fewer moving parts, no new endpoint. Rejected
because it makes every client's track-start hook a Last.fm concept, and drags the `lastfm` tag into
the generated surface for one best-effort ping. A generic start signal is worth having on its own.

**Do nothing; scrobbling is what the web app is for.** The status quo, and defensible if the Mac app
were incidental. It is not — ADR-0001 makes the Apple clients the listening path, so the clients
doing nearly all the listening are the ones contributing nothing.

## Consequences

- **Positive.** Every client scrobbles, including the two that cannot today and any built later, with
  no client-side work.
- **Positive.** Offline listening scrobbles at its true timestamps for free, because the events
  already carry `started_at` and already survive being queued.
- **Positive.** Tracks abandoned past the halfway mark scrobble — which the web gets right today and
  the first draft of this ADR would have lost.
- **Positive.** No generated-surface widening, so the Apple side is a single new call rather than a
  new tag.
- **Tradeoff.** The web loses its own scrobbling and gains a dependency on the server doing it. A bug
  is then wrong everywhere at once, where today it would affect one client.
- **Tradeoff.** Scrobbles now arrive when a track *ends* rather than at the halfway mark. The
  timestamp is `started_at` either way, so the history is identical — but "now playing" and
  "scrobbled" sit further apart in wall-clock time than a Last.fm user may expect.
- **Tradeoff.** A listener with no Last.fm connection pays a session lookup on every play and skip.
  Cheap, and worth measuring rather than assuming.
- **Follow-up.** `POST /tracks/{id}/started` is a signal nothing else uses yet. It is the natural
  place to hang presence, listening-together, or a "recently started" feed — worth remembering before
  someone adds a second start signal beside it.
- **Follow-up.** The Apple clients have no track-start hook wired to anything; `trackEpoch`
  (ADR-0031) counts starts and is the obvious thing to drive this from.
