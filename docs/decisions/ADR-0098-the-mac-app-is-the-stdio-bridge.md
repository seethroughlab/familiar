# ADR-0098: The Mac App Is the stdio Bridge

Status: accepted

Implementation:
- Built 2026-08-30 in `familiar-apple` on `adr-0098-mcp-helper`: four Swift files under
  `App/MCPHelper/` and a Run Script phase that compiles them into
  `Familiar.app/Contents/MacOS/familiar-mcp`. Verified against the live server — 39 tools,
  `get_library_stats` returning 26,434 tracks, and `launch_familiar` opening the app.
- **Point 4 is proven, not argued.** The test run opened the *Debug build the helper was inside*
  rather than `/Applications`. That is exactly the bug `FAMILIAR_APP_PATH` exists to work around in
  the Python bridge, and it cannot occur here because the helper resolves its own bundle from
  `argv[0]`.
- **Point 2's reasoning about `UserDefaults` was backwards, and the code now does the opposite of
  what this ADR describes.** The Context says macOS keys defaults by bundle identifier, so a
  separate executable must name the app's suite explicitly. That is true *outside* the bundle.
  Shipped *inside* it, the helper inherits `com.familiar.player`, so `UserDefaults.standard` already
  is the app's domain — and asking for your own identifier as a suite is refused by AppKit with
  *"does not make sense and will not work"*. The first bundled build reported "no server configured"
  on a machine where Familiar is configured and running. `AppConfiguration.appDefaults` now matches
  on the identifier and picks; both paths carry the reason.
- **A Swift-specific bug worth recording.** The MCP streamable-HTTP frames are CRLF-delimited, and
  in Swift `"\r\n"` is a **single grapheme cluster** — so `split(separator: "\n")` does not match
  it. The entire body came back as one line, nothing began with `data:`, the parse produced nothing,
  `send` returned `nil`, and the helper answered nothing at all while logging that it had connected.
  `split(whereSeparator: \.isNewline)` is correct. Cost an hour, and the compiler is silent about
  it.
- **A Run Script phase rather than a second Xcode target**, which point 1 did not specify. The
  helper is four files with no dependencies beyond Foundation and AppKit; a native target would add
  build configurations, a scheme and a dependency edge to say the same thing. It runs before code
  signing, so the binary is signed as part of the bundle. **A first-class target is the follow-up if
  the helper ever needs its own signing identity or entitlements** — recorded rather than left
  implicit.
- Point 5 is unchanged and still holds: `backend/scripts/mcp_bridge.py` stays for Linux and Windows.
  The Python bridge was also used, unchanged, to unblock the listener the same day while this was
  being written.

Date: 2026-08-30

Extends [ADR-0043](ADR-0043-the-llm-surface-is-an-mcp-server.md), which put the LLM surface at
`/mcp`, and [ADR-0044](ADR-0044-mcp-clients-actuate-playback-through-a-command-channel.md), which
made the Mac app the thing that actually plays. Supersedes `backend/scripts/mcp_bridge.py` on macOS
only.

## Context

Familiar's MCP server is HTTP. Claude Desktop's `claude_desktop_config.json` accepts **stdio servers
only** — `command`, `args`, `env` — so a remote URL has to be added through Settings → Connectors
instead. `backend/scripts/mcp_bridge.py` exists to cover that gap, and its docstring is explicit
about why it is in this repository rather than an `npx` of somebody else's proxy: *"Familiar is
self-hosted software … downloading a third-party bridge onto the listener's machine to reach their
own music server is the wrong shape."*

That reasoning is right and does not go far enough. The listener already installed a `.app`.

### What broke, and what it revealed

On 2026-08-30 the custom connector stopped working with *"Couldn't register with Familiar's sign-in
service"* — Claude attempting OAuth Dynamic Client Registration. Familiar has no OAuth: `ADR-0045`
is accepted and unimplemented, and there is no authorization server to register with. The server
itself is unchanged and healthy; `/mcp` answers `Bad Request: Missing session ID`, which is a live,
unauthenticated MCP endpoint.

So the remote-connector path is closed until `ADR-0045` ships an authorization server, which is a
project rather than a fix. The stdio path is the one that works, and it is worth putting somewhere
better than a Python script in a repository the listener has no other reason to clone.

### The configuration the bridge needs is configuration the app already has

`mcp_bridge.py` is configured entirely through environment variables:

| variable | who else already knows it |
|---|---|
| `FAMILIAR_MCP_URL` | `ServerConfiguration` — the app's server address |
| `FAMILIAR_MCP_PROFILE_ID` | `familiar.server.profileID` in the app's `UserDefaults` |
| `FAMILIAR_MCP_TOKEN` | the app's credential, once `ADR-0045` ships |
| `FAMILIAR_APP_PATH` | **the app's own path** |

The last row is the argument in miniature. The bridge has a `launch_familiar` tool and must be
*told where the app is*, with a comment explaining that LaunchServices may prefer an Xcode build
over `/Applications`. A helper inside the bundle knows its own path by construction; that entire
class of problem does not exist for it.

The token row is the second argument. The script's docstring notes that
`claude_desktop_config.json` is world-readable in the user's Library folder, and settles for
`env` over `args` so the value stays out of the process list. Once `ADR-0045` ships, that file
holds a server credential in plaintext. The Mac app has a Keychain.

### The app is already required

