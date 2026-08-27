# ADR-0010: Played Bytes Are Cached, Downloads Are Pinned

Status: proposed

Date: 2026-07-31

Extends [ADR-0009](ADR-0009-offline-downloads-are-background-transfers.md)

## Context

[ADR-0009](ADR-0009-offline-downloads-are-background-transfers.md) established that the engine
already downloads every track whole before playing it, and deletes the file when the next track
loads. It recorded keeping those bytes as a follow-up rather than deciding it, because bytes retained
because they happened to be fetched are a different thing from a track the listener asked for.

This ADR decides that follow-up. It should be read after ADR-0009 is accepted, and it can be rejected
without disturbing it — nothing in ADR-0009 depends on this.

**The mechanism is close to free, and smaller than the follow-up in ADR-0009 implied.** The engine
already distinguishes files it must delete from files it must leave alone:
`ManagedTempFile(url:owned:)` is constructed with `owned: true` on the two network paths
(`Sources/FamiliarKit/NativeAudioEngine.swift:814` for `load`, `:1274` for `preloadNext`) and
`owned: false` on the two local paths (`:840`, `:1317`), and `cleanupTempFile()` (`:1893`) honours the
flag. "Do not delete this one" is an existing concept.

What the engine lacks is a say in *where* the download lands: both network paths hardcode
`NSTemporaryDirectory()`. The right seam is therefore a destination provider — the engine asks for a
URL and an ownership flag, defaulting to today's tmp-and-owned behaviour — rather than a delegate
callback after the fact. `NativeAudioEngineDelegate` (`:144-160`) is entirely event notifications
(`audioEngineDidFinishPlaying`, `audioEngineDidUpdateAnalysis`, remote-command forwarding), so
notifying it post-hoc would mean a second move racing the cleanup it is trying to prevent.

**The policy is not free, and this is the whole reason this is a decision rather than a patch.** A
cache that is never evicted is a slow download of the entire library, so cached files must be
evictable. ADR-0009 point 10 says nothing is evicted automatically. Both are correct only if the
store holds **two classes of file with two different promises**, and that distinction has to be
explicit or it will be got wrong.

**The web client already has this distinction, and its one recorded bug is precisely a confusion
between the two classes.** ADR-0006 records it twice. In its Context: "`offlineScoring.ts` reads
`db.cachedTracks` — all cached metadata — rather than `db.offlineTracks`, so offline ambient can
select a track whose audio was never downloaded." And in its Implementation block, on the offline
radio path: "the manifest goes stale when a download is removed… metadata present, audio absent."
The Apple client is about to acquire the same two tiers. The lesson is not "avoid two tiers" — it is
that the boundary between them needs to be an invariant with a test on it, not a naming convention.

The honest value of this is narrower than "offline downloads" and worth stating plainly, because it
is what an approver should weigh: a play cache does **not** add offline capability. Anyone going
somewhere without a network downloads deliberately, which ADR-0009 covers. What it buys is
time-to-first-audio on a repeat play — a whole-file fetch replaced by nothing — and a corresponding
reduction in load on the NAS, which is also the CI runner. On the local network that saves a second
or two per repeat play. Over Tailscale from outside the house, where a hi-res FLAC is tens of
megabytes, it is the difference between a pause and an instant start.

**The size of that win was measured against the live database rather than assumed, and the
measurement does not settle it.** Two tables answer different questions and disagree, which is the
most useful thing found here:

| Measured on the production database, 2026-07-29 | Value |
|---|---|
| Library | 26,462 tracks |
| `profile_play_history` span | 175 days (2026-02-04 → 2026-07-29) |
| Plays, distinct tracks played | 6,206 plays over 2,564 tracks — 2.42 plays per track |
| Bytes transferred to serve those plays | **99 GB**, against **37 GB** of distinct audio |
| Mean track size | 14.7 MB |
| Share of plays in the top 10 / 100 / 500 tracks | 5.4% / 20.9% / 49.4% |
| `play_events` span | **2 days** (2026-07-27 → 2026-07-29), 549 events |

So **63% of all bytes the server has ever sent for playback were re-sends of a file it had already
sent** — 62 GB of 99 GB. That is the strongest available argument for caching, and it is a lifetime
aggregate.

It does not follow that a bounded cache recovers much of it, and that is the trap this table exists
to avoid walking into. A 175-day aggregate has no ordering, so it cannot distinguish a track played
five times this week from one played once every five weeks; an LRU cache sized for a phone captures
the first and evicts its way straight past the second. The distribution is also flatter than "the
same few songs over and over" implies — the top 10 tracks are 5.4% of plays, and it takes 500 tracks
(≈7.3 GB at the mean size) to reach half.

The only ordered data is `play_events`, and it is **two days long**, because ADR-0004 landed on
2026-07-27. Simulating LRU over its real sequence gives a 5.5% hit rate at a 0.5 GB budget, 10.7% at
2 GB, and saturating at 13.3% — that last figure being not a cache limit but the total amount of
repetition present in the window. Those numbers are also drawn from the exact days the Swift client
was being developed and tested against this library, so they describe a developer exercising a player
at least as much as a listener using one. **Neither dataset supports a confident hit rate, and this
ADR does not claim one.** What is certain comes from the code rather than the data: today every play
re-downloads the whole file, and 63% of historical playback bytes were re-sends.

This is a case where the ordering principle in `CLAUDE.md` — start anything that accumulates data
over wall-clock time as early as possible — pays out precisely as intended. ADR-0004 was sequenced
second for exactly this reason, and a few weeks of ordinary use will answer the locality question
that two days cannot.

## Decision

