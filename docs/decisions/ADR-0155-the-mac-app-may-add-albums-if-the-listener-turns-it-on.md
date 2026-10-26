# ADR-0155: The Mac App May Add Albums If the Listener Turns It On

Status: accepted

Date: 2026-10-25

Implementation:
- **Accepted 2026-10-25.**
- **Point 5 built 2026-10-25** on `docs/adr-0155-opt-in-add-only-import`. `_discover_files_sync`
  skips any entry whose name begins with `.`, files as well as folders, so macOS `._` files go too.
  `folder_to_scan` ignores a change under a hidden folder *below* a library root; a root that is
  itself hidden (`~/.music`) is still watched. Pinned in `test_scanner.py::TestDiscoverySkipsHiddenEntries`
  and `test_library_watch.py`; both fail against the previous code. On the NAS no track sat under
  a hidden path (0 of 27,335), so no existing track changes state.
- **Point 2's setting is two layers** (decided 2026-10-25, built in `familiar-apple` #235). A single
  general switch ("allow limited write functionality") was considered and rejected: a listener
  cannot judge it, and every later feature that writes would inherit a yes given to something
  else. Instead Settings → Adding holds (1) the music folder, granted once and explained as
  add-only, shared by every way of adding albums because macOS grants per folder anyway, and
  (2) one switch per source under it, each off by default — "Add Bandcamp downloads" is the first.
  A later source is another switch, never a broader permission. Turning the last switch off drops
  the library bookmark, so no grant is kept as a dormant permission. Anything that would write
  other than adding albums is outside this ADR and needs its own.
- **Point 7 done 2026-10-25**, against two FLAC purchases: Bonobo, *Distance in Static* (830 MB,
  22 entries) and Max Cooper, *Feeling Is Structure* (670 MB, 11 entries). What a Bandcamp album
  download actually is:
  - **The zip is `Artist - Album.zip` and flat.** Entries sit at its root with no enclosing folder:
    tracks as `Artist - Album - NN Title.flac`, a `cover.jpg`, and sometimes more (Bonobo's has a
    booklet, oddly named `Bonobo - Distance in Static - Bonobo - Distance in Static - Booklet.pdf`).
    The importer therefore makes the album folder itself and moves the whole zip's contents into it,
    extras included.
  - **Names are UTF-8 with the zip's UTF-8 flag set** (`Youth’s Fountain (feat. Nilüfer Yanya)`).
    macOS's bundled `unzip` (Info-ZIP 6.0) *lists* them garbled; `ditto` and Python's `zipfile`
    read them correctly. Use a flag-aware extractor; never derive names from `unzip -l`.
  - **Tags are complete and consistent:** `ARTIST`, `album_artist`, `ALBUM`, `TITLE`, `track`,
    `DATE` (year only), `ISRC`, and `COMMENT=Visit https://<page>.bandcamp.com`. Both comments named
    the artist's own page (`bonobomusic`, `maxcooper`). Point 6's recognition holds. The destination
    is `<album_artist>/<ALBUM>` from the tags; the zip name agrees but is not relied on.
  - **Zip timestamps carry no time zone.** Extracted on the Mac and copied to the NAS, files landed
    four hours in the future. The importer should give added files the time of the import rather
    than the zip's.
  - **The single-track form is still unverified:** no single was bought. (Since verified; see below.)
