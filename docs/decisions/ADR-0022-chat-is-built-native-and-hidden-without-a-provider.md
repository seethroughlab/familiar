# ADR-0022: Chat Is Built Native, and Hidden Without a Provider

Status: superseded by [ADR-0043](ADR-0043-the-llm-surface-is-an-mcp-server.md)
Date: 2026-08-02

Implementation:
- The Mac surface shipped in `familiar-apple` #54: `ChatStore` (status through the generated client,
  stream through a hand-rolled `URLSession` reader) and `ChatView`, with the decidable parts in
  `FamiliarKit` — `ChatEvent`, `ChatStreamParser`, `ChatLineSplitter`, `ChatConversation`,
  `ChatPlaybackCommand`, `ChatMarkdown`.
- **Three places the server did not match its own documentation**, found building it. It emits nine
  event types, not the seven its docstring lists (`navigate` and `ephemeral_playlist_created` are
  undocumented). `error` arrives in two shapes — `content` from the service, `message` from the
  route's exception handler. And `control_playback` speaks in absolutes while `FamiliarPlayer`
  offers toggles, so a direct wiring would have paused music that was already playing.
- **Point 2's premise held for a reason it did not anticipate**: the assistant's prose arrives as
  whole `text` events, not token deltas, so streaming buys tool-call visibility rather than a typing
  effect. The tool events really are the whole of it.
- The tradeoff this ADR recorded — a hand-parsed event set outside ADR-0007's generation — cost a
  bug immediately. `URLSession.AsyncBytes.lines` drops empty lines, which in SSE terminate a frame,
  so every reply accumulated into one unparseable payload and the surface answered every question
  with silence. The parser's own tests passed, having fed lines from a splitter that *does* produce
  the empty strings. `ChatLineSplitter` moved the splitting to where a test can fail on it.
- Point 7's phone half and Listening Ideas: `familiar-apple` #55 (open at the time of writing). The iOS floor of 15 was the real
  cost — `TextField(axis:)` and `lineLimit(1...6)` are iOS 16, `onChange(of:initial:)` is iOS 17 —
  so the phone composes on one line rather than the floor being raised.
- Point 3's rule applies to the web app too, in `familiar` #78 (open at the time of writing): `chatApi.getStatus` had never been
  called there, so an install with no provider showed a chat box that failed on send.
- Restoring the "Listening Ideas" that `familiar` #76 removed needed **no third bridge message and
  no ADR of its own**: `/library/discover/prompts` carries the `library` tag and was already
  generated, so the native surface asks for them itself and ADR-0020 point 2's cap of two stands.

Extends [ADR-0016](ADR-0016-embedded-web-surfaces-on-the-mac.md)

## Context

[ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md) point 4 put AI chat in the native v1 scope
and it is the last item there still unbuilt. Nothing has decided *how* it is built:
[ADR-0016](ADR-0016-embedded-web-surfaces-on-the-mac.md) settled embed-versus-native for Discover and
Music Map only, and chat is a third surface its point 1 has never been applied to.

The question arrived from the other end. `familiar` #76 removed the "Listening Ideas" cards from the
embedded Discover surface because pressing one did nothing: a curated prompt is a message for the
chat and has no other destination, `triggerChat` sets `rightPanel: 'chat'`, only `AppShell` renders
that panel, and the embed mounts Discover without a shell. It was the third defect of that shape,
after the Unheard spinner and the dead purchase links, and the only one that could not be fixed by
supplying the destination — because there is no chat anywhere in the native app to supply.

**A premise worth recording, because it cuts against building this at all.** Chat was deprioritised
on 2026-07-31 on the evidence of real use: *"AI chat is becoming less of a priority through usage. I
just didn't end up using it as much as I thought. I still like the idea of the CLAP and other
analysis for creating playlists, but the actual chat is a lower priority for now."* That judgement is
not overturned here. What changed is that the native app now has surfaces that *lead* to chat and
cannot complete the journey, so the choice is between building the destination and permanently
removing the paths to it. Point 2 below is shaped by the deprioritisation: the parts worth showing
are the tool calls that build playlists, not the prose.