The download store holds two classes of file: **pinned** (explicitly downloaded) and **cached**
(retained because it was played). They differ in exactly one respect — whether the store may delete
them.

1. **The engine gains a destination provider, not a delegate callback.** A closure supplied at
   construction answers `(trackId, fileExtension) -> (URL, owned: Bool)`, consulted by both network
   paths. Its default is `NSTemporaryDirectory()` with `owned: true`, which is today's behaviour
   exactly, so the engine's shipped semantics are unchanged when nothing supplies one.

2. **Pinned and cached files live in separate directories** — `Application Support/Downloads/` from
   ADR-0009 point 2, and `Application Support/Cache/` — rather than one directory with a flag in the
   index. ADR-0009 point 4 makes the filesystem the truth and the index a cache of it; a class
   distinction that exists only in the index contradicts that, and reconciliation could not repair
   a mislabelled entry because there would be nothing to compare it against.

3. **Cached files are evictable, pinned files are not.** Eviction is least-recently-played first,
   under a byte budget, and touches `Cache/` only. This does not reverse ADR-0009 point 10: that
   promise is about tracks the listener asked for, and it continues to hold without exception.

4. **The offline set posted to ADR-0006's manifest is the pinned set only.** Cached tracks are
   invisible to ranking. Including them would tell the server to rank toward tracks that eviction
   may remove, which is the stale-manifest failure ADR-0006's Implementation block records —
   reintroduced on a new client, having been written down as a lesson on the old one.

5. **Cached tracks do not appear in the downloads list.** ADR-0009 point 9 makes that list the
   offline browse surface, and everything on it must still be there later. A cache entry is a
   latency detail, not a promise, and surfacing it as a download would make eviction look like data
   loss.

6. **An explicit download of an already-cached track promotes the file rather than re-fetching it.**
   A rename between two directories on the same volume, and the common case for "I liked this,
   keep it".

7. **Preloaded-but-skipped tracks are cached too.** `preloadNext` (`:1274`) has already paid for the
   bytes by the time the listener skips past the track; discarding them is the one case where the
   current behaviour is unambiguously wasteful.

8. **The invariant is a test, not a convention:** nothing in the pinned set is evictable, nothing in
   the cached set reaches the manifest or the downloads list. This is the boundary the web client got
   wrong once already.

## Alternatives Considered

- **Do nothing; rely on explicit downloads.** Rejected, but it has a real case and is the option to
  take if the second residency class is judged not worth its complexity. Explicit downloads already
  cover every offline scenario; this only improves repeat plays while connected. The case for acting
  is that the mechanism is a destination closure and a directory, while the benefit lands on exactly
  the tracks a listener plays most.
- **Cache into `NSTemporaryDirectory()` and simply stop deleting.** Rejected. The system purges tmp
  at its own discretion, so the cache would evaporate unpredictably — and worse, the same directory
  would then hold both files the engine owns and files it does not, which is how a purge takes out
  something the index still lists.
- **One directory, with the class recorded in the index.** Rejected, per decision point 2: it puts
  the distinction somewhere reconciliation cannot verify it, in a design whose stated principle is
  that the filesystem is the truth.
- **Let cached tracks count toward the offline set.** Rejected. It is superficially attractive —
  more tracks rankable offline for free — and it is the exact bug ADR-0006 documents. A larger
  offline pool built from bytes that may be evicted is worse than a smaller honest one.
- **Cache on a `NativeAudioEngineDelegate` callback after the load completes.** Rejected. The
  protocol is event notification, and the file has already been moved into tmp by then, so this buys
  a second move racing `cleanupTempFile()` for no benefit over choosing the destination up front.
- **A single unified store with no promise about permanence, evicting anything under pressure.**
  Rejected. It collapses the two classes by giving up the guarantee that makes explicit downloads
  worth having, which is the one thing ADR-0001 went native to deliver.

## Consequences

- **Positive:** Repeat plays start instantly, and the tracks that benefit are automatically the ones
  played most. No user-facing feature, no setting, no intent to express.
- **Positive:** Fewer whole-file fetches against the NAS, which also hosts the CI runner and has
  been observed starving music streaming during heavy CI.
- **Positive:** The wasteful case where a preloaded track is skipped and its bytes thrown away
  disappears.
- **Positive:** The engine's default behaviour is untouched — the provider defaults to tmp and
  owned, so a caller that supplies nothing gets exactly what ships today.
- **Tradeoff:** The store now has two classes of residency, and every future feature touching it has
  to know which one it means. That cost is real and is the reason to reject this if the latency win
  is judged too small.
- **Tradeoff:** Disk usage grows silently up to the cache budget without the listener asking for
  anything. The budget must be visible and adjustable, or it becomes a support question.
- **Tradeoff:** "Is this track available offline?" now has two answers depending on who is asking —
  the manifest and the downloads list say pinned, the player says pinned-or-cached. That is correct
  but it is a distinction that invites bugs.
- **Follow-up:** Choose the cache budget **from measured locality, not from the lifetime aggregate**.
  Re-run the LRU simulation over `play_events` once it covers a month or more of ordinary use rather
  than two days of client development, and pick the budget where the hit-rate curve flattens. If that
  curve turns out to flatten below roughly 15%, the "do nothing" alternative above is the better
  answer and this ADR should be superseded rather than implemented — the measurement is the thing
  that decides it, and the data to make it will exist without any further work.
- **Follow-up:** Decide whether the budget is a fixed size or a fraction of free space. A fixed
  default is easier to reason about; a fraction survives moving to a smaller device.
- **Follow-up:** Decide whether eviction is least-recently-played or least-recently-*started*, once
  ADR-0004's listening events are recorded natively — the store would otherwise need its own
  timestamp for something the event stream already knows.
