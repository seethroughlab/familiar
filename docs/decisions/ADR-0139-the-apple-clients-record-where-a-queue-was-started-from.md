# ADR-0139: The Apple Clients Record Where a Queue Was Started From

Status: accepted

Date: 2026-09-30

Implementation:
- **Accepted 2026-09-30.** It records a decision Jeff made on 2026-09-29 ("there should be a way to
  easily return to the currently playing playlist", refined to "like CarPlay: always an icon in the
  top bar that takes you to the currently playing list"), which was built and shipped before it was
  written down.
- **Points 1–4 built** in familiar-apple #199 (the origin, the full player's "Playing from", the Mac
  bar menu's "Go to"), #200 (the top-bar button), #201 and #202 (legibility over light covers). On
  TestFlight as 1.5 builds 52–55, both platforms VALID, 2026-09-30.
- **Point 5 built** in familiar-apple #203, 2026-09-30; not yet merged or on TestFlight.
- **No server change.** Everything here is device state, and point 5 uses values `PlayContext`
  already accepts.

## Context

A listener who starts a playlist and then browses elsewhere had no way back to it from the
transport. The Apple clients did not know where their queue came from. The nearest thing was
`FamiliarPlayer.queueScope` (ADR-0120), which is `library | favorites` and deliberately nil for an
album or a playlist: it exists to re-draw a weighted shuffle, not to name a screen.

ADR-0003 point 8 defines a `queue_source` for the *server's* queue, in the web client's vocabulary
(`library | album | playlist | artist | ephemeral | other`). ADR-0035's follow-up records that these
clients never implemented it. The need here is narrower than ADR-0003's. It is not a fact about the
server's queue, and nothing else has to agree with it. It answers one question on one device: which
screen do I open to get back to what is playing?

ADR-0004's follow-up records the second cost of not knowing: every listening event the native app
sends carries `context = 'library'`, hardcoded, whatever was actually playing.

## Decision

1. **A queue records the screen it was started from, on the device.**
   `FamiliarPlayer.queueOrigin` is a `QueueOrigin`: `playlist(id, name)`,
   `smartPlaylist(id, name)`, `album(artist, name)`, `artist(name)`, `favorites` or `downloads`,
   one case per screen that can be pushed. A library shuffle, a search, a single track, radio,
   CarPlay and the command channel start queues no screen describes, and have none.

2. **It is set by the screen, kept through edits, and cleared by anything that replaces the
   queue.** `play` and `playShuffled` take it from the detail screen, the collection row menus,
   Favorites and Downloads. Play next, add to queue, reordering and the shuffle toggle keep it:
   adding a track to a playlist's queue is still listening to that playlist. A weighted draw,
   widening to the library, adopting another device's queue, stopping, and any `play` without an
   origin clear it. An origin that outlived its queue would send the listener somewhere unrelated to
   what they hear.

3. **It is kept in the device's queue record, never the snapshot.** `ColdRecord.origin` sits beside
   `scope` (ADR-0120) for the same reason: the snapshot is the server's contract, and this is a fact
   about the device. It is optional, so records written before it decode with no origin.

4. **The way back is in the top bar of every screen, as CarPlay's is.** A waveform button (animated
   while audio sounds) sits on the phone's Home, Search and Library roots and every pushed detail
   screen, and in the Mac's window toolbar. It opens the origin's screen, or the queue when there is
   no origin, so it never does nothing. It is absent while nothing plays, as the transport is (familiar-apple #167).
   The full player also shows "Playing from ‹name›", and the Mac bar's menu leads with
   "Go to ‹name›".

5. **Listening events say where a track was played from.** The origin is captured on the
   `PlaybackReport` when a track ends, before a new queue can replace it. It travels with the queued
   event, and maps onto `PlayContext` as follows: playlist and smart playlist → `playlist`,
   album → `album`, artist → `artist`, Favorites and Downloads → `other`. A queue with no origin,
   and any event queued by an earlier build, is still sent as `library`.

## Consequences

- **This is not ADR-0003's `queue_source`, and does not implement it.** It is never sent as queue
  state. If the server's queue gains a source, this can seed it. It should not be mistaken for one.
- **ADR-0004's follow-up test for the web client stops working.** That test reads a non-`library`
  context as evidence the web app reported. Once point 5 ships, native events carry `playlist`,
  `album`, `artist` and `other` too. Settling the web question now needs the `client` column that
  follow-up proposes, or a play in the web app matched by timestamp.
- **Favorites and Downloads are `other`.** `PlayContext` has no word for either, and `library` would
  claim a choice the listener did not make. A `favorites` context is a server change, and is
  worthwhile only if a taste signal wants to tell the two apart.
- **A renamed playlist keeps its old name in "Playing from"** until the queue is replaced. The id is
  what navigation uses, so the button still opens the right playlist.
