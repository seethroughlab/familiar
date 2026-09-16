# ADR-0120: A Weighted Shuffle Applies to the Queue That Is Playing

Status: accepted

Date: 2026-09-16

Implementation:
- **Accepted 2026-09-16**, the day it was proposed, as written; both halves built the same day.
- **Built 2026-09-16.** Server: `favorites=true` on `/tracks/ids` (`routes/tracks/listing.py`),
  joined on the base query, the weighted path reading its boost column off that join rather than
  joining twice; four tests; contract re-locked at v1 (familiar#322). Client: `FamiliarPlayer.
  queueScope` with `.library`/`.favorites` in place of the boolean, set by the Favorites screen for
  its whole collection and by the library draws; `LibraryView.redrawScopedQueue` with the scope on
  the request; `ShuffleControl.toggle` asking for the weighted order after turning shuffle on;
  the device queue record carrying `scope` beside the boolean it supersedes; seven tests
  (familiar-apple, ADR-0120 branch). Not yet deployed or on TestFlight as this is written.

## Context

ADR-0035 made a weighted shuffle a *preset the server applies*: the listener chooses Rediscover,
Fresh Finds, Comfort Zone or Deep Dive on the transport's shuffle control, and the choice reaches
the server as `shuffle_preset=` on `GET /api/v1/tracks/ids`, which draws the whole library in a
weighted order the client cannot compute (the weights normalise against a library-wide maximum
play count; the client holds fifty tracks at a time). Its point 4 said where that applies: *where a
queue is drawn from the library, and nowhere else* — "Shuffle everything", Home's Start Shuffle,
and the widening of a short queue to the library. Its point 2 gave the reason the control has to
be honest: a shuffle that permutes a weighted order "leaves a control that appears to work and
does nothing — the exact shape of the defect ADR-0027 exists to fix."

That sentence now describes the control itself, measured on 2026-09-16 on the Mac:

- **Choosing a preset stored the choice and showed nothing.** `familiar-apple#189` found and fixed
  the surface: the `Menu` with a `primaryAction` that shape makes on the Mac paints its own label
  (the glyph never lit, shuffled or not) and does not rebuild its rows once built. The stored
  value moved on every choice — `rediscover` → `comfort_zone` → `deep_dive` in the defaults — and
  nothing on screen followed. That is fixed on the Apple side and is not this record's subject,
  except that it hid the second defect for a month.

- **Choosing a preset while something is playing changed nothing you could hear**, because of
  point 4. `#189` amended that for a library draw: `FamiliarPlayer.isLibraryDraw` says the queue
  came from the whole library, and a preset chosen over such a queue re-draws what is left through
  the widening path — `start_with` pins the current track, the rest is replaced, the audio is not
  touched.

- **And then it still did nothing, because the queue was not the library.** The device's queue
  record read: 1,747 tracks, shuffled, not a library draw. That is the Favorites collection —
  played from a row, then shuffled with the transport's toggle. A whole-library draw is 26,794
  ids. The listener's everyday queue is Favorites, and for that queue there is no server order to
  ask for: `/tracks/ids` filters by artist, album, genre, year and four analysis axes, and not by
  favourite. So on the queue that is actually played, the preset is a preference that acts on a
  button the listener does not press.

### What the server already has

The weighted path in `routes/tracks/listing.py` joins `ProfileFavorite` for every track it
scores — `favorites_boost` is one of the four axes. Scoping the *draw* to favourites is the same
join used as a filter rather than as a column, on the same `query` the other filters compose on,
and the weighted, random and sorted paths all read from it. Nothing about the scorer changes: it
runs over whatever rows the query returns, and normalises against the maximum play count *within
those rows*, which is what a weighting over a subset should do.

### What the client already has

`#189`'s re-draw is a scope away from general. `isLibraryDraw` is a boolean because there was one
scope; `redrawLibraryQueue` fetches with no scope because there was one. The toggle on the
transport still permutes locally with a preset set and lit beside it — point 2's defect from the
other direction: shuffle *on* looks weighted and is not.

## Decision

1. **`GET /api/v1/tracks/ids` takes `favorites=true`.** With a profile, the query is restricted to
   the profile's favourites by joining `ProfileFavorite`; every path — weighted, `shuffle=true`,
   sorted, `start_with` — sees the restriction, because it is applied to the base query before any
   of them. Without a profile it is a 400 — the API's own validation error — rather than a silent whole-library answer,
   for ADR-0032 point 5's reason: a plain shuffle looks exactly like the feature working. `total`
   counts the scoped set. Additive to the contract; re-locked at v1.

2. **A queue has a draw scope, not a library flag.** `FamiliarPlayer.isLibraryDraw` becomes
   `queueScope: QueueScope?` with cases `.library` and `.favorites`. `.library` is set where the
   flag was; `.favorites` is set when the Favorites screen builds its queue from the **whole,
   unfiltered** collection — a filtered collection is a subset the server cannot name, and gets
   no scope. An album, playlist or hand-built queue has none. Persisted in the device's queue
   record beside the field `#189` added, which keeps its name and meaning for records already
   written.

3. **A preset chosen over a scoped queue re-draws it, while shuffle is on.** `redrawLibraryQueue`
   becomes `redrawScopedQueue`, and asks `/tracks/ids` with `favorites=true` for a `.favorites`
   scope and without it for `.library`; the rest is unchanged — `start_with` pins the current
   track, `widenQueue` swaps what is left, "Off" is a re-draw in the scope's own order shuffled
   here from the cursor. With shuffle off the preset is stored and waits for the toggle (point 4):
   a weighted order playing under an "in order" toggle would be the lie point 2 forbids, from the
   other side. A queue with no scope is left alone and the preset waits, as ADR-0035 point 4
   always said.

4. **Turning shuffle on over a scoped queue with a preset set draws weighted, rather than
   permuting.** The toggle turns on immediately and locally, as it always has — the queue is
   permuted and plays on — and the same re-draw then replaces the permutation with the server's
   weighted order when it arrives, a second later. Turning shuffle *off* is unchanged: point 3 of
   ADR-0035 holds the weighted order in `logicalQueue`, so "in order" straightens out to the order
   the server gave, which is an order that really existed. The glyph lights for either kind of
   shuffle (`#189`), so the state it shows is the state that plays.

5. **The preset is still a listener preference, held on the device** (ADR-0035 point 1), and it
   still applies to nothing the server cannot weight — an album, a playlist, a filtered view. What
   changes is that the two queues a listener actually keeps, the library and their favourites, are
   both weightable, and both follow the control.

6. **Not decided here:** weighting any other collection (a playlist of 300 could be; a scope per
   playlist is a different parameter and a different question), and the phone's long-press menu,
   which has not been reported broken.

7. **Execution order:** point 1 with its test → schema dumped, contract re-locked, deployed to the
   NAS → the schema vendored into `familiar-apple` → points 2–4 with their tests → a TestFlight
   build. The server must be up before the client asks, or the client's Favorites re-draw is a
   refusal it treats as "no answer" and does nothing, which is correct and invisible.

## Alternatives Considered

- **Compute a favourites-scoped weighting on the client.** The client holds the whole Favorites
  collection (ADR-0012 point 3) but not the play history it would weight by, and it would be a
  second copy of the scorer in a second language — ADR-0035's Alternatives already rejected this
  for the library and the reason does not weaken for a subset.

- **Send the favourite ids to the server and weight those.** 1,747 ids in a query string, on
  every re-draw, to tell the server something it already knows about the profile. The join is
  cheaper, and it is the same join the scorer already makes.

- **Make the Favorites screen's row tap draw weighted at once when a preset is set.** Rejected:
  tapping a row means "play these, from here", and the listener chose the order by not pressing
  shuffle. Point 4 acts when shuffle is turned on, which is the moment the listener asks for an
  order they did not choose.

## Consequences

- A preset does what it says on the two queues that matter; the transport's state and the
  playing order agree.
- One more server request when shuffle is turned on over a scoped queue with a preset set, and
  a second's delay before the weighted order lands under a permutation that is already playing.
- `/tracks/ids?favorites=true` without a profile is a 400, and a client behind this build never
  sends it.
- The device's queue record grows a field; the server's session snapshot does not.
