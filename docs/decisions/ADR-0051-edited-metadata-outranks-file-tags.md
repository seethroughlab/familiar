# ADR-0051: Edited Metadata Outranks File Tags

Status: proposed

Date: 2026-08-11

## Context

Familiar has always treated the file as the source of truth for tags. `LibraryScanner._update_track`
(`backend/app/services/scanner.py:835`) assigns `title`, `artist`, `album`, `album_artist`,
`track_number`, `disc_number`, `year` and `genre` straight from what the file carries, and until now
nothing recorded that a person had deliberately corrected any of them. Re-tagging a file in another
app, re-encoding it, or replacing it changes its hash, and the next scan restored the old value —
silently, with no event and no way to notice except spotting the old spelling again weeks later.

That was tolerable while editing tags meant opening the web app. It stopped being tolerable when the
Mac gained a track metadata editor, because a form that quietly loses your work is worse than no
form.

**A premise this investigation disproved, and which was stated on two screens as fact.** The Mac's
editor and its library sync pane both said that a library sync undoes metadata edited in Familiar.
It does not. The scanner re-reads a file's tags only under `if reread_unchanged or file_changed:`
(`scanner.py:491`), and `reread_unchanged` defaults to `False` in both the scanner
(`scanner.py:280`) and `POST /library/sync` (`api/routes/library_sync.py:60`) — which is what the
Mac's Sync Now button calls, with no parameters. **An ordinary sync has never touched edited
fields.** The overstatement went unchallenged until Jeff asked whether it was really true; it is
recorded here because a warning that overstates a danger teaches people to distrust a feature that is
safe, and because the false version was already copied into two screens, a commit message and a pull
request before anyone checked the condition.

The real exposure is narrower and worth fixing: **a field is lost only when the file itself changes.**

There is no shortage of places that write these fields. Seven at the time of writing — six that
express a person's choice, and one that retracts one:

| Path | Where | Is it a person's choice? |
|---|---|---|
| `PATCH /tracks/{id}/metadata` | `api/routes/tracks/metadata.py:262` | Yes — somebody typed it |
| `POST /tracks/bulk/metadata` | `services/bulk_editor.py:125` | Yes |
| Approving a pending track with edits | `api/routes/pending_review.py:265` | Yes |
| Group metadata on a pending folder | `api/routes/pending_review.py:554` | Yes |
| `PATCH` on a pending track | `api/routes/pending_review.py:710` | Yes |
| Applying an accepted proposed change | `services/proposed_changes.py:326` | Yes — somebody accepted it |
| Undoing one | `services/proposed_changes.py:399` | **No — it is a retraction** |

`user_overrides` (`db/models/tracks.py:131`) is not the place for this. It is documented as
overrides for *analysis* values — `{"bpm": 124.0, "key": "Am"}` — and is merged only where the key
already exists in the computed feature set. It answers "what did the analyser get wrong", which is a
different question from "who wins between the library and the file".

Confusingly, `pending_review.py:265` already contains a private function named
`_apply_metadata_overrides`, which applies caller-supplied values while approving a track. It is
unrelated to any of this and the name collision is noted so nobody assumes the mechanism already
existed.

## Decision

1. **A tag field a person set in Familiar outranks the file. A field nobody has touched follows the
   file.** The rule is per field, not per track: correcting an album name must not freeze the genre.

2. **The record lives in a new `tracks.metadata_overrides` JSONB column**, mapping field name to the
   chosen value, added by migration `20260811_metadata_overrides`. Not `user_overrides`, for the
   reason in Context — the two answer different questions and merging them would make both harder to
   reason about.

3. **Only the eight fields a rescan actually assigns are eligible**: `title`, `artist`, `album`,
   `album_artist`, `track_number`, `disc_number`, `year`, `genre`. The bulk editor accepts 17
   (`bulk_editor.py:20`), but `_update_track` never assigns composer, lyricist, grouping, comment,
   the sort fields or lyrics, so recording them would claim a protection that does not exist.

4. **A cleared field is recorded as an explicit null, not an omission.** Emptying a genre is a
   decision; treating a falsy value as "no override" would let the next scan refill it from the file.