Four facts about the server, verified against the repo and the running instance at write time:

- **`chat` is already a generated tag.** `openapi-generator-config.yaml` lists it among the eleven,
  so `POST /api/v1/chat` and `GET /api/v1/chat/status` already exist in the Swift client. Unlike
  ADR-0014, this needs no widening of the generated surface.
- **`GET /chat/status` already answers the capability question**, returning `configured` and
  `provider`. Its docstring says it exists "so the frontend can show appropriate warnings before the
  user tries to chat". Nothing in the web app has ever called it — `chatApi.getStatus`
  (`packages/frontend/src/api/chat.ts:174`) has no callers. It reports the **active** provider, so
  selecting `openai` without OpenAI credentials returns `configured: false` even when
  `ANTHROPIC_API_KEY` is set.
- **Both chat endpoints raise `LLMNotConfiguredError`** when the active provider is unconfigured
  (`backend/app/api/routes/chat.py:140` and `:179`), so an unguarded surface fails at the moment the
  user has already typed something.
- **The server holds no conversation.** `ChatRequest.history` carries up to 100 messages on every
  request, and the web app's history lives in the browser's IndexedDB (`db.chatSessions`, via
  `services/chatService.ts`). There is nothing server-side for a second client to read.

Applying ADR-0016 point 1's test — churn and size — to the chat surface as it stands, counting
components and hooks and excluding tests:

| | Chat | Discover (embedded) |
|---|---|---|
| Lines | 965 (`ChatPanel` 637, `ChatHistoryPanel` 327, `index` 1) | 2,828 |
| Commits since 2026-02-01 | 6 | 15 |

Chat's transport and persistence add 466 lines beyond that — `services/chatService.ts` (269) and
`api/chat.ts` (197) — of which the native app reimplements only the SSE reader, taking the rest from
the generated client. Discover's equivalent lives in the shared `api/library.ts` and is not counted
on either side.

## Decision

1. **Chat is built native, not embedded.** ADR-0016 point 1's test is churn and size, and chat is a
   third of Discover's UI with under half its churn — small and settled, which is the native side of
   that test. Embedding it would also put the bridge under pressure it was explicitly capped against:
   a chat response carries `queued_tracks` and `playback_action`, so the surface whose entire product
   is queueing tracks and controlling playback would need messages for both, against
   [ADR-0020](ADR-0020-the-embedded-surface-can-ask-the-app-to-navigate.md) point 2's cap of two.
   Native, the generated `ChatResponse` is handed straight to `FamiliarPlayer` and there is no bridge
   at all.

2. **It streams, through a hand-rolled `URLSession` reader rather than the generated client.**
   `POST /chat/stream` is a `text/event-stream`, which [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md)
   point 8 already keeps outside generation — the same carve-out audio streaming and the two
   `/library/map/*/stream` variants use. The non-streaming endpoint would be simpler and is already
   generated, but tool execution takes real time and it returns nothing until every tool has run.
   **The `tool_call` and `tool_result` events are the point, not the prose**: "Searching your
   library", "Creating playlist" is the analysis-driven work that holds the value here, and a surface
   that sits silent for twenty seconds and then prints a paragraph shows none of it.

3. **The destination is absent when the active provider is not configured.** The app reads
   `GET /chat/status` at launch and on foreground; when `configured` is false the chat destination
   does not appear in the root list or the sidebar at all. Not a disabled row, not a greyed control,
   and not an error raised after the user has typed a message — showing a surface that cannot work is
   the defect this ADR exists to stop repeating, and doing it one step later is not a fix.

4. **A configuration that changes underneath is handled as an unavailable state, not a crash.** The
   status check races the server: a key can be removed after launch, and `LLMNotConfiguredError` can
   arrive on a send from a surface that was legitimately shown. That response puts the open surface
   into the native unavailable state of ADR-0016 point 7, and the destination goes away on the next
   status read.

