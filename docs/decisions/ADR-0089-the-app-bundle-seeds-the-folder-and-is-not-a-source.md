# ADR-0089: The App Bundle Seeds the Folder, and Is Not a Source

Status: accepted

Date: 2026-08-20

Supersedes the two-source model in [ADR-0034](ADR-0034-visualizers-are-drop-in-bundles.md) point 4
and [ADR-0088](ADR-0088-every-visualizer-ships-as-a-document.md) point 3. Generalises
[ADR-0065](ADR-0065-the-app-seeds-the-drop-in-folder-with-worked-examples.md) points 1–3 from two
examples to every visualizer.

## Context

`ADR-0034` point 4 decided there were **two sources, and only two: shipped and local** — shipped
folders served straight out of the app bundle's resources, local ones out of a directory the user can
open. `ADR-0088` point 3 reaffirmed it while converting everything to documents, and said the
distinction *"needs nothing new"*.

It needed a great deal. Everything below was discovered building it, and all of it comes from the
same root: **two mechanisms doing one job.**

- The bundle half does not survive an ordinary Xcode build. Both app targets take their contents from
  a `PBXFileSystemSynchronizedRootGroup`, which copies a plain directory's files *flat* into
  `Resources/`, so five plugins each carrying an `index.html` collide and the build fails. Shipping
  them at all needed a wrapper extension to make the directory opaque to the sync.
- The two halves live in different places under the sandbox, and only one of them moved when the app
  was sandboxed for the App Store — so a user's drop-ins were stranded while the built-ins were not.
- The picker shows seven visualizers and the folder the Settings panel names contains two. The panel
  is not lying about the path; the model is lying about where visualizers come from.
- A shipped visualizer cannot be edited, deleted, or read as a worked example without finding it
  inside `Familiar.app`. `ADR-0063` publishes the API for outside authors and `ADR-0065` point 1 says
  a seeded example *"become[s] an ordinary local plugin the moment it lands"* — the built-ins get
  neither property, for no reason anybody chose.

**The contradicted premise is `ADR-0088` point 3's "needs nothing new".** It was written as a
restatement of an existing distinction and turned out to be the load-bearing claim in three separate
defects. Recorded here so nobody re-derives it from the fact that two sources sound harmless.

`ADR-0065` already built the mechanism this ADR wants, and stopped one step short of it. Its point 1
ships examples in the bundle and copies them into the folder; its point 2 seeds once; its point 3 adds
an explicit **Restore** that overwrites by id and leaves everything else alone. That is exactly the
right shape. It was scoped to the two examples because, at the time, the built-ins were a compiled
registry inside the web bundle and could not be folders at all. `ADR-0087` and `ADR-0088` removed
that obstacle: every visualizer is now a folder with an `index.html`. Nothing remains that makes a
built-in different in kind from a drop-in — only the plumbing that predates them being the same
thing.

## Decision

1. **There is one source: the `Visualizers` folder.** Everything the picker offers is a folder in
   that directory. The loader has no second place to look, and "built-in" stops being a category the
   running app knows about.

2. **The app bundle carries the visualizers as seed material, and copies them into the folder.** This
   is `ADR-0065` point 1 applied to all of them rather than to two examples. They become ordinary
   plugins the moment they land — editable, deletable, readable as worked examples, indistinguishable
   to the loader from anything the user put there.

3. **Seeded once, automatically, before the first scan.** `ADR-0065` point 2's marker and its
   reasoning carry over unchanged: deleting a visualizer means the user meant to delete it, and it
   does not come back on its own. The ordering is a requirement, not an implementation detail — a
   scan that runs before seeding shows an empty picker on first launch, which is the worst possible
   first impression of the feature.

4. **"Restore Visualizers" is explicit, overwrites by id, and leaves everything else alone.**
   `ADR-0065` point 3, widened to the full set and renamed: it is no longer only about examples. It
   names what it will overwrite before it does, and a visualizer in the folder that the app does not
   ship is never touched.

5. **A shipped visualizer is not a supported artefact once it is in the folder.** `ADR-0065` point 7,
   inherited. The app makes no promise to update or migrate a copy the user now owns; a new app
   version's copy arrives only through Restore. When one stops loading, the picker says why, like any
   other plugin.

6. **`Source.shipped` leaves the loader, the scheme handler and the index.** It becomes dead the
   moment point 1 holds, and dead plumbing that still routes is how `bundle.js` outlived the format
   it served. The app bundle is read by exactly one thing: the seeder.

## Alternatives Considered

**Keep both sources and fix the symptoms.** The build was already fixed with a wrapper extension, the
sandbox orphaning with an import affordance, and the Settings copy could name both directories. Each
fix works. Together they are three mechanisms maintaining a distinction that buys the user nothing —
and the next symptom is already visible: `ADR-0064`'s ranking, the picker's refusal rows and any
future editing feature all have to know which half a visualizer came from. Rejected because the
symptoms were not the problem.

**Seed only the examples, as `ADR-0065` decided, and leave the built-ins in the bundle.** This is the
status quo and it is coherent — until you ask why one visualizer is editable and another is not, and
find the answer is when it was written rather than anything about it. Rejected because the boundary
is historical, not principled.

**Ship nothing and let the folder start empty**, with the visualizers offered as a download. Honest
about there being one source, and it makes a fresh install useless until the user goes and finds
something — which is the state `ADR-0065` was written to prevent. Rejected: install-from-URL is
already deferred by `ADR-0034` point 5, and this would make it a prerequisite.

**Symlink the bundle's folders into the directory** instead of copying. One copy on disk, and the
folder tells the truth about what is loadable. Rejected because the symlinks would be read-only,
pointing inside a signed app bundle — so a user who edits a built-in gets a permission error, which
is worse than not offering to edit it. It also breaks on app update, when the target moves.

## Consequences

- **Positive.** One mechanism, one directory, one answer to "where do visualizers come from". The
  Settings panel's path becomes the whole truth. Every visualizer Familiar ships is a worked example
  an author can open, read and change in place, which is what `ADR-0063` publishes the API for.
- **Positive.** The sandbox-orphaning problem shrinks to the user's *own* drop-ins, because the
  shipped set arrives in the container on first launch by itself.
- **Tradeoff.** The visualizers exist twice on disk: once in the app bundle as seed material, once in
  the folder. This is the same trade `ADR-0088` point 2 already accepted for THREE, and for the same
  reason — it is only bytes.
- **Tradeoff.** A user who deletes a built-in has an emptier picker until they press Restore. That is
  `ADR-0065` point 2's deliberate choice, inherited with its reasoning: the alternative is a
  visualizer that cannot be removed.
- **Tradeoff.** A new app version's improved visualizer does not reach a user who already has the old
  copy until they Restore. Point 5 accepts this; the alternative is overwriting edits on every launch.
- **Follow-up.** The "Import Older Visualizers" affordance and the
  `files.user-selected.read-only` entitlement added for it are re-examined once seeding lands — the
  problem it solves is much smaller than it was.
- **Follow-up.** `ADR-0065`'s implementation copies two files per example, which was right when an
  example was a manifest plus an `index.js`. It has to copy folders before it can seed a document.
