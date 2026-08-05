# ADR-0029: The Server Stores No Listener Preferences

Status: proposed
Date: 2026-08-05

Extends [ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md) and
[ADR-0015](ADR-0015-audio-effects-are-exposed-not-rebuilt.md)

## Context

There has never been a rule for what lives on a device and what lives on the server, so every ADR
that needed one derived it again. **Ten have**: 0003, 0012, 0015, 0018, 0021, 0022, 0025, 0026, 0027
and 0028. ADR-0021 point 5 does not even argue it: column choice is per-device because those
settings "follow ADR-0015 points 5" — one ADR about equalisers, cited as the precedent for the
layout of a table.

The eleventh case fell over. ADR-0028 point 8 gated resume-across-launches behind the queue-sync
toggle, on the reasonable-sounding grounds that a listener who turned sync off has opted out. But
that toggle's own copy says the opposite in the interface:

> At launch, Familiar restores the queue, track and position another device left on the server. It
> arms rather than plays, so opening the app never starts audio unasked, **and it never writes back**.

Someone who does not want their phone's queue landing on their Mac turns that off for exactly that
reason, and would have silently lost "resume where I left off" — which the label never mentions. The
gate was wrong because there was no rule to check it against.

**An audit of all three surfaces produced a surprising result.** The server holds **exactly one**
listener preference: `favorites_auto_download`, the only key ever written to the `Profile.settings`
JSONB bag (`backend/app/api/routes/favorites.py:152`). Everything else a listener tunes — effects,
crossfade, normalisation, columns, theme, shuffle weights, visualiser, per-playlist sort order, Home
layout — is *already* device-local on every client. The rule below is therefore mostly a description
of what the codebase already does, which is the best argument that it is the right one.

**The premise that "settings belong on the server so they follow you" does not survive contact with
what the settings are.** Of the 31 fields in `AppSettings`, seven are credentials and the rest
configure the server's own behaviour — what it scans, how it analyses, when it backs up, which model
it calls. None of them are preferences in the sense a listener would recognise.

## Decision

1. **Three categories, named, because conflating them is what caused this.**

   | category | what it is | where it lives |
   |---|---|---|
   | **Server configuration** | secrets, library paths, analysis toggles, backup schedule, LLM provider | `data/settings.json` |
   | **Listener preference** | effects, crossfade, columns, theme, shuffle weights, auto-download | the device |
   | **Shared session** | the playback queue | the device, authoritative; the server, as a handoff mirror |

2. **The test for server configuration is not "is it a preference" but "does the server act on it
   with no client present?"** `background/backup.py:27` reads app settings from a scheduled task; a
   value in a Mac's `UserDefaults` cannot drive a 3am backup. This is a structural constraint, not a
   preference about preferences, and it is why the categories cannot simply be collapsed toward the
   device.

3. **Secrets live where they are used, which is the server.** Familiar's server is what calls
   Anthropic, Last.fm and AcoustID. Moving those keys to a client would make them readable by any
   XSS in the web app *and* require transmitting them on every request — strictly worse than where
   they are. `LastfmProfile.session_key` is the same case: a credential the server scrobbles with,
   in the background, with no client attached.

4. **The server stores no listener preferences.** `favorites_auto_download` moves to the device,
   leaving the category empty. This reverses ADR-0025 point 6, which deliberately told listeners the
   toggle reached their other machines — recorded as a change of mind rather than reinterpreted.
   The merits favour the move independently: whether to keep audio offline depends on the device's
   storage, and a phone and a desktop currently cannot disagree.

5. **Device identity stays uninvented**, upholding ADR-0003 point 1. `Profile.device_id` is a legacy
   column with no readers and the client-side `deviceId` is the empty string. **A consequence, not a
   detail: anything device-scoped is local by construction**, because the server has no key to file
   it under. Point 4 is therefore not merely preferred, it is the only option that does not require
   inventing a data model first.

6. **Session state is device-authoritative with the server as a handoff mirror.** The playback queue
   is not a preference — it changes constantly, it has a conflict story, and it goes stale. Each
   device restores its own; the server session exists so another device can pick it up
   ([ADR-0028](ADR-0028-the-apple-client-writes-its-playback-session-back.md)). The web client
   already works this way and is the reference implementation: IndexedDB `playerState` is
   authoritative and always written, and `reconcileWithServer` adopts the server copy only when it
   is newer.