5. **Queued tracks and playback actions from a chat response go to the native player directly.** One
   player, one queue, one now-playing entry — as with CarPlay and with the embedded surface. Chat is
   another way of asking for something to play, not a second playback path.

6. **Conversations are per-device and are not synced.** The server holds no history and the web's
   lives in IndexedDB, so the native app keeps its own. Presenting the two as one history would mean
   inventing server-side storage, which is a larger decision than this one and belongs in its own
   ADR if it is ever wanted.

7. **Both platforms, Mac first.** Chat is a way of finding something to play, so it is a legitimate
   destination on the phone under [ADR-0018](ADR-0018-the-phone-navigates-from-a-root-list.md) and
   does not touch [ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md) point 2's line about
   management surfaces. It ships on the Mac first and the phone second, the same order Discover took
   through ADR-0016/0017 and then ADR-0019.

## Alternatives Considered

**Embed the chat panel in the `WKWebView`, as Discover is.** The consistent choice, and it would
reuse 965 lines rather than reimplementing them. Rejected on ADR-0016 point 1's own test: chat is
small and settled where Discover is large and moving, so the criterion points the other way. The
bridge is the stronger objection — chat's output is `queued_tracks` and `playback_action`, so an
embedded chat needs the app to play and to control playback on its behalf, and ADR-0017 is the record
of how many construction paths a bridge misses on a surface far less playback-centric than this one.

**Use the non-streaming `POST /chat`.** Already generated, no SSE reader, and it returns the same
tool calls and queued tracks in one structured response — a genuinely smaller build. Rejected because
it returns them only after every tool has finished. The wait is the tool execution, so the endpoint
that hides tool execution is the one that makes the wait worst, on the surface with the least
goodwill to spend.

**Show chat always, and report "no provider configured" when the first message fails.** How the web
app behaves today. Rejected: it is the Listening Ideas defect moved one step later — the user has
composed a message before learning the feature does not work here. The endpoint that would prevent it
has existed, unused, the whole time.

**Add the `settings` tag to the generated surface to read the provider configuration.** Rejected for
the reason the queue-sync pane was: filtering to a tag generates its writes as well as its reads, so
this would make server configuration editable from the app, which ADR-0013 point 4 forbids.
`/chat/status` answers the question from a tag that is already generated.

**Leave chat web-only and delete the paths to it.** The honest minimum, and #76 is exactly this done
for one surface. Rejected as a direction because ADR-0001 point 4 put chat in native v1 scope, and
because the paths keep appearing: Listening Ideas is one, and every "ask about this artist" affordance
in the web app is another.

## Consequences

- **Positive.** The native app gains the last unbuilt item in ADR-0001 point 4's v1 scope, and gains
  it in the form that shows the analysis work rather than the chat box.
- **Positive.** `familiar` #76's removal becomes reversible on a rule already written. ADR-0020 point
  3's bar for a third bridge message is "the native app already does this better, and the page
  cannot" — which a chat prompt fails today only because there is no native chat. Once there is, a
  `chat` intent clears that bar exactly, and Listening Ideas can return to the embedded surface.
- **Tradeoff.** A second chat implementation to keep working. Point 1's test says this is the cheap
  case, but 6 commits in six months is not 0, and each one is now a question about two clients.
- **Tradeoff.** The SSE reader is hand-written and untyped, outside the generation that ADR-0007
  exists to guarantee. It parses a documented event set — `text`, `tool_call`, `tool_result`,
  `queue`, `playback`, `done`, `error` — that nothing enforces against the server.
- **Tradeoff.** Conversations do not follow the user between the web app and the Mac, and the Mac and
  the phone do not share one either.
- **Follow-up.** The web app should gate on `GET /chat/status` too. It has never called it, so a web
  install with no provider configured shows a chat box that fails on send — the same defect this ADR
  refuses on native, still present on the surface that has it today.
- **Follow-up.** Restoring Listening Ideas needs its own ADR under ADR-0020 point 3, after the native
  chat surface exists to receive the intent.
