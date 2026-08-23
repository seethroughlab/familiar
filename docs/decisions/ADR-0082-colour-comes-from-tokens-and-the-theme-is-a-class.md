# ADR-0082: Colour Comes from Tokens and the Theme Is a Class

Status: proposed

Date: 2026-08-18

Extends [ADR-0058](ADR-0058-the-web-app-is-an-administration-tool.md), whose point 5 keeps the theme
when the rest of the listener preferences leave, *"because it applies to the administration interface
itself"*.

## Context

The application themes itself three different ways, and one of them does not work at all.

**`light:` is not a Tailwind variant, and 102 classes across 18 files use it.**
`components/Admin/*` and `components/Settings/*` are styled with `light:bg-zinc-100`,
`light:text-zinc-900` and similar. The project is on Tailwind v4, configured CSS-first: `index.css`
begins `@import "tailwindcss"` with two `@source` directives, **there is no `tailwind.config.*`
anywhere in the repository**, and nothing registers `@custom-variant light`. An unregistered variant
compiles to nothing, so every one of those 102 classes is inert. The newest screens in the
application — the three `ADR-0058` destinations — have never had a working light theme.

**The older components ternary by hand.** `AppShell`, `Sidebar`, `ContentToolbar` and `MobileNav`
read `useThemeStore((s) => s.resolvedTheme)` and pick class strings in JSX; `AppShell.tsx` alone does
this about twenty times. This works, and it puts theme logic in every component that has a colour.

**`StatusMenu` and `PlayerBar` ignore the theme entirely** and hardcode `bg-zinc-800`, so they are
dark in a light interface.

**The tokens to do it properly already exist and are used by almost nothing.** `index.css:12-31`
defines `--bg-primary`, `--bg-secondary`, `--bg-tertiary`, `--text-primary`, `--text-secondary`,
`--text-muted` and `--border-color` for `:root, .dark` and again for `.light`. Their only consumers
are `body`, the scrollbar rules and `#root`. Every component reaches past them to the raw zinc scale.

**There are two accents.** `green-500` for active navigation and focus rings — the player's accent,
inherited from Spotify-shaped chrome — and `cyan-400` for the admin cards added under `ADR-0058`.

**One trap makes this riskier than it looks.** `packages/web/src/embed.tsx:1` and `visualizer.tsx:1`
both import this same stylesheet. Those documents run inside `WKWebView`s in native windows: the
visualizer draws on black, and Discover sits in an app with its own appearance. A theme driven by
`prefers-color-scheme` would flip both to a light palette on a light-mode Mac, silently, with nothing
in CI able to see it — and `ADR-0054` makes the illustration set dark-only.

## Decision

1. **Colour comes from tokens.** The existing `--bg-*`, `--text-*` and `--border-color` variables are
   exposed to Tailwind through `@theme` as `--color-bg`, `--color-surface`, `--color-surface-raised`,
   `--color-fg`, `--color-fg-muted`, `--color-fg-subtle` and `--color-border`, so `bg-surface` and
   `text-fg-muted` resolve correctly in both themes with no variant and no ternary.

2. **The theme is a class on `<html>`, and never a media query.** `themeStore` already toggles
   `.dark` / `.light`; that stays and becomes the only mechanism. **No bare
   `@media (prefers-color-scheme: …)` rule may exist at `:root` in `index.css`**, for the reason in
   the Context. A lint enforces it, because the failure is invisible to every automated check and
   appears only on someone's Mac.

3. **The embedded documents declare their theme explicitly.** `embed.html` and `visualizer.html` set
   `class="dark"` on `<html>`, so neither depends on a store they do not mount or a default that
   might change.

4. **All 102 `light:` classes are deleted**, together with their `dark:` twins in the same files and
   every `resolvedTheme === 'light' ? … : …` ternary in the shell and navigation. After this,
   `resolvedTheme` is read in exactly two places: the theme store and the settings panel that changes
   it.

5. **One accent.** `--accent`, set to the admin `cyan-400`, replaces both it and `green-500`. The
   green is the player's, and the player is being deleted.

6. **Status colours are semantic tokens, not raw hues.** `--color-danger`, `--color-warning`,
   `--color-success` — `StatusMenu` distinguishes severity with amber, orange, blue and red today and
   would otherwise stay hardcoded, which is how it became theme-blind in the first place.

## Alternatives Considered

**Register `@custom-variant light` and keep the 102 classes.** The smallest possible fix — one line,
and every inert class starts working. Rejected because it enshrines writing every colour twice, and
because the pair `bg-zinc-800 light:bg-zinc-100` is where the two halves drift: one gets updated and
the other does not, and nothing fails.

**Standardise on the hand-ternary pattern the shell already uses.** It works today and is easy to
follow in a single file. Rejected because it puts theme resolution in every component with a colour,
makes each one re-render on theme change, and cannot be checked — a component that forgets is exactly
`StatusMenu`, and nothing noticed.

**Use Tailwind's built-in `dark:` variant with a class strategy**, which is the conventional answer.
Rejected as a smaller version of the same problem: it is still two class names per colour, and the
tokens that would make it unnecessary are already defined and already switch on the same class.

**Do the full visual redesign now** — type scale, spacing, density, a real component set. Explicitly
out of scope: this ADR fixes a mechanism and a bug, and leaves the appearance where it is. A redesign
whose diff also contains a correctness fix is a redesign nobody can review.

## Consequences

- **Positive** — light mode works on the three destinations for the first time.
- **Positive** — theme handling moves from three mechanisms in every component to one in the
  stylesheet, and colour becomes reviewable: a raw `zinc-` in the admin tree is a lint failure.
- **Positive** — the player's green accent leaves with the player, rather than outliving it in the
  navigation.
- **Tradeoff** — every admin and settings component is touched. The diff is large, mechanical, and
  almost entirely unreviewable line by line; it is verified by looking at the screens in both themes,
  which is manual work.
- **Tradeoff** — `index.css` is shared by all three entry points, so this change reaches the
  embedded surfaces, which have no automated coverage. Point 2's lint and point 3's explicit class
  are the mitigations, and they are not a substitute for opening both on a Mac and a phone.
- **Tradeoff** — the CSS gzip budget is checked by `web/scripts/check-bundle-budgets.mjs`. Removing
  102 inert classes should shrink it, but `@theme` emits variables for every token, so it must be
  measured rather than assumed.
- **Follow-up** — `VisualizerBundle.html` contains the Tailwind build of this stylesheet and is
  vendored by hand into `familiar-apple`. It must be re-vendored after this change, and
  `ADR-0078` point 4's revision stamp is what makes a stale copy visible.
