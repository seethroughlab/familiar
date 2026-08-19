/**
 * The shape a captured frontend log entry has while it is buffered.
 *
 * This lived in `db/` as a Dexie table type until ADR-0071 deleted that store. It is still a
 * useful name for what `remoteLogService` holds between capture and submission, so it moved here
 * rather than being inlined.
 */
export interface RemoteLogEntry {
  level: string;
  namespace: string;
  message: string;
  createdAt: Date;
  context?: Record<string, unknown>;
}