7. **The cost is accepted explicitly: device-local state has no backup.** Nothing in category two
   survives a reinstall, and with point 5 there is nowhere to put a copy. This is already biting —
   user-authored audio-effect presets exist only in one browser's `localStorage`, with no export,
   and `?reset=true` deletes every `familiar-*` key. If it becomes painful the answer is
   export/import, not device identity, because the latter reopens ADR-0003 point 1 for a problem
   that is not about identity.

8. **Preferences that are genuinely per-listener but shared by everyone are mis-scoped in the other
   direction, and this ADR names them without fixing them.** `playlist_discovery_mode` shapes how
   the LLM answers *for every profile on the server*; `community_cache_contribute` is a privacy
   decision made once for everyone. They violate this rule as surely as `favorites_auto_download`
   does, in the opposite direction, and they are recorded as follow-ups rather than smuggled into
   this decision.

## Alternatives Considered

**No server-side settings at all.** The instinct that prompted this ADR, and it is nearly right —
it is exactly right about category two. Rejected as stated because categories one and three cannot
follow: the server runs scheduled backups and an analysis queue with no client attached, and it
holds credentials it is the one to use. The useful half of the idea survives as point 4.

**Sync everything to the server so settings follow the listener.** The obvious opposite, and what
most music apps do. Rejected on the merits rather than cost, following ADR-0015's reasoning, which
this generalises: effects "compensate for output — headphones, car speakers, a desk monitor — so
identical settings across devices is the wrong default". The same is true of column widths on a
laptop versus a 27-inch display, and of whether a 64 GB phone keeps 1,700 favourites offline. It
also makes every preference unavailable offline, which is not hypothetical: the one server-stored
preference today fails silently when the network is down —
`startFavoritesAutoDownloadIfEnabled` wraps its read in `catch { return }`.

**Invent device identity and store per-device settings on the server.** This would deliver the
backup that point 7 gives up, and make "copy my setup to a new Mac" possible. Rejected because it
reverses ADR-0003 point 1 — whose reasoning is that one queue per profile makes handoff need no
transfer step — in exchange for a registration flow, stale-device cleanup, and a device dimension on
every settings row. That is a large data model for a problem better solved by exporting a file.

**Keep deciding case by case, as the last ten ADRs did.** It has worked, in the sense that no
individual decision looks wrong in isolation. Rejected because the eleventh was wrong, and it was
wrong in a way review nearly missed: point 8 of ADR-0028 read as a sensible respect for the
listener's opt-out, and only checking the toggle's own copy showed it was gating something the
toggle never claimed to govern.

## Consequences

- **Positive.** A new setting has an answer before the argument starts, and the ADRs that re-derived
  one can cite this instead.
- **Positive.** The rule is mostly a description of the existing codebase, so adopting it costs one
  migration rather than a rearchitecture. Every client already keeps its preferences locally.
- **Positive.** Point 2 gives a test that is decidable by looking at the code — does a background
  task read it? — rather than by arguing about whether something feels like a preference.
- **Tradeoff.** Point 7 is a real loss with no mitigation in this ADR. A listener who reinstalls
  loses their effect presets, their column layout and their crossfade settings, and will reasonably
  expect otherwise.
- **Tradeoff.** Point 4 changes behaviour for anyone using `favorites_auto_download` today: their
  other devices stop following. A one-time seed from the server keeps it from reading as data loss,
  but the divergence afterwards is the point of the change and cannot be softened.
- **Follow-up.** Delete the five `normalization_*` fields from `AppSettings`. They are duplicated in
  `localStorage`, have no server reader, and are absent from `SettingsResponse` and
  `SettingsUpdateRequest` — so the server can hold `-20` LUFS while every client plays at `-14`.
- **Follow-up.** Re-scope `playlist_discovery_mode` and `community_cache_contribute` per point 8.
- **Follow-up.** `Playlist.auto_download` and `SmartPlaylist.auto_download` carry the same
  per-device argument as favourites and are left server-side for now.
- **Follow-up.** `Profile.settings` becomes an empty JSONB bag with no schema and no readers. Decide
  whether to keep it as the established place for a future per-profile preference, or drop it.