5. **The rule lives in one module**, `services/metadata_overrides`, with a `record` half and an
   `apply` half. Seven call sites have to agree about it, and a rule copied into seven files is the
   shape that goes wrong later. `record` returns a new mapping rather than mutating, because
   SQLAlchemy does not notice in-place changes to a JSONB column and a helper that depends on the
   caller remembering that is a trap.

6. **Overrides are applied after the file's tags, at the end of `_update_track`.** Ordering is the
   whole decision: applied first, the file overwrites them and nothing has changed. The canonical
   artist ids are resolved from the file's own tags before the override lands, because those resolve
   *identity* and the override corrects the display fields on top.

7. **Accepting a proposed change records an override; undoing one removes it.** An undo is a
   retraction, not a new opinion — a field that has been un-changed should go back to following the
   file, or the first accepted suggestion would pin it forever and "undo" would be a lie.

8. **There is no user-facing way to un-pin a field yet, and the clients must not claim otherwise.**
   Point 7 covers undo; nothing else does. Until a "revert to the file's tags" affordance exists, an
   edited field stays edited, and this is a known limit rather than a hidden one.

## Alternatives Considered

- **Write the correction back into the file's tags.** The obvious fix, and genuinely tempting: it
  makes the file true and the whole problem disappears. Rejected because Familiar has never written
  to the music files and starting to is a much larger decision than this one — it needs a story for
  permissions, for formats whose tags it cannot write, for files on read-only media, and for what
  happens when the write half-fails across an album. `PATCH /tracks/{id}/metadata` deliberately
  writes to the database only, and `ArtworkUploadResponse.embedded_in_file` is already hard-coded
  `False` for the same reason. Worth revisiting as its own ADR.

- **Store the overrides inside `user_overrides`.** One fewer column and one fewer migration. Rejected
  because the merge loop at `api/routes/tracks/metadata.py` only copies keys that already exist in
  the feature dictionary, so tag keys would sit in the column being silently ignored by the code that
  appears to consume it — a shape that reads as supported and is not.

- **Never re-read tags for a track that has ever been edited.** Simpler to implement and simpler to
  explain. Rejected because it throws away the good half of rescanning: a person who fixes one
  misspelt album still wants a corrected genre or a newly-added year to arrive from the file. The
  per-field rule costs one dictionary and keeps that.

- **Compare against the tags seen at last scan, and keep the library value only when it differs.**
  Infers intent instead of recording it, and gets the interesting case exactly wrong: when somebody
  edits a field to the same value the file already had, and the file later changes, the inference
  says "not edited" and discards a deliberate choice. Recording the choice at the moment it is made
  is both simpler and correct.

- **Leave it, and warn on the editor instead.** What the code did, by accident, before this. Rejected
  on the evidence in Context: the warning that existed was not merely insufficient, it was false,
  and a warning is in any case a way of asking the listener to accept a defect.

## Consequences

- **Positive:** A correction survives the file changing underneath it, which is the only reason to
  offer an editor at all. The Mac's editor becomes trustworthy rather than provisional.
- **Positive:** The rule is per field, so rescanning keeps doing its job for everything a person has
  not touched.
- **Positive:** One module holds the rule, and the scanner logs which fields it kept — so the
  behaviour is observable in a log rather than only inferable from what did not happen.
- **Tradeoff:** The library is now authoritative over the file for edited fields, inverting the
  scanner's standing assumption. Anyone reasoning about where a value came from has a second place
  to look.
- **Tradeoff:** An edited field cannot currently be handed back to the file except by undoing a
  proposed change. Point 8 makes that explicit rather than leaving it to be discovered.
- **Tradeoff:** Seven write paths must remember to record. Two do so far; the rest are follow-up, and
  a path that forgets fails quietly — it simply does not protect the edit, which looks exactly like
  the old behaviour.
- **Follow-up:** Record overrides on the four `pending_review` and `proposed_changes` paths, and
  remove them on undo per point 7.
- **Follow-up:** A "revert to the file's tags" affordance, per point 8, and an indication in the
  editor that a field is currently overriding the file.
- **Follow-up:** The Mac's editor and library sync pane both describe this behaviour and must be
  reworded **only once this is deployed**, not when it merges. Their current text is accurate for a
  server without this change, and changing it early would repeat the mistake recorded in Context.
