# ADR-0114: A Contribution Is Keyed on the Fingerprint, Not the Column

Status: accepted

Date: 2026-09-10

Implementation:
- **Accepted 2026-09-10.** Points 1, 2 and 3 are built and tested; points 4 and 5 are operations
  that follow the deploy, and point 6 is deliberately unowned.
- The rule is reimplemented independently in `backend/tests/test_canonical_fingerprint.py` rather
  than imported from clapback's CLI, because what must hold is that two implementations of one
  written rule produce one key. Sharing an import would test agreement with a function rather than
  agreement with the rule, which is the thing that actually broke.
- **Measured before landing**, against the deployed corpus: of 120 escaped-form tracks, 120 of 120
  old keys are present and 1 of 120 canonical keys is. So the backfill re-contributes essentially
  the whole escaped half, and the single hit is a recording this library also holds in raw form —
  consistent with the ~49 duplicate fingerprints found while measuring `ADR-0006` phase 4.

Extends [ADR-0102](ADR-0102-the-community-cache-gains-a-recording-key.md), which chose the AcoustID
fingerprint hash as the community cache's key, and adopts clapback's
[`ADR-0010`](https://github.com/seethroughlab/clapback/blob/main/docs/decisions/ADR-0010-the-corpus-key-is-a-function-of-the-audio.md)
on this side of the wire. It is the sibling of
[ADR-0108](ADR-0108-a-contribution-names-the-installation-that-made-it.md), which did the same for
`client_id` and `pipeline_version`: the corpus decides what a key means, and this record is how this
installation complies.

## Context

`ADR-0102` made the key the SHA256 of an AcoustID fingerprint, and that has been true in the sense
that matters least. What has actually been hashed is the *string this application stored*, which is
not the same thing and turns out not to be the same value either.

### `track_analysis.acoustid` holds the same fingerprint two ways

Measured 2026-09-10, 25,648 non-null rows:

| form | rows | example |
|---|---|---|
| hex-escaped | **14,284** (56%) | `\x41514144744a4c79...` |
| raw base64 | **11,364** (44%) | `AQADtJESbVkUhYL8...` |

They are not two kinds of fingerprint. `\x41514144` is hex-of-ASCII for `AQAD`: decode the escaped
form and the base64 string comes back unchanged. The column is `text` and almost certainly once held
`bytea`, so a migration rendered the existing values in Postgres's hex output format; new writes come
from a subprocess that returns a decoded `str` (`backend/app/services/analysis.py:750`) and land raw.

### Both encodings are already keys in the live corpus

Probed 2026-09-10 against the deployed commons, 400 random local tracks hashed exactly as stored:
211 of 212 escaped hashes found, 188 of 188 raw ones. So this is not a local tidiness problem. It is
a property of the public corpus, and this installation put it there.

### The premise this contradicts

`backend/scripts/backfill_community_cache.py:15` states the rule and defends it with a real
measurement: *"The fingerprint is hashed as stored, not decoded"*, because hashing the stored string
matched 232 of 500 tracks in the corpus and hashing the decoded bytes matched 1.

**That measurement was correct and the conclusion is what cemented the problem.** Hashing as stored
is the only way to match a corpus built by hashing as stored; it also guarantees that corpus can
never be matched by anyone who did not share this application's schema history. The rule was right
locally and wrong globally, and nothing about running it locally could have revealed that.

### Why it matters now rather than whenever

clapback's `ADR-0009` point 6 shipped a second client on 2026-09-10 — a CLI that fingerprints audio
and hashes the result. It is correct, and *because* it is correct it disagrees with this application
about the key for every recording stored escaped here. Two clients that never agree and never
contradict each other are invisible to one another, and clapback's `ADR-0008` reports exactly the
confirmations and contradictions that would then be missing. The first real second contributor would
produce misleading evidence, and nothing after the fact separates that from two people owning
different music.

Familiar is the reason the corpus has this defect, so it is the one that should carry the cost of
removing it.

## Decision

1. **Hash the fingerprint, not the column.** `hash_fingerprint`
   (`backend/app/services/community_cache.py:244`) canonicalises before hashing, via
   `canonical_fingerprint` (`:212`), which undoes Postgres's hex escaping and nothing else.

2. **The decode is deliberately narrow**: a leading `\x`, an even length, and a decode to printable
   ASCII. A chromaprint fingerprint is base64 and cannot begin with a backslash, so the rule cannot
   misfire on a real one; anything unrecognised passes through untouched rather than being guessed
   at, because a wrong guess produces a key that is wrong in a new way and nothing downstream can
   tell.

3. **The 11,364 rows already stored raw keep the keys they have.** This corrects one half of the
   column and must not disturb the other, or it strands rows it was not aimed at. That is a tested
   property, not an intention.

4. **The rows keyed on the escaped form are re-contributed rather than relabelled**, by running the
   existing backfill after this change. The vectors are already stored locally, so this re-sends
   rather than recomputes — it costs a paced run, not a day of CPU, and no embedding changes.

5. **The keys that strands are deleted from the corpus.** They are unconfirmable rows that no correct
   client will ever look up, the same category as the 47,486 that clapback's `ADR-0006` phase 4
   removed. This installation can enumerate them exactly, because it still holds the fingerprints
   that produced them: the old key is `sha256` of the stored string, which is what this record stops
   computing but can still compute deliberately.

6. **The column itself is normalised separately, or not at all.** With point 1 in place the stored
   encoding no longer affects the key, so rewriting 14,284 rows buys tidiness rather than
   correctness. It is not a prerequisite and should not be smuggled into this change.

7. **Cache lookups for the affected tracks will miss until point 4 completes, and that is
   acceptable.** A miss costs a local recompute, which is the behaviour before the cache existed. It
   is a temporary cost bounded by one backfill run, paid to stop publishing a key nobody else can
   reproduce.

## Alternatives Considered

- **Keep hashing as stored, and let clapback's CLI adopt Familiar's convention.** It would work, and
  it is the cheapest change on this side: one sentence in the other project's record. Rejected
  because the convention is not expressible in terms of audio — it would require every future client
  to hex-encode a value chromaprint already handed it, in order to match a Postgres rendering of a
  column in somebody else's database. A commons cannot ask that of a stranger.

- **Normalise the column first and leave `hash_fingerprint` alone.** Tempting, since it fixes the
  cause rather than the symptom, and the hashing code is then correct by construction. Rejected as
  insufficient rather than wrong: rows already contributed keep their old keys whatever the column
  says afterwards, so it does not repair the corpus, and it leaves the rule implicit in data where
  the next migration can undo it silently. It is worth doing, which is point 6, but not instead.

- **Re-contribute by bumping `EMBEDDING_VERSION` and letting re-analysis carry it.** The mechanism
  already exists and was used for clapback's `ADR-0006` phase 3. Rejected because it spends a day of
  CPU recomputing vectors that clapback's own measurement showed reproduce to 5e-16 — it would buy
  nothing but the form of a rule, and `ADR-0104` point 6 already records one such bump as an
  exception rather than a precedent.

- **Leave the escaped rows in the corpus as orphans.** No deletion step, no admin calls. Rejected
  because the corpus has just finished removing 47,486 rows for being unconfirmable, and quietly
  contributing 14,284 more of the same kind under a different cause is the failure that record was
  written to stop.

## Consequences

- **Positive** — the key becomes a property of the recording. Two people who own the same recording
  compute the same key, which is what clapback's premise requires and what `ADR-0102` intended.

- **Positive** — Familiar and the clapback CLI now agree, which is the precondition for the corpus
  measuring agreement at all. Tested here against an independent reimplementation of the rule rather
  than against a shared import, because the property is that two implementations of one written rule
  agree.

- **Tradeoff** — cache misses for ~14,284 tracks until the backfill runs, each costing a local
  recompute.

- **Tradeoff** — a paced backfill run and a batch of admin deletions, both with the failure modes the
  last two runs had. The sweep of 2026-09-07 died silently at 16,500 of 26,428; whatever runs here
  should report an exit code, and its finish should be observable rather than inferred.

- **Follow-up** — point 6, normalising the column, is unowned and deliberately so.

- **Follow-up** — the deletion in point 5 needs clapback's admin endpoint, which is not public. It is
  an operator action on a corpus with one operator, which is fine now and is not a mechanism a second
  contributor could use for their own mistakes.

- **Follow-up** — nothing checks that a client's key is canonical, and nothing can: the corpus
  receives a digest. clapback's `ADR-0007` attestation is the only thing that would ever catch this
  class of error, and it remains unbuilt.
