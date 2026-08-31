# ADR-0100: Connecting an Account Happens in the Listener's App

Status: accepted

Date: 2026-08-30

Supersedes point 1's clause *"No client learns that Last.fm exists"* in
[ADR-0030](ADR-0030-scrobbling-is-the-servers-job.md). The rest of that ADR stands, including the
part that matters most: the server scrobbles.

Extends [ADR-0029](ADR-0029-the-server-stores-no-listener-preferences.md) and
[ADR-0058](ADR-0058-the-web-app-is-an-administration-tool.md).

## Context

Familiar supports several people sharing one library, each scrobbling their own plays.
`LastfmProfile.session_key` is per-profile, the client says which profile it is via `X-Profile-ID`,
and the server scrobbles in the background. The mechanism exists and works.

**But there is no way for a listener to connect their own account from the app they listen in.** The
Mac's settings are Playback, Effects, Downloads and Library. The phone's are Audio. Neither contains
any account or credential surface — grepping both clients for Last.fm, scrobbling, API keys or
accounts returns nothing.

The only place to connect an account is the web admin, which `ADR-0058` point 2 lists under
**Server** — the operator's destination, beside health, diagnostics and API keys. So the one setting
that is unambiguously *a person's own* is reachable only through an administrator surface, on a
machine that is very likely not theirs.

### What is already decided, and is not being reopened

An earlier version of this discussion proposed moving the Last.fm credential to the client.
**`ADR-0029` point 3 already rejected that**, and for a better reason than the ones being offered
now:

> Moving those keys to a client would make them readable by any XSS in the web app *and* require
> transmitting them on every request — strictly worse than where they are. `LastfmProfile.session_key`
> is the same case: **a credential the server scrobbles with, in the background, with no client
> attached.**

That last clause settles it on its own. Scrobbling runs from `/played` events with no client in the
picture, so a key held on a device is unreachable at the moment it is needed. `ADR-0030` point 1 —
the server scrobbles, from listening events it already receives — stands for the same reason.

**So this ADR moves no secrets.** It is about the one thing neither ADR decided: where the *asking*
happens.

### Why the ceremony is different from the credential

Obtaining a Last.fm session key is a browser round-trip: open an authorisation URL, the person
approves, a callback returns a token, the server exchanges it. Two of those steps want things the
server does not have and the listener's app does — a browser in front of the person whose account it
is, and a place to stand while they approve.

The web admin has a browser, which is why the flow ended up there. It does not have the *person*:
on a household server it is opened by whoever administers the box, from their machine, and every
listener has to borrow it to connect an account that is theirs.

### Two things the implementation runs into, both verified

**The server already has the endpoints, and the Swift client cannot reach them.**
`GET /lastfm/auth`, `POST /lastfm/callback`, `POST /lastfm/disconnect` and `GET /lastfm/status` all
exist and work — the web admin drives them today. But `Sources/FamiliarAPI/openapi-generator-config.yaml`
does not list `lastfm`, so none of them is generated. The vendored `openapi.json` contains the paths;
the filter excludes them.

**Admitting the tag would generate two operations that must not exist on a client.** The `lastfm` tag
carries six operations, and two of them are `lastfm_scrobble_track` and `lastfm_update_now_playing`.
Generating those would hand a client the ability to scrobble directly — which is the part of
`ADR-0030` this ADR explicitly does *not* supersede. The filter keys are a union, so this is the same
trap `ADR-0031` recorded for `outputs` and `ADR-0086` for `videos`.

**The callback is bound to the web app, not to whoever started the flow.** `get_auth_url` builds the
`cb=` parameter from `settings.frontend_url` and ignores the caller. Last.fm then redirects a
*browser* there, and `POST /lastfm/callback` attaches the resulting session key to whichever profile
that browser's `X-Profile-ID` names. A flow started on the Mac would therefore connect the account to
the browser's profile — silently, and to the wrong person on a shared server. The `cb` value is a
per-request parameter, so this is fixable rather than fundamental, but it is not optional.

## Decision

1. **The listener's app is where an account is connected.** The Mac and iPhone apps gain an Account
   section showing which Last.fm account the active profile scrobbles to, with connect and
   disconnect. This is the first listener-facing credential surface in either client.

2. **The app runs the authorisation flow; the server keeps the key.** The app asks the server for an
   auth URL, opens it, and the callback completes on the server exactly as it does today. The
   session key is written to `Profile.session_key` and never travels to the client. `ADR-0029`
   point 3 is upheld in full: the secret lives where it is used.

3. **`ADR-0030` point 1's "no client learns that Last.fm exists" is superseded, and only that
   clause.** A client that offers to connect an account plainly knows Last.fm exists. What the
   clause was protecting — that no client is *involved in scrobbling*, so a failed scrobble cannot
   touch a listening event — is untouched and remains the reason scrobbling stays server-side.

4. **The web admin keeps its Last.fm panel.** Removing it would strand a listener whose only client
   is a browser, and would break the operator's ability to see and revoke a connection. `ADR-0058`
   point 2 is unchanged; this adds a second route to the same server state rather than moving it.

