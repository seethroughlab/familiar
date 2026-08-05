# ADR-0030: The Apple Clients Scrobble

Status: proposed
Date: 2026-08-05

Extends [ADR-0014](ADR-0014-the-generated-surface-widens-to-management.md) and
[ADR-0004](ADR-0004-listening-feedback-is-event-sourced.md)

## Context

**Playing music in the Mac or iPhone app contributes nothing to Last.fm.** The same album played in
a browser scrobbles normally. Nothing anywhere says so.

The server has the capability and has had it all along. `backend/app/api/routes/lastfm.py` exposes
six operations — `/status`, `/auth`, `/callback`, `/disconnect`, `/now-playing`, `/scrobble` — and
the web client drives them from `hooks/useScrobbling.ts`, which implements Last.fm's rules directly:
at least 30 seconds played, then a scrobble at `min(duration / 2, 4 minutes)`, once per play, with a
now-playing update when the track changes.

The Apple clients cannot reach any of it. `lastfm` is not among the eleven tags in
`Sources/FamiliarAPI/openapi-generator-config.yaml`, so no Swift method exists — and there is no
generic web view in the app to reach it through either. This is the same shape as the three defects
ADR-0017 records and the two ADR-0025 closed: **a capability the server has and a client cannot
reach, failing silently.**

**A premise worth correcting before it is assumed.** `POST /tracks/{id}/play` looks like it might
scrobble as a side effect — the native reporter calls it, and its docstring talks about scrobble
thresholds. It does not. It increments `play_count`, updates `last_played_at` and writes a
`completed` `PlayEvent`; the mention of thresholds is describing *when the client should call it*,
not what the server then does. Nothing in `backend/app/` calls the Last.fm service except the
`/lastfm/*` routes themselves.

**The native client reports differently from the web one, and that turns out to help.**
`ListeningReporter` acts on a completed `PlaybackReport` — `.natural` becomes `recordPlay`, `.user`
and `.error` become `recordSkip` — where the web runs a mid-playback effect. The report already
carries `playedSeconds`, `trackDuration`, `completionRatio` and `happenedAt`, which is everything
Last.fm's threshold needs, and it already flows through `ListeningEventQueue`: an on-disk,
at-least-once outbox holding up to 1,000 events across launches. The web client had to build a
separate outbox (`syncService`) to get the same guarantee.

## Decision

1. **The generated surface widens to `lastfm`.** Six operations, following ADR-0014's precedent —
   the same config change, for the same reason: the client cannot call what is not generated.

2. **A scrobble is derived from the completed play report, not from a mid-track timer.** When
   `ListeningReporter` sends `recordPlay`, it also sends `/lastfm/scrobble` for the same event.
   Nothing new observes playback; nothing new has to be kept in sync with the transport.

3. **This is exact rather than approximate, because the endpoint accepts a backdated timestamp.**
   `lastfm.py` computes `timestamp = request.timestamp or int(time.time())`, so passing the event's
   `startedAt` records the scrobble at the moment the track began — which is what Last.fm wants and
   what the web client already sends. Scrobbling after the fact is therefore not a compromise.

4. **Last.fm's thresholds are evaluated against the report, and stay identical to the web's:** at
   least 30 seconds played, and `playedSeconds >= min(trackDuration / 2, 240)`. Reaching the end of
   a track is not on its own sufficient — a 20-second interlude played to completion is a play but
   not a scrobble, and the two counts should not silently disagree between clients.

5. **Now-playing is the exception and fires when a track starts.** It is a statement about the
   present — "this is playing right now" — and cannot be reconstructed afterwards. `FamiliarPlayer`
   has `onPlaybackEnded` and no counterpart, so this adds one.

6. **Now-playing is best-effort and is never queued.** A now-playing update replayed from an offline
   outbox an hour later is a lie about the present, and Last.fm expires it after a few minutes
   regardless. It is sent if it can be sent and dropped otherwise. Scrobbles go through the queue;
   these do not.

7. **Nothing is sent, and nothing is queued, unless `/lastfm/status` reports both `configured` and
   `connected`.** The two are different failures — the server has no API keys, versus this profile
   has no session — and neither is this client's to fix. Queuing scrobbles for a profile that has
   never connected would fill a 1,000-event outbox with events that can never drain, evicting real
   ones. This is ADR-0022 point 3's rule applied to a surface with no interface: **absence means do
   not send**, not disable a control.

