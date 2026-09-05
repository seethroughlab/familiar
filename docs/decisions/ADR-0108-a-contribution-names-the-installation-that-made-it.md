# ADR-0108: A Contribution Names the Installation That Made It

Status: accepted

Date: 2026-09-04

Extends [ADR-0102](ADR-0102-the-community-cache-gains-a-recording-key.md), whose Context weighed what
the community cache discloses and stated that no installation identifier was attached. That is the
premise this record changes, so it is the one that has to argue for it.

Implementation:
- Points 1, 2, 5 and 6 are implemented in the branch this record accompanies. Point 3 needs nothing.
- **Point 4 is not built.** The identifier is written to `settings.json` and is neither shown in the
  admin UI nor resettable from it. That is the gap between what this record asks the user to accept
  and what it currently gives them, and it should close before the next release rather than sit.
- **Accepted 2026-09-05 with point 4 still outstanding, knowingly.** The gap was put to the owner
  and the record was accepted anyway, on the grounds that contribution is opt-in and off by default
  (`community_cache_contribute` is `False`), so nobody is disclosing an identifier without having
  asked to. Recorded because "accepted" and "shipped" are not the same claim, and a later reader
  finding point 4 missing should be able to tell that it was seen rather than overlooked. It
  remains the one point that is *for the user* rather than about the mechanism — points 5 and 6
  promise the identifier is used for the corpus and nothing else, and point 4 is what would let
  someone check that promise instead of taking it.

## Context

Familiar contributes CLAP embeddings to clapback, a public commons it does not own. Contribution is
opt-in and off by default — `community_cache_contribute` is `False`
(`backend/app/services/app_settings.py:81`), and clapback's `ADR-0001` point 11 says it stays that
way.

### What clapback needs, and cannot get from what we send

clapback's whole argument is that an embedding is the output of a pinned function rather than a
claim about the world, so **how many independent parties computed the same vector** is a meaningful
confidence signal — the one AcousticBrainz said it lacked. Its `ADR-0004` point 3 is blunt about what
happens without an identifier: a contribution is accepted and stored, and can never be confirmed,
because nothing can show it came from a different party than the last one.

Familiar is **99.85% of that corpus**. So today the corpus's confidence measure cannot mean anything
at all, and no amount of new contributors fixes the rows already there. The identifier is not a
nice-to-have for clapback; it is the difference between a corpus that can report agreement and one
that cannot.

### What ADR-0102 said, and why it stopped being true

`ADR-0102` was deciding whether to attach a MusicBrainz recording id, which makes the corpus legible
to anyone holding a dump. Isolating that, it noted: *"This is not a disclosure about a person — no
profile, listener or installation identifier is attached, and `contributor_count` is a count rather
than a list."*

That clause was accurate when written and is not any more. It was an observation in service of a
different decision rather than a commitment, but a later reader would reasonably rely on it, so it is
amended in place and this record is why.

### What actually leaves the machine, audited 2026-09-04

For an installation that has opted in:

| sent | what it is |
|---|---|
| `fingerprint_hash` | SHA256 of an AcoustID fingerprint — one-way, and useless without the audio |
| `embedding` | 512 floats describing what the recording sounds like |
| `analysis_version`, `clap_model_version` | which pipeline produced it |
| **`client_id`** | **new: an opaque per-installation UUID** |

No filename, no path, no library contents, no listening history, no account, no address beyond the
one any HTTP request carries. The corpus already sees *that some installation holds a recording whose
fingerprint hashes to this*; the change is that it can now tell two such installations apart.

### The thing actually being traded

An opaque identifier that persists across contributions makes a set of submissions **linkable to each
other**. Someone with the corpus can say "these 20,000 embeddings came from one installation" — which
is roughly what `contributor_count` already implied and now says accurately.

What it does not do is name anyone. There is no email, no account, no name, and nothing that survives
deleting `settings.json`. clapback's `ADR-0004` point 5 makes that a rule on their side rather than a
courtesy: a client identifier is not a person and must not become one.

## Decision

1. **A contribution names the installation that made it.** Familiar sends an opaque identifier with
   every embedding contribution, per clapback's `ADR-0004` point 1. It is self-issued — a random
   UUID, no registration, no key exchange, no server ever asked.

2. **It is generated on first contribution, not at install.** An installation that never opts in
   never has one. This is the cheapest possible version of data minimisation and costs nothing: the
   identifier has no use until there is a contribution to attach it to.