5. **Operator credentials do not move and do not appear in a client.** AcoustID, S3 backup, the
   update channel and the `ADR-0045` token belong to whoever runs the server. The distinction this
   ADR draws is **whose account it is**, not which credential is convenient to reach: a listener's
   own scrobbling identity is theirs, and everything else is the operator's.

6. **The app shows which profile it is scrobbling as.** `familiar.server.profileID` already selects a
   profile per device, and today nothing displays the consequence. An Account section that says
   "scrobbling as *jeff*" makes a wrong profile selection visible at the moment it matters instead of
   in somebody else's Last.fm history.

7. **Four operations are generated by name; the `lastfm` tag is not added.** `lastfm_get_auth_url`,
   `lastfm_handle_callback`, `lastfm_disconnect` and `lastfm_get_lastfm_status` — following
   `ADR-0031`'s pattern for exactly its reason. **Do not add `lastfm` to `tags:`**: the filter keys
   are a union, and the tag also carries `lastfm_scrobble_track` and `lastfm_update_now_playing`.
   Generating those would put a client in the scrobbling path, which is the half of `ADR-0030`
   point 1 this ADR upholds.

8. **The app completes its own callback, and the exchange is bound to the profile that started it.**
   The `cb` parameter is per-request, so the app supplies a callback it can receive and then posts
   the token with its own `X-Profile-ID`. Today `get_auth_url` hardcodes `settings.frontend_url`, so
   a Mac-initiated flow would redirect to the web app and attach the account to the *browser's*
   profile. That is a silent wrong-person bug on precisely the shared-library setup this ADR is for,
   and fixing it is part of the work rather than a follow-up.

## Alternatives Considered

- **Move `session_key` to the client and scrobble from the app.** The proposal this discussion
  started from. Rejected by `ADR-0029` point 3, which considered it and found it strictly worse, and
  independently by the fact that scrobbling runs in the background with no client attached — a key
  on a device is not available when the scrobble happens. It would also change the granularity of a
  scrobbling identity from *person* to *device*, which is wrong for two people sharing a machine and
  merely redundant when everyone has their own.

- **Leave it in the web admin and document it.** Free, and it works today. Rejected because it
  requires every listener to open an administration tool on someone else's machine to configure
  something about themselves, and because `ADR-0058` deliberately made that surface the operator's.
  A documented workaround for a structural mismatch is how the "Listening Ideas" defect survived
  four times.

- **Put the whole Last.fm panel in the app and remove it from the web.** Cleaner in one sense: one
  place per thing. Rejected by point 4 — a browser-only listener would be stranded, and an operator
  needs to be able to revoke a connection without borrowing somebody's phone.

- **Have the app hold the key and hand it to the server on each request.** Keeps the credential on
  the person's device while letting the server scrobble. Rejected explicitly by `ADR-0029` point 3:
  transmitting a secret on every request is worse than storing it once, and it would not survive
  background scrobbling with no client attached anyway.

## Consequences

- **Positive** — a listener can connect their own account from the app they listen in, which is the
  gap that prompted this. Nobody has to be shown the administration tool to start scrobbling.
- **Positive** — a wrong profile selection becomes visible in the app rather than in someone else's
  listening history.
- **Positive** — it establishes where the line falls for the next credential: whose account is it.
  `ADR-0099` will add ListenBrainz, which is the same shape — a personal account, a server that uses
  it — and now has a precedent to follow rather than a decision to make.
- **Tradeoff** — two routes to the same server state, which is duplication of a kind `ADR-0081` spent
  effort removing. Accepted because the two audiences are genuinely different, and stated rather than
  hidden.
- **Tradeoff** — the Apple clients gain a settings surface they have never had, on the phone in
  particular, where `ADR-0013` point 2 keeps management off the device. The distinction is that
  connecting your own scrobbling account is not managing the library; if that reading is rejected,
  point 1 should apply to macOS only.
- **Follow-up** — `ADR-0099` proposes ListenBrainz, whose personalised endpoint is only personalised
  if the listener's history is there. Whether Familiar should scrobble to ListenBrainz as well is
  still undecided, and this ADR's Account section is where that would surface.
- **Positive** — the server work is nearly nil. The four endpoints exist and the web admin already
  drives them; what is missing is a generator entry, a per-request callback, and a client.
- **Tradeoff** — point 8 changes an endpoint the web app depends on. `get_auth_url` must keep
  defaulting to `frontend_url` when no callback is supplied, or connecting from the browser breaks.
- **Follow-up** — the app needs somewhere for Last.fm to redirect to. A custom URL scheme is the
  obvious shape on both platforms and is not decided here; whatever is chosen has to be a callback
  Last.fm will accept.
- **Follow-up** — profiles remain unauthenticated: `X-Profile-ID` is an assertion the server does not
  check, so this makes it easier to connect an account, not harder to connect it to the wrong
  profile. That is `ADR-0045`'s job, and it is worth stating that this ADR does not fix it.
