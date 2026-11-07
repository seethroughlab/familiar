# ADR-0165: The Apple Clients Are Localized and the Server Stays English

Status: proposed

Date: 2026-11-07

## Context

Familiar has been on the App Store in all 27 EU storefronts since 2026-11-06. The listener who
asked for that (familiar #321) then offered to help with translation. What the project needs most is
more listeners, and a listing and an app in a listener's own language serve that directly. But
nothing in either repository is set up for a second language, and the cost of adding one depends
almost entirely on where the line is drawn. This record draws it.

What exists today, counted on `familiar-apple` at `c650915` and `familiar` at `98550f78`:

- **No localization at all in the Apple clients.** `knownRegions` is `Base, en`; there is no
  `.xcstrings` or `.lproj`; `SWIFT_EMIT_LOC_STRINGS = NO` appears four times in
  `Familiar.xcodeproj/project.pbxproj`; `Package.swift` declares no `defaultLocalization`. The only
  localization API in use is the `LocalizedStringResource` title of `CancelDownloadsIntent`.
- **About 530 literal sites Xcode would extract on its own**, all in `App/Shared` and the widget
  (`Text` 170, `Button` 135, `Label` 49, `accessibilityLabel` 38, and smaller counts of the rest).
- **Several hundred user-facing strings it would not.** These are built in code: `var title: String`
  on models in `FamiliarKit` (`QueueOrigin`, `ShufflePreset`, `SmartRule.summary`, `AwayCause`),
  display names derived from a `rawValue`, the 18 sentences of `ServerErrorMessage.swift` that
  ADR-0124's `RepositoryError` maps to, and the Live Activity's "Downloading %d of %d".
  `FamiliarKit` and `FamiliarAppCore` live in a Swift package, whose strings need `Bundle.module`.
- **English grammar written by hand.** `Count.of(n, "track")` in `BrowseText.swift` appends an "s"
  at 17 call sites; five more sites use an inline `n == 1 ? "" : "s"`; `ListPhrase` joins with
  "and"; `Clock.long` builds "1 hr 5 min". None of these survive a language with other plural rules.
- **The server sends almost no prose that the native clients show.** The recap is structured data,
  and ADR-0157 already put "every word on every card" in the client's `RecapStory`. Suggested tracks
  (ADR-0093) and rediscovery send the tracks a suggestion came from, not a sentence. Mood tags are a
  closed set of 49 values in `backend/app/services/mood_tags.py`. **The exception is errors:**
  `ErrorCode` has four members, about 226 `raise` sites carry a hand-written English message, and
  `ServerErrorMessage` shows that message whenever no code matched.
- **Nothing in the backend reads a locale.** No `Accept-Language`, no gettext, no babel.
- **The web frontend has no i18n library.** The Mac embeds its Discover surface (ADR-0016,
  ADR-0017), which has about 60 English strings of its own.

## Decision

1. **The Apple clients are localized.** That covers iOS, macOS, the Live Activity widget, CarPlay and
   the Info.plist usage strings, plus the App Store listing. English remains the development
   language and the fallback. String Catalogs (`.xcstrings`) are the format: one for the app targets,
   one per package target that shows text, and one for `InfoPlist`.
2. **English literals are the catalog keys.** `Button("End session")` stays as it is written. Twenty-two
   tests read Swift source as text through `AppSource.swift` and `EngineSource.swift` and match such
   literals. Opaque keys would break every one of them and make the source harder to read.
3. **The server stays English and locale-blind.** Clients localize from structured data. Where a
   client must explain a server error in the listener's language, the server gains an `ErrorCode`
   for it (ADR-0129 point 6, documented in `docs/ERROR-CONTRACTS.md`), and the client maps the code.
   Errors with no code fall back to a translated sentence for their HTTP status class, with the
   server's English `message` kept as secondary detail. New codes are added for errors a listener
   actually meets on the phone or the Mac, not for every exception class.
4. **The embedded Discover surface, the web admin app and the website stay English.** A localized Mac
   app will show an English Discover pane until a later record decides otherwise.
5. **Grammar is the platform's.** Counts use catalog plural variants (or `inflect: true`); lists,
   durations and numbers use the `formatted` APIs. Hand-built English plurals and joins are replaced
   as part of the first language, not after it.
6. **A language ships only after a native speaker has reviewed it.** A machine-drafted catalog is a
   starting point. A language whose catalog has untranslated entries is not shipped; a check in
   `familiar-apple`'s CI enforces that for every language listed in `knownRegions`.
7. **Names the server generates and saves stay as written** ("Based on …", "Albums by …",
   "{name} (Copy)"). Once saved, a playlist name is the listener's data, which they can rename.

The order of work: the App Store listing first, since it needs no code; then the catalog plumbing and
the strings Xcode extracts; then the strings it cannot; then error codes; then localized screenshots.
The detailed plan goes in `familiar-apple` as `PLAN-localization.md` when the work begins.

## Alternatives Considered

**Localize the server through `Accept-Language`.** Every client would then get translated text for
free, including the web app and embedded Discover. Rejected because it means a second string pipeline
(gettext or similar) across about 226 hand-written messages, most of which a listener never sees.
`ERROR-CONTRACTS.md` deliberately calls `message` text "for people" that "may be reworded at any
time". And the recap, ADR-0157's precedent, already went the other way: the client owns the words.
Point 3 gets the errors listeners actually meet for a few new codes.

**Also localize embedded Discover, passing a `lang` to `/embed`.** This would remove the one English
pane in a localized Mac app. Deferred rather than rejected: it needs an i18n library in
`packages/frontend` for about 60 strings on a surface the phone does not show as a web page. It
should be reconsidered once one language has shipped and someone has seen how much the English pane
actually matters.

**Machine-translate everything and ship without review.** It would be fastest, and would cover many
languages at once. Rejected for the reason the offer in #321 is valuable: a music player's labels are
short and context-free ("Played", "Kept", "Away"), which is exactly where machine translation guesses
wrong. A wrong guess tells listeners in that market that the app was not made for them.

**Opaque keys** (`"ambient.end.button"`). Conventional in large apps, and it lets English wording change
without invalidating translations. Rejected per point 2: the source-reading tests, and an
English-first codebase where the literal *is* the documentation of what a button says.

## Consequences

- **Positive:** a listing and an app in the listener's language, in the market Familiar just entered.
  After the first language, each further one costs only translation and review.
- **Positive:** point 5 fixes grammar that is already wrong in English in places (bare `"\(n) tracks"`
  for n = 1).
- **Tradeoff:** every new user-facing string now has to be translated before release, and point 6's
  check will fail CI until it is. That is the intended cost.
- **Tradeoff:** a localized Mac app shows an English Discover pane, and server errors without a code
  read in English under a translated headline.
- **Follow-up:** the App Store listing for the first language, entered by hand in App Store Connect.
  `scripts/upload-screenshots.py` uploads only to the first localization and needs a loop.
- **Follow-up:** `UITests/ScreenshotTests.swift` selects elements by English labels. They need
  `accessibilityIdentifier`s before screenshots can be captured per locale.
- **Follow-up:** CarPlay's tab title constant says "Favourites", while the rest of the app says
  "Favorites". Fix it when the constants move to the catalog.
