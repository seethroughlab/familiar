/**
 * The shared vocabulary for visualizer plugins: where one came from, what it says it suits, and why
 * one was refused.
 *
 * **Types only.** This file used to carry the loader's judgement as well — `parseManifest`,
 * `parseAffinity` and `reviewPlugins`, about 300 lines deciding which of two sources won a
 * collision, whether a drop-in was claiming a compile-time visualizer's id, and whether a manifest
 * declared a usable `apiVersion`. Two ADRs removed the ground under all of it:
 *
 * - `ADR-0087` deleted the registry, so there are no compile-time ids to reserve and nothing
 *   evaluates a manifest in this page any more. `visualizerCatalog` reads the listing instead.
 * - `ADR-0089` made the app bundle seed material rather than a second source, so a collision
 *   between `shipped` and `local` cannot happen — there is one directory.
 *
 * What was left had no callers outside its own test file, which is `ADR-0077`'s case exactly: a
 * surface with no caller is deleted, not documented. The git history is where the shadowing rules
 * live if a second source is ever proposed again.
 */

/**
 * Where a plugin came from.
 *
 * **One value, and that is the decision** (`ADR-0089` point 1). `'shipped'` stood beside it for
 * folders served straight out of the app bundle; the bundle now seeds the user's directory on first
 * launch and is read by nothing afterwards, so every plugin the page sees is local — including the
 * ones Familiar ships, which is what makes them editable.
 *
 * Kept as a named type rather than inlined because it is a path component in every plugin URL, and
 * because it is where a future second source would have to declare itself.
 */
export type VisualizerPluginSource = 'local';

/** One bound a visualizer declares over a numeric analysis column. Either end may be open. */
export interface VisualizerFeatureRange {
  feature: string;
  minimum?: number;
  maximum?: number;
}

/** What a visualizer says it suits — matched against a track's analysis by the server (ADR-0064). */
export interface VisualizerAffinity {
  tags: string[];
  ranges: VisualizerFeatureRange[];
}

/**
 * Why a plugin was refused. The tag is for tests and telemetry; `detail` is what a person reads.
 *
 * Shorter than it was. `'shadowed'` and `'reserved-id'` described collisions that needed two
 * sources or a compile-time registry, and neither exists; `'threw'` and `'registered-nothing'`
 * described running a bundle inside this page, which `ADR-0087` stopped doing.
 */
export type PluginRefusal = 'malformed' | 'api-version' | 'not-a-visualizer' | 'fetch-failed';
