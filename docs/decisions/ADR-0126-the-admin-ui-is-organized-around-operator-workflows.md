# ADR-0126: The Admin UI Is Organized Around Operator Workflows

Status: proposed

Date: 2026-09-17

Extends [ADR-0058](ADR-0058-the-web-app-is-an-administration-tool.md),
[ADR-0080](ADR-0080-the-web-app-is-navigated-from-a-top-bar.md) and
[ADR-0081](ADR-0081-the-admin-app-has-one-component-tree.md). Those records correctly removed the player
and reduced the application to administration; this record revisits the information architecture after
the remaining administration surface grew.

## Context

The top bar has three destinations: Library, Tools and Server (`packages/frontend/src/app/routes.ts:42-44`).
Their labels are simple, but their contents are no longer predictable categories:

- Library contains collection totals, analysis backlogs, artwork coverage, listening history, sync,
  analysis configuration and a maintenance link.
- Tools contains duplicate/artwork/file inspection, profile and library transfer, and community-cache
  operations.
- Server contains health, discovery-source state, background jobs, backup, credentials, profiles,
  integrations, logs and diagnostics in one vertical page.

The grouping follows where code or data is owned: something acts on the library, or configures the server.
An operator arrives with a different question: what needs attention, how do I repair the collection, or
where do I change a setting? The current pages give every answer approximately the same visual weight.

On a narrow screen, three collection totals become three full-width cards followed by analysis and artwork
cards. The first operation, Sync Library, may be several screens below the title. On tool child routes the
top-level Tools destination is not marked active because selection is based on exact path equality
(`packages/frontend/src/app/TopBar.tsx:47`); only Library has an ancestor rule, hand-written for `/library/`.

## Decision

1. **The persistent destinations are Overview, Library and Settings.** They name operator intent rather
   than implementation ownership. Three destinations preserve ADR-0080's one-bar layout at every width.

2. **Overview answers three questions in its first viewport:** is the system healthy, is anything running,
   and what needs attention? Collection totals and listening history are secondary summaries. Active work,
   failures, stale analysis, missing artwork and pending review link directly to their owning screen.

3. **Library owns operations on the collection.** Its local groups are:
   - Build: scan, analysis and analysis configuration.
   - Review and repair: pending review, duplicates, artists and artwork.
   - Files and data: organiser and profile/library transfer.

4. **Settings owns configuration and infrastructure.** Its local groups are:
   - People and access: profiles, server token and API credentials.
   - Integrations: discovery providers, Last.fm and Soulseek.
   - Protection: local/export and S3 backup and restore.
   - System: service health, jobs, logs and diagnostics.

5. **Desktop pages have persistent local navigation.** The selected section has a route of its own and can
   be linked, reloaded and reached with browser history. Mobile uses a compact drill-in list or section
   selector over the same routes, not a second destination registry.

6. **Status is summarized once and configured elsewhere.** Overview may report that Redis is unavailable
   or backup is stale; detailed controls remain under Settings. The same full panel is not rendered in two
   destinations.

7. **Frequent actions precede descriptive metrics on narrow screens.** Compact totals may share one row;
   active jobs and the primary action remain visible without scrolling through one card per number.

8. **Ancestor matching drives navigation state.** `/library/duplicates` selects Library and
   `/settings/integrations/soulseek` selects Settings. Navigation integrity tests cover every routed section
   and child-page selection.

9. **Labels describe outcomes.** “Tools” and “Server” leave the navigation. Technical names such as CLAP,
   Redis and MCP may appear inside diagnostics or advanced settings, but not as the only explanation of an
   operator task.

## Alternatives Considered

**Keep the three destinations and add headings or accordions.** Smaller, and useful as an intermediate
step, but rejected as the target because Tools and Server remain catch-all labels with no stable rule for
the next feature.

**Add more top-level destinations.** Overview, Library, Tools, People, Integrations and System would make
every category explicit. Rejected because the administration surface is not used frequently enough to pay
for six permanent choices, and mobile navigation would need a second form.

**Return to a desktop sidebar.** It would hold more destinations and local navigation comfortably.
Rejected for the top level under ADR-0080's reasoning. A local section rail inside Library or Settings is
not the old application-wide media sidebar and is allowed by this record.

**Keep Library as the dashboard name.** Rejected because the screen now includes server health and active
jobs by design; calling that Library reproduces the ambiguity this record addresses.

## Consequences

- **Positive:** a newcomer can predict where a new administrative feature belongs from the user's goal.
- **Positive:** the landing page prioritizes exceptions and work over inventory.
- **Positive:** long Server and Tools pages become linkable, bounded sections.
- **Tradeoff:** established URLs and screenshots change. Old router paths (`/tools/*`, `/server`) redirect
  to their successors for as long as bookmarks and README links might reach them. This is a router concern;
  ADR-0079's alias rule is about API paths in `compat.py` and does not apply here.
- **Tradeoff:** Overview queries several domains and must remain a summary rather than becoming another
  implementation-heavy dashboard.
- **Tradeoff:** local navigation adds chrome inside two destinations.
- **Follow-up:** this record is not accepted on the text alone. Before acceptance, a mocked Overview is
  reviewed against two states — the NAS library, idle, and a server with active failures — at desktop and
  at 400px, and the labels and first viewport are confirmed or revised from what that shows.