- **Built and shipped in 1.5.1 (68)** (`familiar-apple` #235, #236) and run on the reference Mac
  against the NAS share. The first run had `~/Downloads` chosen as both folders and faithfully
  added both albums into Downloads; #236 refuses that pairing and keys the import ledger to its
  library. The second run reported both albums "already in your library" and left them.
- **Point 6 widened, with its evidence rule kept** (`familiar-apple` #237). Nathan Fake's
  *Evaporator* reads `Visit https://nathanfake.com`: an artist selling on their own domain. The
  wording alone is weak evidence for a domain anyone could own, so a custom domain counts only
  inside Bandcamp's layout (`Artist - Album.zip` holding `Artist - Album - NN …` tracks);
  `*.bandcamp.com` needs nothing more. A single track saved as itself is added as an album of one,
  on `*.bandcamp.com` evidence only. Tags are now read from MP4, Ogg, AIFF and WAV as well, **to
  their specifications only**: none of the reference library's 762 MP4, 8 WAV or 2 AIFF files carries
  Bandcamp's comment, so the first real download in each format is the check still owed.
  - **Both albums were filed by hand the importer's way** (stage in `.familiar-import-<id>` at the
    library root, `sha256sum -c` against the unpacked files, one `mv -T`), into
    `Bonobo/Distance in Static` and `Max Cooper/Feeling Is Structure` on the NAS. The first attempt
    failed at the copy (macOS `rsync` has no `--protect-args`), and the hash check then refused
    both albums with nothing reaching the library, which is the behaviour point 4 asks for.
- **The formats checked against real downloads** (2026-10-25, `familiar-apple` #238): Boards of
  Canada's *Hi Scores* in AAC, Ogg Vorbis, ALAC, WAV and AIFF, each passed to
  `testARealDownloadIsRecognised`. Every zip has the same flat layout and `cover.jpg`, all entries
  stored. AAC, Ogg Vorbis, ALAC and AIFF are recognised and added. **Bandcamp's WAV files carry no
  tags at all**, only `fmt ` and `data` chunks, with no `LIST`/`INFO` and no `id3 `. So a WAV
  download is never recognised, and Settings → Adding says so. Recognising a WAV by its zip's
  layout alone was rejected, because nothing in the files would say who sold them. Chrome saved
  the second to fifth downloads as `Boards of Canada - Hi Scores (N).zip`. That broke the layout
  check a custom domain depends on, so #238 drops a browser's trailing `(N)` before comparing.
- **The add itself had never run against the NAS, and failed every time** (found 2026-10-26, fixed
  in #238). The earlier real runs only reached "already in your library", which is checked before
  anything is written. In 1.5.1 (69) every *Hi Scores* zip and the single failed with
  `NSPOSIXErrorDomain 45 "Operation not supported"`. On the SMB share, `renamex_np(RENAME_EXCL)`
  is `ENOTSUP`. A plain `rename` works there, refuses a non-empty destination with `ENOTEMPTY`,
  and replaces only an empty folder. So point 4's no-replace rule holds with a plain-rename
  fallback. The staging folder was removed after each failure, as point 4 asks. Failures had been
  kept in the ledger forever, with nothing in Settings to ask again, so they are now retried at the
  next launch.
- **The single-track form is verified** (Max Cooper, *Waves*, FLAC, 2026-10-26). Bandcamp saves it
  as `Artist - Title.flac`, not with the album's prefix. It carries `TITLE`, `ARTIST`,
  `ALBUMARTIST`, `ALBUM`, `TRACKNUMBER`, `DATE`, `ISRC` and `COMMENT=Visit
  https://maxcooper.bandcamp.com`, and it is added as `Max Cooper/Emergence`.

Extends [ADR-0140](ADR-0140-familiar-server-enforces-zero-touch-with-a-seatbelt-profile.md) and
[ADR-0154](ADR-0154-familiar-does-not-acquire-music.md).

## Context

Familiar's library is read-only by promise and by enforcement. `docs/ZERO-TOUCH.md` states the
principle ("Familiar never creates, modifies, moves, re-encodes, or deletes files in the user's
music library"). The server refuses to start on a writable library (`validate_library_path`,
`backend/app/main.py:228`, unless `allow_writable_library` is set), Docker mounts the library `:ro`,
and on a Mac the Python server runs under a Seatbelt profile that denies writes to the folder
(ADR-0140).

The intent is to send listeners to Bandcamp, and Bandcamp's customers are almost the only people
who still buy files. The step where a purchase is lost is the one after buying: Bandcamp delivers an
album as a zip in `~/Downloads`, and the listener has to unpack it into the right folder by hand.
Nothing in Familiar helps with that, and under the promise above nothing can.

Two things were settled before this ADR was drafted:

- **Nothing here talks to Bandcamp.** There is no public API for a fan's purchases. The tools that
  sync a collection automatically drive the website with the fan's session cookie, which is not
  above board, and they are rejected below. The importer only handles files the listener has
  already downloaded.
- **A Bandcamp file identifies itself.** Bandcamp writes a comment tag into every file it sells.
  Sampled from the NAS library on 2026-10-25, for example `Visit https://warprecords.bandcamp.com` on
  `/music/Two Lone Swordsmen/Tiny Reminders/17 - Foreververb.flac`, and `Visit
  http://abelard.bandcamp.com` on an MP3. **It names the artist's or label's page, not the
  album's.** The zip's own naming (`Artist - Album.zip`, tracks as `Artist - Album - NN Title.ext`)
  is from memory and **has not been checked against a real download.** Point 7 makes checking it the
  first step of the build.

**`docs/ZERO-TOUCH.md` contradicts this on purpose, and that is recorded here rather than worked
around.** Its section 3 removed zip import ("Direct zip upload import should be removed for
zero-touch mode; the product promise stays cleaner if all adopted music already lives in a
user-managed folder outside Familiar"). That reasoning holds for the default and is kept. This ADR
adds one exception, which the listener must turn on themselves.

**A design built around one installation was considered first and dropped.** It had a tool on the
Mac reach the NAS over `ssh` and stage files beside the library on the same disk. That is how
`soulseek-mcp`'s move works, and it is right for a personal tool. A newcomer has a Mac and a
Downloads folder, not an ssh host, so it was the wrong shape for a feature meant to win users.

**Hidden folders are not skipped today.** `_discover_files_sync` (`scanner.py:174`) descends into
every directory, dot-folders included, and `folder_to_scan` (`library_watch.py:63`) does the same
for the watcher. A partially copied album in a hidden staging folder would therefore be found by
the two-hourly sync.

## Decision

1. **The default stays read-only, everywhere.** A new install, and any install where the listener
   has not turned this on, behaves exactly as today. Nothing in this ADR changes the server.
   `validate_library_path`, the `:ro` Docker mount and ADR-0140's Seatbelt profile all stay. The
   server never writes the library under any setting.

2. **The importer lives in the Mac player app, off until the listener turns it on.** The setting is
   "Add Bandcamp downloads to my library", off by default and stored on that Mac. Turning it on asks
   for two folders through the system's open panel. One is where downloads arrive (`~/Downloads` by
   default), which the app only reads. The other is the library folder to add to, which may be on
   this Mac or a mounted network share. The app keeps both as security-scoped bookmarks and adds the
   matching sandbox entitlements (user-selected read-write and app-scope bookmarks). Today it has
   only `app-sandbox` and `network.client`. Turning the setting off removes the write access.

3. **The importer only adds.** It never modifies, renames, retags, re-encodes or deletes anything,
   in the library or in Downloads.
   - It refuses a destination `<Artist>/<Album>` that already exists, and says so.
   - It leaves the downloaded zip where it is, and records it as done in its own list so it is not
     imported twice. Clearing Downloads stays the listener's job.
   - The files it adds are byte-for-byte the files in the zip, checked by hash after copying.

4. **An album appears whole or not at all.** The app unpacks into a hidden folder
   (`.familiar-import-<id>`) at the library root and checks it. Only then does it rename that
   folder to `<Artist>/<Album>`: one rename on one filesystem, which is atomic locally and on an SMB
   share. A failed import leaves only the hidden folder, which the app removes, since it is the
   app's own.

5. **The scanner and the watcher skip hidden folders.** Any path component beginning with `.` is
   not descended into or scanned. Point 4 depends on this. It is right on its own too, since it stops
   Familiar walking `.Trashes`, `.Spotlight-V100` and similar folders. It is the first slice and
   ships independently.

6. **Only Bandcamp downloads are recognised.** A file counts as Bandcamp's when its comment tag
   reads `Visit http(s)://<name>.bandcamp.com`. Anything else in Downloads is ignored, not guessed
   at. A new album reaches Pending Review by the ordinary rule (`docs/ZERO-TOUCH.md` section 3), as
   anything new in the library does.

7. **The build starts by checking a real download.** Before any code, a purchased (or free)
   Bandcamp album is downloaded in FLAC and MP3, and its zip layout, file names, tags and
   single-track form are recorded in this ADR's Implementation block and kept as test fixtures.
   Points 3–6 are revised to match if the real layout differs.

## Alternatives Considered

- **Stay strictly read-only and never add files.** It is the cleanest promise, and it is still the
  default. Rejected as the only option, because it leaves the step that loses a Bandcamp buyer
  (the zip in Downloads) with no help at all, for a product whose stated audience is people who buy
  files.
- **A separate tool, like `soulseek-mcp`.** It keeps "Familiar never writes" literally true.
  Rejected for this purpose, because every newcomer would have to find and install a second program
  before the feature exists for them. It works against the goal of gaining users. A personal tool
  is still fine for Jeff, and `soulseek-mcp` is one.
- **Sync the fan's Bandcamp collection automatically** (as `bandcampsync` and
  `bandcamp-collection-downloader` do). Rejected: it drives undocumented site endpoints with the
  fan's session cookie, which is not above board, can break at any time, and is a poor thing to show
  Bandcamp. A supported way to sync purchases is something to ask Bandcamp for, not build around it.
- **Have the server import.** Rejected: the server may be a NAS that cannot see the listener's
  Downloads folder, and giving it write access would undo ADR-0140 and `validate_library_path` for
  everyone, not only for those who opted in.
- **Put it in Familiar Server (the Mac menu-bar app).** Rejected as the home: it exists only where
  the server runs on a Mac, so NAS listeners would not get it. The player is on the machine where
  the listener downloads, whatever runs the server.
- **Stage outside the library instead of in a hidden folder.** That needs a writable sibling folder
  on the same filesystem, which a listener with only a mounted library share does not have. It was
  the ssh design's assumption.

## Consequences

- **Positive:** a Bandcamp purchase can go from Downloads to Pending Review with no manual steps,
  for anyone who turns it on, on a local library or a NAS share.
- **Positive:** the server's guarantees are unchanged and still enforced in three places. A
  listener who never opens the setting sees no difference.
- **Tradeoff:** "Familiar never writes your music folder" becomes "Familiar never changes what is in
  your music folder. With your permission, the Mac app adds new albums." `docs/ZERO-TOUCH.md`, the
  README and the website must say that, and must say it is off by default.
- **Tradeoff:** the Mac app gains file entitlements it does not have today, which App Review will
  see and the privacy description must explain.
- **Tradeoff:** the importer is Mac-only. The phone never touches files (ADR-0013 point 2 keeps
  management off it), and the web app has no access to Downloads.
- **Follow-up:** remembering each album's Bandcamp page, for a link back from Familiar, reads the
  same tag but is a separate server change with its own ADR. It is not decided here.
- **Follow-up:** asking Bandcamp for a supported way to sync purchases, once there are users to
  show them.

**Execution order:** point 5 (`familiar`, ordinary fix) → point 7 (check a real download) →
points 2–4 and 6 (`familiar-apple`) → the documentation in the Tradeoff above.