8. **No connect flow, and no settings pane.** Connecting an account is an OAuth round trip through
   `/lastfm/auth` and `/lastfm/callback` — server configuration a listener does once, which
   ADR-0013 point 4 keeps in the web app. The Apple clients consume the connection; they do not
   establish it.

9. **Verification is in three layers.** The threshold rule is pure and unit-tested in `FamiliarKit`
   against a `PlaybackReport` — including the interlude case from point 4, which is the one a naive
   implementation gets wrong. The queue-and-drain path extends the existing `ListeningEventQueue`
   tests. And a real scrobble is confirmed by hand against a connected account, because the failure
   this fixes is invisible from inside the app: everything looks identical whether or not the
   scrobble lands.

## Alternatives Considered

**Scrobble server-side when `/tracks/{id}/play` arrives.** By far the most attractive alternative:
one implementation, and every client — including any future one — gets scrobbling for free without
touching the generated surface. Rejected because the web client already calls both endpoints itself,
so the server doing it too would double-scrobble every track played in a browser; fixing that means
changing the web client in the same breath, which turns a client feature into a cross-client
migration. It also couples two things ADR-0004 deliberately separates: `recordPlay` is the *taste*
signal, and its threshold is free to move for reasons that have nothing to do with Last.fm's rules.
Worth revisiting if a third client ever appears — at that point the duplication argument wins.

**Port `useScrobbling` faithfully — a mid-playback observer with its own timers.** Rejected because
it needs a new hook into the transport, duplicates threshold logic the report already contains, and
would need its own persistence to survive a quit. The native app already has the outbox; a
mid-track observer cannot use it, because there is no completed event to queue.

**Queue now-playing along with scrobbles, for symmetry.** Rejected on the merits: the two have
different truth conditions. A scrobble is a historical fact and stays true; a now-playing update is
a claim about this moment and rots in minutes. Sending a stale one would misreport the listener to
anyone looking.

**Build the Last.fm connect flow natively too.** It is only two endpoints. Rejected because it is an
OAuth callback — a browser round trip and a redirect target — and ADR-0013 point 4 already draws
this line: a server has one configuration, and there is no per-client value in a second editor for
something done once.

**Do nothing; the web app is where scrobbling happens.** The status quo, and defensible if the Mac
app were incidental. It is not — the Mac and phone are the listening path by ADR-0001, so the
clients that do almost all the listening are the ones contributing nothing.

## Consequences

- **Positive.** Listening on the Mac and the phone reaches Last.fm, which for a listener with an
  account is the difference between a scrobble history that reflects what they played and one that
  reflects which client they happened to use.
- **Positive.** Offline listening scrobbles when the network returns, at the correct original
  timestamps, because it rides an outbox that already exists and already survives launches. The web
  client needed a second mechanism for this; the Apple clients get it free.
- **Positive.** No new observer of playback. Everything hangs off the report the reporter already
  receives, so there is nothing extra to keep in step with the transport.
- **Tradeoff.** A scrobble now arrives when the track *ends* rather than halfway through. The
  timestamp is correct either way, so the history is identical — but "now playing" and "scrobbled"
  are further apart in wall-clock time than a Last.fm user may expect, and a track abandoned at 90%
  scrobbles at that point rather than at the halfway mark.
- **Tradeoff.** The generated surface grows again. ADR-0014 widened it once for management; this
  widens it for a single listening integration, and the pattern of "widen for one feature" is worth
  watching before it becomes the whole schema.
- **Follow-up.** `lint_openapi.py` carries `NOT_GENERATED = {"ambient", "outputs"}`, which is
  **declared and never referenced**, and its docstring describes an exclusion set of two when twenty
  tags are excluded. Nothing compares the backend's `GENERATED_SURFACE` to the Swift config's
  `filter.tags`; the two claim to enforce each other in comments only. Adding a tag makes that drift
  worse and is the moment to fix it.
- **Follow-up.** `queue` remains in the generated surface with **zero callers** after ADR-0028
  removed queue sync. It should leave when the list is next revised.
