# ADR-0151: The Phone Makes and Edits Smart Playlists

Status: proposed

Date: 2026-10-07

Supersedes point 2 of [ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md), for playlists
only.

## Context

ADR-0013 point 2 says **"iOS stays the listening path. The phone is not a management client"**, and
point 3 puts smart playlist CRUD on the Mac. `familiar-apple` still cites both:
`SmartPlaylistsListView.swift` keeps creating, refreshing and deleting `#if os(macOS)`, and its
empty state on the phone reads "They're made on the Mac or in the web app, and fill themselves."

**The phone stopped being only a listening path on 2026-08-15, and nothing recorded it.**
`familiar-apple` #119 ("Add visible iOS playlist editing", `2bb5b2d`) gave the phone, in the iOS
branch of `BrowseViews.swift` (lines 722–797 at the time of writing):

- **Edit Rules** on a smart playlist's screen, opening the same `SmartPlaylistEditor` the Mac uses;
- **Edit Contents**, **Rename** and **Delete** on an ordinary playlist.

No ADR was written, so the record and the app have disagreed for seven weeks. That is the defect
ADR-0061 point 5 names: "the record and the app disagreed for weeks and neither one knew."

The prompt for this ADR is the owner, travelling with only the phone, wanting to **make** a smart
playlist and finding no way to. The phone can now change any rule of a smart playlist that exists,
and cannot write the first one. That line follows from no principle: it is where #119 stopped.

ADR-0013 point 2 says managing the library from a phone "is still a second-class experience by
design", and gives no reason specific to playlists. Point 3 lists smart playlist CRUD beside pending
review, proposed changes and mixtapes, and point 4 keeps settings, imports and backup on the web.
Pending review, proposed changes, settings, imports and backup all change what the server holds or
how it runs. A smart playlist changes neither: it is a saved question about the library. It is a description
of **what to listen to**, and the test ADR-0018 and ADR-0019 used to bring Discover to the phone,
whether it is a way of finding something to play, is one it passes. The editor is already built
from the server's own field list, so writing a rule on the phone needs no new screen, only a way in.

## Decision

1. **Playlists are not management.** On the phone, as on the Mac, a listener can create, edit,
   rename and delete ordinary playlists and smart playlists. This supersedes ADR-0013 point 2 for
   playlists and for nothing else.

2. **The phone gets "New Smart Playlist"**, opening the existing `SmartPlaylistEditor` with no
   playlist, the way the Mac's `+` does. It sits in the toolbar of the smart playlists list, and the
   empty state names it rather than sending the listener to another device.

3. **Refresh and Delete join Edit Rules** on a smart playlist's screen on the phone, under the same
   actions menu, so a smart playlist has the same three operations an ordinary one already has
   there.

4. **#119's editing is recorded as decided here, not as an exception.** Nothing it added is removed.

5. **Everything else ADR-0013 point 2 kept off the phone stays off it**: settings, pending review,
   proposed changes, mixtapes, imports, backup, and every other surface whose subject is the server
   rather than what to play next.

## Alternatives Considered

- **Leave ADR-0013 point 2 as it is and remove #119's editing from the phone.** Restores agreement
  between the record and the app at the cost of the feature. Rejected: the owner uses it, and the
  reason given for the original line, that a phone is a poor place to manage a server, does not
  describe a playlist.
- **Record #119 and still keep creation on the Mac.** Smallest change, and creating is where a new
  rule is most likely to be written badly on a small keyboard. Rejected: the editor that edits a rule
  is the one that would create it, the phone already writes every field of one, and "you can change
  any rule but not write the first" is the gap that prompted this ADR.
- **Create on the phone through a simpler, phone-only editor**, such as a handful of preset rules.
  Easier to use with a thumb. Rejected for now: a second editor is a second thing to keep in step
  with the server's field list, which `SmartPlaylistEditor` already reads, and the full editor
  already works on the phone through Edit Rules.

## Consequences

- **Positive:** the record matches the app again, and a smart playlist can be made where the idea
  for it happens.
- **Positive:** the phone and the Mac offer the same playlist operations, so nothing about a
  playlist has to be explained per device.
- **Tradeoff:** ADR-0013's simple rule, "the phone is not a management client", becomes a rule with
  an exception. Point 5 states the boundary so it does not drift further one feature at a time.
- **Follow-up:** `SmartPlaylistsListView`'s header comment and empty state, and the `LibraryView`
  comment on `smartPlaylistsStore`, describe the old split and change with the code.