`ADR-0044` makes the Mac app the thing that plays. An MCP host's playback tools work only when a
client is attached, and `ADR-0043` point 2 already excludes the tools that need one from the
server's own surface. The bridge exists to talk to a server the app is already talking to, on a
machine where the app is already running.

## Decision

1. **The Mac app ships a stdio MCP bridge as a helper executable in its own bundle**, at
   `Familiar.app/Contents/MacOS/familiar-mcp`. Claude Desktop spawns it with `command` and no
   `args`; it speaks stdio to the host and HTTP to `/mcp`.

2. **It reads its configuration from the app, not from the host's config file.** Server address and
   profile come from the same `UserDefaults` suite the app writes; the token, once `ADR-0045`
   exists, comes from the Keychain. `claude_desktop_config.json` names a path and nothing else, so
   it holds no address, no profile id and no credential.

3. **It is a separate process, not a channel into the running app.** Claude Desktop spawns one per
   session and expects it to exit with the session. Reaching into the GUI app over XPC would tie an
   MCP session's lifetime to whether somebody had the app open, and make "the app is not running" a
   failure of the tool surface rather than of one tool.

4. **`launch_familiar` stays, and gets correct by construction.** The helper is inside the bundle it
   would launch, so it opens *that* app rather than whichever one LaunchServices currently prefers.
   This is the one tool that genuinely cannot work from the server (`ADR-0029` point 5 leaves device
   identity uninvented, so there is no door to knock on).

5. **`backend/scripts/mcp_bridge.py` stays, for everything that is not a Mac.** Linux and Windows
   hosts have no bundle to ship a helper in, and the script is the only option there. Its docstring
   gains a line pointing macOS users at the app. **Two bridges is the cost of this decision** and is
   stated rather than hidden: the tool-forwarding logic exists twice, in two languages.

6. **The two must not drift, and the check is the tool list.** A test asserts that the helper and
   the script expose the same tool names for the same server, so a tool added to one and not the
   other fails rather than silently differing by host.

7. **This does not close the remote-connector path, and does not pretend to.** When `ADR-0045`
   ships an authorization server, a custom connector becomes possible again and is the better
   experience for anyone not on a Mac. This is the bridge that works meanwhile, and on a Mac it may
   remain the better one because of points 2 and 4.

## Alternatives Considered

- **Do nothing; keep pointing people at `mcp_bridge.py`.** It works today, and it is already
  written. Rejected because it asks a listener who installed an app to clone a repository, install
  `uv`, and hand-write four environment variables — three of which the app already knows — into a
  world-readable file. The script's own docstring rejects a third-party proxy on the grounds that
  downloading something to reach your own music server is the wrong shape; a git checkout is the
  same shape.

- **Implement `ADR-0045` and use a normal remote connector.** The proper fix, and it removes the
  bridge entirely rather than duplicating it. Rejected as the answer to *this* question because it
  is a ~30-module project with no date, and because even after it ships, points 2 and 4 still favour
  a local helper on a Mac — the connector cannot launch the app or read the Keychain.

- **Have the helper talk to the running app over XPC**, so it reuses the live session and
  configuration. Tempting, and it would make `launch_familiar` unnecessary. Rejected by point 3: it
  makes every tool depend on the app being open, and an MCP host that reports thirty-six tools which
  all fail because a window is closed is worse than one that reports them and can open the window.

- **Ship the helper as a separate download.** Keeps the app bundle unchanged. Rejected because a
  second thing to install is the problem this ADR is solving, and because a helper outside the
  bundle cannot know the bundle's path — which is precisely the bug `FAMILIAR_APP_PATH` exists to
  work around.

- **Write the helper in Python and embed the interpreter.** Reuses the existing implementation
  verbatim and removes point 5's duplication. Rejected: it puts a Python runtime inside a Swift app
  bundle to avoid writing about 200 lines of Swift, and the App Store review surface for an embedded
  interpreter is worse than the duplication it saves.

## Consequences

- **Positive** — configuring Familiar in Claude Desktop becomes one path in one file. No address, no
  profile id, no token, no repository.
- **Positive** — the credential moves from a world-readable JSON file to the Keychain, before
  `ADR-0045` creates one worth stealing.
- **Positive** — `launch_familiar` stops guessing which build to open, which is a real bug today for
  anyone who has ever built the app in Xcode.
- **Tradeoff** — the tool-forwarding logic exists twice, in two languages. Point 6 makes drift a
  test failure rather than a discovery, but it is still two implementations.
- **Tradeoff** — macOS-only. Everyone else keeps the script, so the documentation has to describe
  two paths and say plainly which is which.
- **Follow-up** — the Tailscale `serve` configuration on the NAS has **Funnel on port 10000 pointing
  at `127.0.0.1:8000`**, which is not Familiar — `familiar-api` publishes host port 4400, and 8000
  is a service titled "Familiar Cache". The one publicly reachable endpoint answers 404 for `/mcp`.
  Unrelated to this ADR, found while diagnosing it, and worth fixing before anything relies on
  off-tailnet reach.
- **Follow-up** — `/register` and `/.well-known/*` return **200 with `index.html`** from the SPA
  catch-all, so an OAuth discovery attempt gets HTML where it expects JSON and reports a registration
  failure rather than an absence. Making those paths honest 404s would have turned the incident that
  prompted this ADR from a mystery into a one-line answer.
