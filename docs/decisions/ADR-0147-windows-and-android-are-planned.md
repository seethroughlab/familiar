# ADR-0147: Windows and Android Are Planned

Status: accepted

Date: 2026-10-03

Implementation:
- **Accepted 2026-10-03**, as written. Not yet built.

Extends [ADR-0131](ADR-0131-the-server-is-its-own-app.md) point 4 and
[ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md) point 7

## Context

The site is about to say that Windows and Android are coming (ADR-0146). The claims ledger
(`docs/SITE-CLAIMS.md`, ADR-0055 point 2) needs every claim to trace to something true, and a
promise about the future is true only if it has been decided. Read on 2026-10-03, what the
repository has decided:

- **Windows server: shelved, with a condition.** ADR-0131 point 4: "Windows is shelved until the Mac
  ecosystem is done", where done is checkable — ADRs 0132–0138 shipped, and "a coworker on a clean
  Mac has gone from download to listening on their phone without help". It names the option this
  ADR takes up: a Windows **server** app could serve the Apple clients with no Windows player at all.
- **Windows player: never decided.** ADR-0001 point 7 says Windows "is deliberately not built now"
  and is prepared for by keeping logic on the server; ADR-0006 and ADR-0007 assume a Windows client
  could follow from the same schema.
- **Android: nothing.** No ADR, document or plan mentions an Android client. The only hits are a
  mobile user-agent regex and screenshot viewports named after Android phones.
- **Docker on Windows is supported today**, run end to end on Windows 11 Pro on 2026-08-30
  (`docs/SITE-CLAIMS.md`).

So "coming" would be a claim the repository does not support, unless it is decided here.

## Decision

1. **Three are planned:** Familiar Server for Windows, a Familiar player for Windows, and a Familiar
   player for Android. No dates are given, here or on the site.

2. **The order ADR-0131 point 4 set is kept.** None of the three begins before its condition is met:
   the Mac ecosystem done, as that point defines it. Between them the order is open, and is decided
   when the work starts, by the ADR that starts it.

3. **Docker on Windows stays supported in the meantime**, labelled as Docker wherever it appears, so
   that "Familiar Server for Windows is coming" and "run it on Windows with Docker" can sit side by
   side without contradicting each other.

4. **"Coming" on the site, the README and the FAQ cites this ADR**, and the claims ledger records it
   as an intent with this ADR as its evidence. If a platform is dropped, this ADR is superseded and
   every "coming" line goes with it.

## Alternatives Considered

- **Say nothing until there is something to ship.** The safest for the ledger. Rejected: Windows and
  Android are the first two questions a Mac-first page provokes ("what about my PC?", "my partner
  has an Android phone"), and silence reads as "never".
- **Name dates.** More useful to a reader. Rejected: nothing in the repository supports a date, and a
  date on a public page is the kind of claim ADR-0055 point 2 exists to stop.
- **Android before Windows.** A phone is how most people listen, and an Android player serves anyone
  with a Mac or a NAS. Not rejected so much as left open: point 2 leaves the order to the ADR that
  starts the work, once the Mac condition is met.
- **Windows server only, as ADR-0131 point 4 suggested.** It covers a Windows user with an iPhone.
  Rejected as the whole plan: it leaves Windows-only and Android households with nothing to listen
  on, and the site would have to explain why.

## Consequences

- **Positive:** the page can answer the two obvious questions honestly.
- **Tradeoff:** a public promise with no date. Point 4 makes withdrawing it a recorded decision, not a
  quiet edit.
- **Follow-up:** `docs/WINDOWS.md`, an outdated audit "documented for future implementation"
  (ADR-0095 said to retire it), is retired or rewritten when the Windows work starts.
- **Follow-up:** each platform gets its own ADR when it starts, deciding packaging, signing and
  distribution, as ADR-0135 did for the Mac.
