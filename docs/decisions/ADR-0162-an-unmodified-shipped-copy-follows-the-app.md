# ADR-0162: An Unmodified Shipped Copy Follows the App

Status: proposed

Date: 2026-11-06

Supersedes [ADR-0089](ADR-0089-the-app-bundle-seeds-the-folder-and-is-not-a-source.md) point 5. Points
1–4 and 6 stand.

## Context

ADR-0089 point 5: *"The app makes no promise to update or migrate a copy the user now owns; a new app
version's copy arrives only through Restore."* Seeding runs once (`VisualizerPlugins.swift:186`).

**That premise was written about a user who owns the copy. Nearly nobody does.** Almost every copy in
the folder is exactly what the app put there, and the listener never chose to freeze it. In practice:

- A fix to a shipped visualizer reaches new installs only. It has already happened: `familiar-apple`
  has two committed revisions of each built document (`74cf95e`, `77b252b`), and the maintainer's own
  Mac was still running the older `lyrics/app.js`.
- A visualizer removed from the bundle stays in existing users' menus indefinitely, so ADR-0161 cannot
  take effect without this.
- A new visualizer never arrives at all.
- The updated host page has to keep working with old documents forever.

Every manifest still says `1.0.0`, and no hash was recorded at seeding, so there is nothing on an
existing install to compare against except the files themselves.

## Decision

1. **A shipped copy that is byte-identical to any revision the app has ever shipped follows the app.**
   If it is outdated it is replaced. If it has been retired it is deleted.

2. **A copy that matches no shipped revision is the user's, and is never touched.** It keeps loading
   as an ordinary plugin. This is the part of point 5 that was right.

3. **A missing folder stays missing.** ADR-0089 point 3 holds: deleting a visualizer means the user
   meant to.

4. **Identity is a digest:** SHA-256 over sorted relative paths and file hashes, skipping hidden files.
   Finder creates `.DS_Store` when a folder is merely opened, and a digest that counted it would
   reclassify clean copies as edited. The known digests are a table generated from git history, with a
   test that the current bundle is in it.

5. **Reconciling runs once per bundle revision,** straight after seeding and before the first scan, and
   its marker is set only on success, so a failure retries on the next launch.

6. **Restore stays,** for putting an edited copy back on purpose.

## Alternatives Considered

**Load first-party visualizers from the app bundle again.** Updates would be automatic, with no table.
Rejected: ADR-0089 removed that runtime source because it broke the Xcode build and stranded drop-ins
under the sandbox, and "built-in" as a category the loader knows about is what point 1 of that ADR ended.

**Compare manifest versions.** The conventional approach. Rejected because every manifest already reads
`1.0.0`, and a version says nothing about whether the user edited the files. An edited copy with an old
version would be overwritten, which is the data loss ADR-0089 point 3's reasoning refuses.

**Record a hash at seeding time and compare to that.** Simpler for future installs. Rejected as the only
mechanism, because it cannot classify the copies already out there. The table is needed regardless, and
once it exists a second record adds nothing.

**Tell the listener and let them press Restore.** No code on disk to get wrong. Rejected: it hands an
ordinary fix to a person who has no reason to care, and Restore overwrites by id, so it can't delete a
retired visualizer anyway.

## Consequences

- **Positive:** a visualizer fix ships like any other fix, and ADR-0161's removal actually happens.
- **Tradeoff:** the app now deletes and overwrites in the user's folder, without being asked. The
  digest is what makes that safe, so it is the code to test hardest.
- **Tradeoff:** a copy from an uncommitted local build hashes as edited and stays. That is the safe way
  to be wrong, and only affects development machines.
- **Follow-up:** the generated table has to be regenerated whenever the bundle changes, and the test in
  point 4 is what enforces that.
