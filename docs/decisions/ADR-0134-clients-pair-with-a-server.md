# ADR-0134: Clients Pair with a Server

Status: accepted

Date: 2026-09-29

Implementation:
- **2026-09-29, `familiar`: the server and web half (points 2, 4, 5, 6).** The Apple half (point 1
  and the phone's side of 4 and 5) is a `familiar-apple` change of its own.
  - **Point 2.** `python -m app.serve` refuses any non-loopback `--host` when no token is configured,
    before it migrates or binds anything, and names both ways to create one. Binding beyond loopback
    sets `advertise_port`. *Minting* the token on first run, and opening the listener on the first
    pairing, belong to Familiar Server (ADR-0136), which does not exist yet. What the server itself
    guarantees is the refusal.
  - **Point 4.** `server_id` and `server_name` live in `settings.json` (`app/services/server_identity.py`).
    The id is minted once, under a lock; the name defaults to the host name without `.local`.
    `GET /api/v1/contract` now reports both (additive; contract still v1), so a client that
    connected by address learns what to remember. `app/services/advertise.py` registers
    `_familiar._tcp` through `zeroconf`, now declared directly rather than inherited from
    `pyatv`/`pychromecast`. It runs only when `advertise_port` is set (`FAMILIAR_ADVERTISE_PORT`,
    or `app.serve` on a LAN bind). In Docker's bridge network, mDNS does not reach the LAN and the
    container's port is not the host's. Its TXT record is `id`, `name`, `contract`, and a test pins
    that the token is never among them.
  - **Point 5.** `GET /api/v1/auth/pairing` returns the id, name, token, advertised port and LAN
    addresses. It is 409 on a server with no token, and behind the gate otherwise. The server does
    **not** build the link, because it cannot know how a phone reaches it (behind Docker its
    addresses are the container's; behind Tailscale the useful host is a name). The web admin
    builds it from the host the page was loaded from, and falls back to a LAN address only when
    that host is loopback. The link also carries `name`, beyond the point's `id/host/port/token`,
    because the confirmation step has to name the server. Server → Access gains a Pair a Device
    panel: a QR code (`qrcode`, rendered as an image rather than injected SVG), the address, and
    the link on request. It offers to create a token when there is none, and stores it in this
    browser at once, because the gate turns on the moment one exists.
  - **Point 6.** `initServerToken` takes `#token=…` from the fragment, stores it, and removes it
    from the address bar with `replaceState`, keeping any other fragment parameters.
  - **Point 3's premise was false, and is now true.** "Media stays exempt" assumed ADR-0045's
    exemption existed. It did not: every `/api/` path was gated. The Pair a Device panel's "Create
    server token" would therefore have broken web artwork, network-output playback and every Apple
    client stream in one click. `MEDIA_ROUTES` in `app/api/auth.py` now exempts `GET`/`HEAD` on
    the seven media shapes. Checked on a real tokened server: media returned 404 for an unknown id
    with or without the token; `/tracks`, lyrics and an artwork `POST` returned 401 without it.
  - **Checked on a real server (2026-09-29):**
    - A LAN bind without a token was refused.
    - A token was minted over loopback.
    - A LAN bind then advertised `jeffbook._familiar._tcp` on the Mac's LAN and Tailscale
      addresses. macOS's own `dns-sd -L` resolved it and read the TXT `id`, `name`, `contract`.
    - `/auth/pairing` answered 401 without the token and returned the full payload with it.
  - Tests: `tests/test_pairing.py`, the `app.serve` refusal and advertise tests in
    `tests/test_server_without_docker.py`, and `src/api/__tests__/pairing.test.ts`.
- **2026-09-29, `familiar-apple` #198: the Apple half (points 1, 4, 5).**
  - **Point 1.** `ServerTokenMiddleware` sits beside `ProfileHeaderMiddleware`, reading the token
    per request. The command stream, screenshot upload and mixtape download send it by hand.
    Embedded Discover receives it in the URL fragment (point 6's mechanism, reused). Tokens live
    in the Keychain under `server_id`, readable after first unlock for background downloads.
  - **Point 5.** `PairingLink` parses strictly. It **form-decodes**, because the web admin's
    `URLSearchParams` writes a space as `+` and Foundation does not read it back. A test
    comparing the two sides' exact encodings caught "Studio+MacBook". The app registers the
    `familiar` scheme, so the Camera app is the phone's scanner. There is no in-app scanner.
  - **Point 4.** `ServerBrowser` resolves `_familiar._tcp` over IPv4. `checkContract` follows a
    paired server whose stored address stopped answering.
  - **Checked on a throwaway simulator against a tokened server:** the prompt named the server
    and address; accepting it listed a profile that the server returns only with the token.
    **The setup screen's Bonjour list stayed empty there, so in-app discovery is unproven on a
    device.**
  - **Left:**
    - the MCP helper still sends no token (it needs a shared keychain group)
    - the visualizer bundle's lyrics fetch is gated
    - library stores still word a token 401 as an unknown profile
- **2026-10-04: first paired phone, and point 5's link gained a scheme.** An iPhone paired with
  Familiar Server over Wi-Fi from the QR code, and browsed and streamed with the token. The
  same check against the NAS found that **a link carried no scheme and the app built every paired
  address as `http://`** (`PairingLink.swift`), while a NAS reached over Tailscale is
  `https://…:8443` through `tailscale serve`, a port that speaks nothing else. A code scanned
  from that admin page would have pointed the phone at a port that cannot answer it. The web
  admin now adds `scheme=https` when the page was loaded over https (`api/pairing.ts`), and
  keeps `http` implicit, so every link an older app reads is unchanged. A loopback page still
  falls back to plain http on the LAN, which is what the server's own listener speaks. The app
  reads `scheme` (`http` or `https`, anything else refused), defaulting to `http`.

Extends [ADR-0045](ADR-0045-familiar-authenticates-inbound-requests.md),
[ADR-0131](ADR-0131-the-server-is-its-own-app.md)

## Context

Under ADR-0131, a client's server may be a NAS, the demo, or Familiar Server on its owner's own
computer, and clients never assume which. So pairing is the one way any client reaches any server,
including a player on the same Mac as its server. The computer case is the new one. It joins
office and café Wi-Fi, and its owner has not chosen to run a network service and would not
recognise one. Today a server:

- **listens on every interface with no authentication by default.** The container runs uvicorn
  on `0.0.0.0` (`docker/Dockerfile:284`). The token gate is built (`backend/app/api/auth.py`), but it
  is off until someone mints a token under Server → Access (`/server/access`). ADR-0045 point 5 (on
  by default, and refuse a non-loopback bind without a token) is accepted and deliberately deferred.
- **cannot be reached by the Apple app once it has a token.** `X-Familiar-Token` appears in
  `familiar-apple` only in `App/MCPHelper/StreamableHTTP.swift`, the MCP bridge. `FamiliarAPI`'s
  client installs `ProfileHeaderMiddleware` and nothing else. ADR-0045's 2026-09-08 correction
  records this as the larger of point 5's two blockers.
- **is found by typing its address.** `App/Shared/SetupView.swift` takes an address like
  `10.0.0.130:4400`. Nothing advertises or browses: `familiar-apple` has no `NWBrowser`, and
  `backend/app` does not use `zeroconf`. It is installed anyway, as a dependency of both `pyatv`
  and `pychromecast` (`backend/uv.lock`). A laptop's DHCP address changes, so a typed address is
  wrong within days.

The web client already holds a token: `packages/frontend/src/api/base.ts` keeps it in
`localStorage` under `familiar_server_token` and sends it on every request. Only the Apple client and
the setup flow are missing.

## Decision

1. **The Apple client holds the server token.** `FamiliarAPI` gains a `ServerTokenMiddleware`
   beside `ProfileHeaderMiddleware`. The token lives in the Keychain, keyed by server identity
   (point 4), not by address. This clears ADR-0045 point 5's larger blocker for every deployment,
   not only this one.

2. **A desktop server has a token from its first start, and listens beyond loopback only once a
   device is paired.** `python -m app.serve` (ADR-0132) binds `127.0.0.1` by default and refuses
   any other host with no `access_token` set. Familiar Server (ADR-0136) mints the token
   on first run. It opens the LAN listener when the owner first pairs a phone, and closes it if
   they unpair the last device. Nothing on a freshly installed laptop is reachable from the
   network.

3. **Media stays exempt from the gate**, for the reasons ADR-0045 records: network outputs and
   guest listeners cannot hold a credential. The artwork-hash oracle that ADR-0045 names as the
   exemption's one real leak is now exposed on shared Wi-Fi, not only on a tailnet. Converting
   artwork to signed URLs becomes a Follow-up with a reason.

4. **A server has a stable identity, advertised on the local network.** On first start the server
   generates a `server_id` (a UUID in `data/settings.json`). It advertises
   `_familiar._tcp` through `zeroconf`, with a TXT record carrying the `server_id`, a display name
   and the API contract version (ADR-0113), and never the token. Clients remember a server by its
   `server_id` and re-resolve its address through Bonjour when the stored one fails. The phone
   needs `NSLocalNetworkUsageDescription` and `NSBonjourServices`.

5. **Pairing is one link, `familiar://pair?id=…&host=…&port=…&token=…`, delivered two ways.**
   - **As a QR code**, shown by Familiar Server's menu and by the web admin's Server → Access. The
     phone scans it. A manual fallback shows the same values as text. Setup on the phone lists
     servers found through Bonjour, and choosing one prompts for the code.
   - **As a link opened on the same Mac.** Familiar Server's "Open in Familiar" opens the link, and
     the player registers the `familiar` URL scheme and handles it. There is no camera step.

   **A client always confirms before pairing** ("Connect to *Studio MacBook* at 192.168.1.20?"),
   because any web page can open a `familiar://` link. An unconfirmed link would let a page point
   the player at a server of its choosing.

   Either way, the client stores the token under that `server_id` and connects. The two apps share
   no app group or container (ADR-0135 point 5). A server on the same Mac is paired exactly like a
   NAS, only without the camera.

6. **The web admin receives the token by URL fragment.** Familiar Server's "Open Admin" opens
   `http://127.0.0.1:<port>/#token=…`. The web client stores it through its existing
   `setServerToken` and strips the fragment. A fragment is never sent to the server or logged.

7. **Any server with a token can pair, the NAS included.** Discovery and the QR code are not
   desktop-only. Whether Docker installs switch point 5 on by default is still ADR-0045's to
   decide. This ADR removes its blocker but does not flip it.

8. **Off the local network is not decided here.** ADR-0096's Tailscale recommendation stands for
   people who want it. The ordinary answer to "away from home" is ADR-0137: the phone already has
   what it needs.

## Alternatives Considered

- **Loopback only, with no LAN listener.** Nothing to misconfigure. Rejected: a Familiar Server
  that the owner's phone cannot reach defeats the premise of running one.
- **LAN-open by default, as the container is.** The phone works with no pairing step. Rejected: it
  is the arrangement ADR-0045 exists to end, placed on the least-controlled networks Familiar has
  run on, where anyone on a café's Wi-Fi could read `/settings` and every stored API key.
- **Pair through iCloud (CloudKit shares the token between a person's devices).** No QR code at all
  for Apple users. Rejected: a NAS has no iCloud account, so one of the two server forms (ADR-0131
  point 2) would need a second mechanism, and the server's own authentication would depend on Apple's
  service being reachable.
- **Per-profile passwords.** Already rejected by ADR-0045 for reasons unchanged here. A person
  typing a password on a phone is also the step a QR code removes.
- **Exempt loopback requests from the gate, so the local browser needs no token.** Simpler than
  point 6. Rejected: any process on the machine, and any other user account on a shared Mac,
  could then act as the owner. The fragment handoff costs one line in the web client.

## Consequences

- **Positive:** a coworker pairs their phone by pointing it at their screen. A laptop that has
  paired nothing listens on nothing.
- **Positive:** ADR-0045 point 5's recorded blockers are cleared: the Apple client holds the token,
  and the demo keeps its opt-out. Turning it on everywhere becomes a small, separate decision.
- **Tradeoff:** an existing Apple install against a NAS with a token configured must be paired once
  after the update. The NAS's own users are few and can be told.
- **Follow-up:** artwork behind signed URLs (point 3). ADR-0045 had already separated this; shared
  Wi-Fi gives it a date.
- **Follow-up:** `docs/SITE-CLAIMS.md`'s ADR-0096 row, which expires when the token ships.