3. **It is not a secret and is not masked.** clapback's `ADR-0004` point 10 says identity there is
   bookkeeping that makes agreement countable, explicitly *not* an abuse control, because self-issued
   identifiers rotate. Masking it in the admin UI would advertise a protection it does not provide.
   It stays out of `secret_keys` deliberately rather than by omission.

4. **The user can see it and reset it.** A persistent identifier the user cannot inspect is worse
   than the same identifier in plain sight. Resetting issues a new one; contributions already made
   keep the old one and are not retractable from here, which is a limit of the mechanism and must be
   said rather than implied. **This is not built yet** — see the `Implementation:` block.

5. **Only embedding contributions carry it.** The features and analysis-detail endpoints have no such
   field, and clapback's `ADR-0001` point 6 gives tier two no quorum, so attaching it there would
   imply a guarantee that does not exist.

6. **It is used for the corpus and nothing else.** Not analytics, not telemetry, not support
   correlation, not a key into any other system here. If a second use is ever wanted, it needs its
   own decision rather than inheriting this one.

## Alternatives Considered

- **Send nothing and keep `ADR-0102`'s premise intact.** Zero disclosure, zero work, and the status
  quo for the life of the feature. Rejected because it quietly makes Familiar's contributions
  worthless as evidence: 99.85% of a corpus that can never confirm anything is a corpus whose
  confidence signal is decorative. Contributing is already a deliberate act by the user; contributing
  in a form that cannot be counted spends their CPU for a weaker result than they think they are
  getting.

- **Derive the identifier from something already stable** — a machine id, a hash of hostname, the
  install path. No new state to store and nothing to lose on a reset. Rejected outright: those are
  linkable to a machine and potentially to a person, which is exactly what clapback's `ADR-0004`
  point 5 forbids, and a derived value cannot be reset without changing the machine.

- **Rotate the identifier on every contribution.** Maximal privacy, and it would look like
  compliance. Rejected because it destroys the property the identifier exists for and does something
  worse than nothing: every resubmission would appear to be a new independent party confirming, which
  manufactures confidence rather than measuring it. Poisoning the signal is not a privacy win.

- **Rotate periodically — monthly, say.** The appealing middle, and it bounds how much history any
  one identifier links. Rejected for the same reason at a slower rate: a re-analysis after rotation
  confirms the installation's own earlier vectors, and neither we nor clapback could tell that from a
  genuine second contributor. A mechanism that is right most of the time and silently wrong the rest
  is worse than one that is honestly limited.

- **Put the identifier behind its own opt-in, separate from contribution.** Defensible on
  consent-granularity grounds. Rejected because it is a second gate in front of the thing that makes
  the first gate worthwhile, for no privacy gain that survives inspection — the identifier is
  meaningless without the contribution it accompanies, and a contribution without it is the case
  point 3 of clapback's `ADR-0004` already handles. The place to decide whether to contribute is the
  contribute switch.

## Consequences

- **Positive** — Familiar's contributions become countable evidence. clapback's `ADR-0008` can report
  a real number of independent confirmations instead of zero, and its `ADR-0007` attestation gains a
  party to count.
- **Positive** — `contributor_count` stops being a figure that rises on retries and starts meaning
  what readers already assume it means, on the corpus side.
- **Positive** — the disclosure is now written down. It was going to be true either way; the
  difference is whether a later reader finds it in a record or in a payload.
- **Tradeoff** — **an installation's contributions become linkable to each other.** That is the whole
  of the change, and it is real: a corpus dump can be partitioned by contributor where before it
  could not. It names nobody, and it is bounded by an opt-in that is off by default.
- **Tradeoff** — point 4's reset cannot retract what was already sent. The mechanism has no delete
  path from this side; clapback's `ADR-0004` point 7 makes deletion admin-only and by identifier,
  which means asking rather than doing.
- **Tradeoff** — a persistent identifier in `settings.json` is one more thing a backup carries. It is
  not a credential and losing it costs nothing but a new identity.
- **Follow-up** — point 4's admin surface: show the identifier, and offer a reset that explains what
  it does and does not undo.
- **Follow-up** — whether Familiar should ever send a recording id alongside, which is `ADR-0102`'s
  decision and a much larger disclosure than this one. Unaffected either way, but the two will be
  read together.
