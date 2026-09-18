import { defineConfig } from '@hey-api/openapi-ts';

/**
 * The web client is generated from the committed OpenAPI contract (ADR-0129).
 *
 * Input is `backend/openapi.json`, the same file `familiar-apple` generates its Swift client from
 * (ADR-0007). Output under `src/generated/` is committed and never edited by hand; CI regenerates
 * it and fails on a diff, so a contract change, its lock and its generated clients are one
 * reviewable change (point 2).
 *
 * The axios client is chosen because the shared transport (`packages/frontend/src/api/base.ts`)
 * is an axios instance whose interceptors install the origin, the server token and the profile
 * header once (point 7). The generated client is pointed at that same instance at boot, so no
 * generated operation learns authentication on its own.
 *
 * **Special transports stay hand-written (point 8).** These are not reachable through this
 * client and are listed here so the exceptions are in one place rather than discovered at call
 * sites:
 *   - `GET /tracks/{id}/stream` (range requests; an `<audio>` element's `src`)
 *   - `GET /videos/{id}/stream` (range requests; a `<video>` element's `src`)
 *   - artwork URLs (`<img src>`; a media element cannot send a header)
 *   - SSE endpoints (`EventSource`)
 *   - file downloads (mixtape export, backup archives: a navigation, not a fetch)
 * Their DTOs may still come from `types.gen.ts`.
 */
export default defineConfig({
  input: '../../backend/openapi.json',
  output: {
    path: 'src/generated',
    // A stable, reviewable output: no formatter or linter run over it, so a diff is the contract's diff.
    postProcess: [],
  },
  plugins: [
    '@hey-api/typescript',
    '@hey-api/sdk',
    {
      name: '@hey-api/client-axios',
      // The instance is supplied at runtime by the shared transport; nothing is configured here.
      runtimeConfigPath: undefined,
    },
    {
      name: '@tanstack/react-query',
      // Feature modules build their queries from these (point 5); components never import them.
    },
  ],
});
