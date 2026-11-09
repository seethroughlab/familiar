/**
 * Task failures, grouped (ADR-0174 points 4 and 5): what failed, how much, when last, and what to do
 * first; the raw messages behind a disclosure, with a copy action.
 *
 * Until ADR-0174 this page printed each failure's exception as its own line, so one driver error
 * repeated thirty times read as thirty problems and none said what to do. The server groups them
 * and redacts credentials (`app/services/failure_report.py`); this only presents.
 */
import { useState } from 'react';

import type { FailureGroup } from '../../api/system';

const TASK_LABELS: Record<string, string> = {
  extract_features: 'Feature extraction',
  new_releases: 'New releases',
};

function when(timestamp: string | null | undefined): string {
  if (!timestamp) return '';
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? timestamp : date.toLocaleString();
}

function detailText(group: FailureGroup): string {
  return (group.examples ?? [])
    .map((e) => [e.timestamp, e.track, e.error].filter(Boolean).join(' · '))
    .join('\n');
}

function GroupItem({ group }: { group: FailureGroup }) {
  const [copied, setCopied] = useState(false);
  const task = TASK_LABELS[group.task] ?? group.task;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(`${group.kind} · ${group.task}\n${detailText(group)}`);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <li className="space-y-1">
      <p className="text-sm text-white">
        {group.summary}{' '}
        <span className="text-zinc-400 tabular-nums">
          · {group.count} time{group.count === 1 ? '' : 's'}
          {group.affected > 0 ? ` · ${group.affected} affected` : ''}
        </span>
      </p>
      <p className="text-xs text-zinc-400">
        {task}
        {group.last_at ? ` · last ${when(group.last_at)}` : ''}
      </p>
      <p className="text-sm text-zinc-300">{group.next_action}</p>
      <details className="text-xs">
        <summary className="cursor-pointer text-zinc-400 hover:text-zinc-200">Details</summary>
        <div className="mt-2 space-y-2">
          <pre className="whitespace-pre-wrap break-words bg-zinc-900 rounded p-2 text-zinc-400">
            {detailText(group)}
          </pre>
          <button
            type="button"
            onClick={copy}
            className="text-blue-400 hover:text-blue-300"
            aria-label={`Copy the details of ${group.summary.toLowerCase()}`}
          >
            {copied ? 'Copied' : 'Copy details'}
          </button>
        </div>
      </details>
    </li>
  );
}

export function FailureGroups({ groups }: { groups: FailureGroup[] }) {
  if (groups.length === 0) return null;
  return (
    <section className="bg-zinc-800/50 rounded-lg p-4 space-y-3" aria-label="Recent failures">
      <h4 className="font-medium text-white">Recent failures</h4>
      <ul className="space-y-4">
        {groups.map((g) => (
          <GroupItem key={`${g.kind}-${g.task}`} group={g} />
        ))}
      </ul>
    </section>
  );
}
