/**
 * `@familiar/api-client` — the web transport client, generated from `backend/openapi.json`.
 *
 * Everything under `./generated` is written by `@hey-api/openapi-ts` (see `openapi-ts.config.ts`)
 * and never by hand. Only `packages/frontend/src/api/` imports this package: feature adapters
 * there wrap the operations in application vocabulary, and screens consume those (ADR-0129
 * points 4 and 5, enforced by `.dependency-cruiser.cjs`).
 */
export * from './generated';
export { client } from './generated/client.gen';
