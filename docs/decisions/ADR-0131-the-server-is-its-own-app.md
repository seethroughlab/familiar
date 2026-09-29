# ADR-0131: The Server Is Its Own App

Status: accepted

Date: 2026-09-29

Extends [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md),
[ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md),
[ADR-0095](ADR-0095-the-install-section-is-platform-first.md)

## Context

Familiar is about to be offered to coworkers, each of whom would run it over their own music. Every
route to a server today is Docker. ADR-0095's macOS panel asks for four things: Docker Desktop, an
unzipped repository, a `.env` edited in Terminal, and a ~7 GB pull. It named a one-click installer
as "eventually right" and declined it because "the Apple app is a *client* — there is no packaged
server today".

**Two earlier drafts of this set were written and reversed before any was accepted.** Both are
recorded so neither is rebuilt from its parts:

1. **A server inside the App Store build of the Mac app, running only while the app was open and
   listening only on loopback.** Each choice was defensible alone. Together they describe a server
   that stops when its owner closes a window, that the owner's phone cannot reach, and whose every
   release waits on App Review.
2. **A background helper inside the Mac player, with the player leaving the Mac App Store to carry
   it.** This fixed the first draft's lifecycle, but it welded the server to the machine you listen
   from. The author's own arrangement is the counter-example: a server on a NAS with a 26k-track
   library, played from a Mac and an iPhone. Under that draft the Mac player would have carried a
   Python runtime, a database and `ffmpeg` it would never start. It would also have left the App
   Store to do so, and a coworker who later moved their library to a NAS would have had to migrate
   out of it.

What survives both reversals is that **where the server runs and where you listen are
independent**. That is already true of the clients. `familiar-apple`'s setup takes an address
(`App/Shared/SetupView.swift`), and nothing in FamiliarKit assumes the server is local or remote.
This ADR makes the same true of how the server is packaged.

What it inherits:

- **ADR-0001 point 7:** there is no Windows player.
- **ADR-0013 point 2:** iOS is the listening path.
- **ADR-0096:** remote access is Tailscale-first because "Familiar has no login".

## Decision

1. **Familiar is two products: a server, and the clients that play from it.** They are installed
   separately, released separately, and paired (ADR-0134). No client bundles a server, and the
   server bundles no player.

2. **The server comes in two forms, and both are supported:**
   - **Familiar Server**, a menu-bar app for macOS that runs in the background (ADR-0135,
     ADR-0136)
   - **Docker on Linux and NAS**, as today

   They are the same backend from the same release tag. A new user with only a Mac is pointed at
   Familiar Server. Anyone with a NAS or a home server keeps using, or is pointed at, Docker.
   Neither is the secondary route.

3. **Clients never assume where their server is.** A server on the same Mac, a NAS and the demo are
   all reached the same way: by pairing, through a stable `server_id` (ADR-0134). A feature that
   only works when client and server share a machine must say so in its ADR, and must degrade
   rather than fail when they do not.

4. **Windows is shelved until the Mac ecosystem is done.**
   - "Done" is checkable: ADRs 0132–0138 are shipped, and a coworker on a clean Mac has gone from
     download to listening on their phone without help.
   - The split creates a new option for later: a Windows **server** app could serve the Apple
     clients with no Windows player at all, so a Windows user with an iPhone would be covered. That
     is for the Windows set to weigh.
   - Until then, server work stays platform-neutral. The server may adapt to the platform it runs
     on (ADR-0138 point 3 is an example), but no server feature may depend on macOS.

5. **Server work every client inherits still goes first.** This is the ordering principle of the
   first ADR set.

6. **Server settings stay in the web admin.** ADR-0013 point 4's reasoning ("a server has one
   configuration whichever client edits it") holds for both forms. Familiar Server's menu opens the
   admin in the browser (ADR-0136).

This set, and its execution order, which differs from the numbering:

| # | ADR | Why here |
|---|---|---|
| 1 | `0131` | Framing only. |
| 2 | `0132` → `0133` | The server runs as one ordinary process against one database. Every later ADR assumes it. |
| 3 | `0134` | Pairing and the token, server and Apple client together. It also clears ADR-0045 point 5's larger blocker for the NAS. |
| 4 | `0136` spike | Its point 8: does Postgres run under Familiar Server's sandbox? The answer shapes that ADR before anything is built on it. |
| 5 | `0135` | Familiar Server's build, signing and update pipeline in `familiar`'s release workflow. It depends on nothing else and must exist before 0136 ships. |
| 6 | `0136` with `0138` | The background server and the rules it keeps on its owner's machine. They ship together, because a background app without etiquette is the one people uninstall. |
| 7 | `0137` | The phone keeps a copy. It needs 0134's pairing and is worth most against a server that sleeps. |

## Alternatives Considered

- **The server inside the player: as a child of the App Store app (draft 1), or as a background
  helper with the player leaving the store (draft 2).** One download, with no pairing step on the
  same Mac. Rejected for the reasons in Context. The deciding one is that it fixes the listening
  machine and the server machine as the same, which the author's own setup already contradicts.
- **Docker only, with a friendlier install panel.** No new packaging at all. Rejected because
  ADR-0095 already made the panel as short as Docker allows. What remains (Docker Desktop, a
  terminal, ~7 GB) is the hurdle itself.
- **A shared server at work that coworkers connect to.** No install at all for everyone but one
  person. Rejected because each coworker's music is their own and on their own machine, and
  because it would need ADR-0045's full profile allowlist to keep people out of each other's
  playlists.
- **A hosted server.** Rejected: it contradicts a local, analysed library and the zero-touch
  guarantee (`docs/ZERO-TOUCH.md`), and it is the step from music player to hosting business that
  ADR-0045 records ADR-0038 point 7 as declining.
- **Mac and Windows server apps at once.** It reaches more coworkers sooner. Rejected: two
  packaging, signing and background-service problems before the first is proven.

## Consequences

- **Positive:** Familiar can be recommended to someone who has never opened a terminal, and the
  author's NAS arrangement is a first-class case rather than an exception.
- **Positive:** the Mac player stays in the Mac App Store, and NAS users' players carry no server.
- **Positive:** the server work (0132, 0133) and the token (0134) improve the NAS route as much as
  the desktop one.
- **Tradeoff:** a coworker installs two things, the player and Familiar Server. ADR-0135 and
  ADR-0134 point 5 make the second one hand off to the first.
- **Tradeoff:** there are two server packagings to keep working from one backend. CI has to prove
  both.
- **Tradeoff:** a desktop server sleeps. ADR-0137 is why that is survivable.
- **Follow-up:** once a notarized Familiar Server exists, ADR-0095's macOS panel is superseded by
  one that leads with it, with Docker kept for the NAS panels. ADR-0096's claim about "no login"
  expires when 0134 ships, as its point 6 anticipated.
- **Follow-up:** the Windows set, when point 4's condition is met.
