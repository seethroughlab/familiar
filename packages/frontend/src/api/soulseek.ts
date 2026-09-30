/**
 * Soulseek, through the generated client (ADR-0129) — the first feature on that path.
 *
 * The shape ADR-0129 point 4 asks of every adapter: the generated operation is the only place
 * the path, method and response type are declared; this module names the operation in the
 * application's vocabulary and re-exports the wire type under the name the panel uses. It does
 * not redeclare the response by hand — `SoulseekStatus` *is* the schema's `SoulseekStatusResponse`,
 * so a field added on the server appears here on the next `pnpm generate` and nowhere else.
 */

import { soulseekGetSoulseekStatus, type SoulseekStatusResponse } from '@familiar/api-client';

export type SoulseekStatus = SoulseekStatusResponse;

export const soulseekApi = {
  /**
   * Probe the configured slskd (ADR-0116). Never rejects for an unreachable or logged-out client:
   * those come back as `reachable: false` with an `error` sentence, which is what the panel shows.
   */
  status: async (): Promise<SoulseekStatus> => {
    const { data } = await soulseekGetSoulseekStatus({ throwOnError: true });
    return data;
  },
};
