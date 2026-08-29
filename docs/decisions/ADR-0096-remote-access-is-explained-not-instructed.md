# ADR-0096: Remote Access Is Explained, Not Instructed

Status: proposed

Date: 2026-08-29

Extends [ADR-0095](ADR-0095-the-install-section-is-platform-first.md). Reads alongside
[ADR-0045](ADR-0045-familiar-authenticates-inbound-requests.md), whose Decision is accepted and
whose implementation this ADR depends on **not** existing yet.

## Context

Remote access is step 4 of the install section, titled "Reach it from anywhere". It gives one
`tailscale serve` command, a sentence naming Cloudflare Tunnel and WireGuard as alternatives, and
one imperative: *"Don't port-forward `4400` to the open internet."*

It never says why, and the why is not a preference.

### Familiar has no authentication today

`ADR-0045` — "Familiar Authenticates Inbound Requests" — is **accepted** and says in point 5 that
"a server with no token configured refuses to start". None of it is built: there is no token in
`backend/app/api/deps.py`, none in `app/config.py`, none in `app/main.py`, and no auth middleware.
Its own Implementation block explains why, and it is a good reason — point 2, closing the 158
allowlisted operations, "is the actual project", spanning ~30 modules, while the token itself is a
day's work.

So the accurate statement about a Familiar server in August 2026 is: **anything that can reach it
can use it.** Read the library, browse the filesystem through the directory picker, queue playback.
The site's "don't port-forward" line is therefore not hardening advice; it is the difference between
a private server and a public one.

This is not a secret and does not become one by being written down. The software is MIT-licensed and
readable, `ADR-0045` is in the repository, and the site already tells people not to expose the port.
What is missing is the sentence that makes that instruction make sense — and a reader who does not
understand an instruction is a reader who will eventually work around it.

### Why this is a separate ADR

`0095` decides how someone gets Familiar running on their own machine. This decides what they are
told about letting it off that machine, it rests on a different fact (`0045`'s state, not the
install path), and its content **expires**: when `0045` ships, the argument below changes shape.
Executing them together would tie a page rewrite to a claim with a known end date.

## Decision

1. **Remote access becomes its own section, after Install rather than inside it.** It is a decision
   made once, with a consequence, not a fifth step of setup. Someone who only ever listens at home
   should be able to finish the install and stop.

2. **The section leads with the reason, not the command.** Familiar has no login. That single fact
   is what makes the recommendation follow, and it is stated plainly and once — not as a warning
   banner, and not repeated in three places, which reads as either alarm or apology.

3. **Tailscale is the recommended default and is named as such.** Not "one option among several".
   It is the only one of the alternatives that gives a private network *and* a working certificate
   *and* requires no router configuration, and the recommendation is more useful than the neutrality.

4. **The alternatives stay, with the distinction that matters made explicit.** Cloudflare Tunnel,
   WireGuard and a reverse proxy remain listed. What gets added is that a reverse proxy is only a
   boundary if it authenticates — putting nginx in front of an application with no login publishes
   the application through nginx. That is the mistake this section exists to prevent, and the
   current page's flat list of four options invites it.

5. **The site states nothing about Tailscale's pricing, plans, limits or company that it has not
   checked.** It links. Third-party terms change without touching this repository, and `ADR-0055`
   point 2 has already been burned once by a claim about somebody else's product — two cells of the
   comparison table were wrong in Familiar's favour until they were checked against Plex's own
   documentation.

6. **The claim carries an expiry naming `ADR-0045`.** Its row in `docs/SITE-CLAIMS.md` records that
   the wording depends on Familiar having no authentication, so that shipping the token is a reason
   to revisit the page rather than something discovered later by a reader.

7. **No scare copy, and no security theatre.** No shield iconography, no "hackers", no CVE
   language. The reader is being told how a thing works so they can make one decision. This is the
   same register `docs/MACOS_BEGINNER.md` already uses and the opposite of most self-hosting
   documentation.

## Alternatives Considered

- **Leave it as install step 4 and add one sentence of explanation.** Cheapest, and it fixes the
  literal gap. Rejected because remote access is not a step of installing — burying it in a numbered
  sequence means the reader who stops at "it works on my laptop" never reads it, and that reader is
  precisely the one who later types their public IP into a router.

- **Say nothing about authentication and just recommend Tailscale.** Avoids advertising that the
  server has no login. Rejected on two counts: it is the reason, so removing it leaves an
  unexplained instruction people route around; and `ADR-0055` point 2's whole subject is claims that
  quietly stop being true — a privacy page that told readers their conversations went to Anthropic
  when Familiar holds no key. Being vague to look better is how that happened.

- **Wait for `ADR-0045` to ship and describe the authenticated world.** Tempting, because then the
  advice is durable. Rejected: point 2 of that ADR is a ~30-module project with no date, and the
  page has to be true in the meantime. Writing for a version that does not exist is how the site
  described a Capacitor iOS app two days after `packages/ios` was deleted.

- **Recommend Cloudflare Tunnel instead.** Genuinely competitive — no client on the listening
  device, and it survives CGNAT. Rejected because it terminates at a third party who can see the
  traffic, and it publishes to the internet with access control bolted on rather than making the
  server private. For an application with no login that difference is the whole question.

## Consequences

- **Positive** — the strongest instruction on the page stops being unexplained.
- **Positive** — the reverse-proxy trap is named. It is the most likely way a careful person gets
  this wrong, and today the page lists it as an equal option.
- **Positive** — writing this down puts a date on `ADR-0045`'s absence in a place that is read by
  people rather than only by contributors.
- **Tradeoff** — the site states plainly that a Familiar server has no login. That is already
  derivable from the repository and from the existing warning, but it is more prominent, and someone
  will read it as a reason not to install.
- **Tradeoff** — recommending one third-party service in a project whose premise is not depending on
  services. Point 3 accepts this: the recommendation is for reaching your own server, and the
  alternatives stay listed.
- **Follow-up** — when `ADR-0045` ships, this section and its `SITE-CLAIMS.md` row are revisited.
  Point 6 exists so that is a scheduled edit rather than a discovery.
- **Follow-up** — `docs/` has no remote-access document; the material lives in the FAQ and this
  section. If the section grows past a screen it should become one, and the site should link it,
  following `0095` point 3.
