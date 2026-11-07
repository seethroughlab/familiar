# ADR-0164: The Embedded Visualizer Page Is a Paired Client

Status: proposed

Date: 2026-11-06

Extends [ADR-0033](ADR-0033-the-embed-bridge-gains-a-return-channel.md) point 8 and
[ADR-0134](ADR-0134-clients-pair-with-a-server.md) point 6.

## Context

ADR-0033 point 8 says lyrics do not travel on the channel because the page fetches them. ADR-0134
records "the visualizer bundle's lyrics fetch is gated" as left to do. **Both assume a fetch that was
never written**, and the same gaps stop every other API call the page makes.

Two things block the page, and each is enough on its own:

- **Origin.** The page loads from `familiar-visualizer://bundle`, which does not match the CORS regex
  (`main.py:717`). A preflight for that origin against the maintainer's server on 2026-11-06 returned
  400.
- **Token.** `renderVisualizer.tsx` never calls `initServerToken`, unlike `renderApp.tsx:19` and
  `renderEmbed.tsx:51`, and the visualizer's URL carries none, unlike
  `EmbeddedDiscoverView.swift:105`.

Artwork works because `_OPAQUE_ORIGIN_READABLE` (`main.py:730`) exempts it. So the failure is invisible:
the page looks fine with a cover and a palette, while `features` stays null and the ranking behind
Match to the Music cannot run. By reading the code, that feature has not worked in the app. This has
not yet been confirmed on a device, and an earlier note says it did work, so the first device run after
this lands should check.

ADR-0087 also promises plugins lyrics on `familiar:track`, and the contract disagrees with itself:
`VISUALIZER_API.md:105` and `examples/lyric-pulse` use `startTime`, while the server, the SDK and the
host send `time`. So wiring the fetch alone would still leave Lyric Pulse blank.

## Decision

1. **The page is a client of its server like the Discover embed.** The token travels in the URL
   fragment, as in `EmbeddedDiscoverView.swift:105`, and `renderVisualizer` calls `initServerToken`
   during boot.

2. **`familiar-visualizer` joins the allowed origins.** Only that scheme: the `Origin: null` exemption
   for sandboxed plugins stays limited to media. A plugin still has no access to the token or the API.

3. **The page fetches lyrics for plugins,** by calling `useSyncedLyrics` in `EmbedVisualizer`, and so
   ADR-0033 point 8 becomes true.

4. **Lines are sent with both `time` and `startTime`.** Honours the published shape without breaking
   anything that uses the SDK's.

5. **A test runs the real page.** A Playwright spec against the built `VisualizerBundle.html` feeds a
   frame and asserts a lyrics request with the token, and that a plugin receives the lines. Every
   existing test injected lyrics past the seam that was missing.

## Alternatives Considered

**The app fetches lyrics and pushes them through the frame.** It avoids origin and token entirely, since
ADR-0160's native client already has the answer. Rejected: ADR-0033 deliberately keeps the channel
identity-only, and it would still leave `features` and ranking broken, which need the origin and the
token anyway.

**Allow any custom scheme, or all origins, on the API.** Simplest to write. Rejected because
`allow_credentials=True` is set, and the point of the list is that it is a list.

**Drop lyrics from the plugin contract.** With both first-party lyric documents gone, nothing shipped
needs them. Rejected: ADR-0087 published it, Lyric Pulse depends on it, and fixing it costs one hook.

## Consequences

- **Positive:** track features and Match to the Music start working in the app.
- **Positive:** third-party plugins get what the docs say they get.
- **Tradeoff:** Match will run in production for the first time, so its behaviour when it swaps
  visualizers mid-session is unproven. Check on a device.
- **Tradeoff:** a token in a URL fragment is the same exposure the Discover embed already
  accepts. The fragment is not sent to the server, and the plugin's sandboxed frame cannot read it.
- **Follow-up:** the server fix needs a server release; against an older server the page stays as broken
  as it is now, with nothing worse.
