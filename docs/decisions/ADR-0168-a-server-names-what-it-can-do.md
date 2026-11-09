# ADR-0168: A Server Names What It Can Do

Status: accepted

Date: 2026-11-08

Extends [ADR-0113](ADR-0113-the-api-declares-a-contract-version.md), whose contract number says
whether a client and a server can talk, but not whether the server has a feature the client offers.

## Context

ADR-0113 gave the app one comparison: the server's `contract_version` against the contract the app
was generated from. A server behind the app shows `ServerBehindBanner` above the track list
(`familiar-apple` `App/Shared/LibraryView.swift:515`). That banner exists for exactly the case of a
new app against an older server, and **it can never fire for an added feature.** `app/config.py`
says why, correctly for what the number is for: "Purely additive changes do not bump it — they
re-lock `contract.lock.json` and nothing else." An old client is unaffected by an addition, so
nothing moves.

Server 0.2.0-beta23 (2026-11-08) is the server half of app 1.7, and every change in it was additive.
The contract is still v1. So 1.7 against beta22 is "compatible", silently, and what the listener
actually gets is:

- **Lyrics read "no lyrics" for every track.** A pre-ADR-0163 server sends no `status`, and the app
  infers `notFound` from the empty answer (`LyricsDocument.init(wireStatus:…)`,
  `Sources/FamiliarKit/Lyrics.swift`). It does not cache that answer, so the view corrects itself
  once the server is updated, but until then it says the wrong thing about every track.
- **Match to the Music and the visualizer's view of the track do nothing.** The older server refuses
  the page's origin (ADR-0164), which is what they did before 1.7.

Nothing tells the listener that updating the server fixes this. Most listeners will never meet it,
because the server runs on the same NAS as the developer's, or is Familiar Server, which updates
itself through Sparkle. A Docker install updates only when its owner pulls a new image.

The premise that would make this easy is still false: **the server's version string cannot be
compared.** ADR-0113's Context found `get_app_version()` reporting `"demo"` on every fly deploy and
nothing on the NAS. The NAS now runs released images, but `fly-deploy-demo.yml` still writes no
`VERSION`, and a development server reports `"dev"`. App Review connects to the demo, so a check
built on the version string would misjudge the one server that matters most at submission.

## Decision

1. **`GET /api/v1/contract` gains `capabilities`, a list of names**, from a source-level constant
   `SERVER_CAPABILITIES` in `app/config.py`, beside `API_CONTRACT_VERSION` and with its own history
   comment. A constant, for ADR-0113 point 1's reason: it is correct on every deploy channel, where
   the version string is correct on one. The endpoint stays outside the token gate, so a client knows
   what a server can do before pairing.

2. **A name is a feature a client can offer, not an endpoint.** Dotted and lower-case:
   `lyrics.status` (ADR-0163), `visualizer.paired_page` (ADR-0164), `albums.move_to_album`
   (ADR-0166). The first list names everything app 1.7 relies on. A name is added in the same pull
   request as the feature. **A name is never removed while a shipped client may ask for it**;
   removing one is a breaking change and bumps `API_CONTRACT_VERSION` under ADR-0113.

3. **Adding a capability is additive.** It re-locks `contract.lock.json` and does not bump the
   contract number. The number keeps its meaning: can these two talk at all.

4. **The client owns the mapping, as a pure function in `FamiliarKit`**, in the shape of
   `ContractCompatibility`: its table says which of its features needs which capability, and the
   first server release that has it. The release is written into the client's table when the
   release is cut, never read from the server, because the server cannot report its own version
   reliably (Context).

5. **A missing feature says so where the listener meets it.** The lyrics view shows "Lyrics need a
   newer version of your Familiar server (0.2.0-beta23 or later)", not "no lyrics". Match to the
   Music shows the same sentence instead of doing nothing. `ServerBehindBanner` gains a second case
   that lists the missing features once. No feature is hidden: unlike ADR-0022 point 3, where the
   provider was the listener's choice, here an update fixes it, and saying so is the fix.

6. **A server without the field is judged only by what it shows.** Servers up to and including
   0.2.0-beta23 send no `capabilities`. The client must not read that as "has nothing", because
   beta23 has everything 1.7 needs. Where a response proves a server is older, the client says so:
   a lyrics answer without `status` comes from a server before beta23, and it is the only such
   signal 1.7 needs. Otherwise the client says nothing, as ADR-0113 point 8 does for a server that
   predates the handshake.

## Alternatives Considered

- **Bump `API_CONTRACT_VERSION` for additions a new client relies on.** The banner already exists,
  so this costs one number. But the number would then mean two things, and ADR-0113's bump rule
  ("alters what an already-shipped client can assume") would need an exception that every future
  change has to argue about. It can also only say "your server is behind", never which feature is
  missing, and lyrics showing "no lyrics" would still be wrong. Rejected.
- **Compare `server_version` against a minimum.** It needs no new field. Rejected for the reason in
  Context, unchanged since ADR-0113: the demo reports `"demo"` and a development server `"dev"`.
  App Review would see a false warning, or none.
- **Probe each feature's endpoint and treat a 404 as missing.** It works for a new endpoint, and for
  nothing else. Of 1.7's three dependencies, lyrics is a new field on an existing endpoint and the
  visualizer page is a CORS rule, so neither has a 404 to see.
- **Do nothing and rely on release notes.** That is the state 1.7 ships in. It leaves a view telling
  the listener something false ("no lyrics") that a server update would fix. Acceptable for one
  release, because few listeners run an unattended Docker server, but not as a rule.

## Consequences

- **Positive:** a feature that needs a newer server says so by name, and the listener knows the fix
  is to update the server.
- **Positive:** the contract number keeps one meaning, and the first list doubles as a record of what
  each client release depends on.
- **Tradeoff:** two lists must stay in step: the server's names and the client's table. A typo in
  either reads as a missing feature. A test on each side pins the shared names, and the client
  fails closed to "unknown", never to "missing".
- **Tradeoff:** it helps only clients built after it. App 1.7 ships without it, so a 1.7 listener on
  an old Docker server still sees "no lyrics". Point 6's lyrics rule could ship in a 1.7.x on its
  own, since it needs no server change.
- **Follow-up:** the server half, the client half and the first list. Execution order: server first,
  so the field exists before a client asks for it.
