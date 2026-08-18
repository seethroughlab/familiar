/**
 * Drop-in visualizer plugins: the manifest, and the rules for refusing one (ADR-0034).
 *
 * **Everything here is pure, and that is the point of the file existing separately.** The half that
 * actually loads a plugin has to import React, three.js, `@react-three/fiber` and
 * `@react-three/drei` in order to hand them to the plugin on a global — roughly a megabyte of
 * dependency that a test of "does a manifest declaring apiVersion 2 get refused" has no business
 * pulling in. `visualizerPluginHost.ts` is that half.
 *
 * The manifest shape is adopted from the sample plugins rather than designed here (ADR-0034 point
 * 1). It is read as untrusted input: these files come from a directory the user drops things into,
 * so every field is checked before it is believed.
 */

/**
 * The plugin API version this host implements (ADR-0034 point 7).
 *
 * Bumped only when a change to `VisualizerProps`, `AudioData` or the `window.Familiar` global would
 * break a bundle built against the previous number. Adding a field to `AudioData` does not — every
 * existing plugin destructures what it wants and ignores the rest, which is how `beat` and `onset`
 * arrived without anything noticing.
 */
export const VISUALIZER_API_VERSION = 1;

/** Where a bundle came from. Two sources and only two — ADR-0034 point 4. */
export type VisualizerPluginSource = 'shipped' | 'local';

/**
 * `familiar-plugin.json`, in the shape the sample plugins already use.
 *
 * `type` is deliberately a plain string rather than a union: a manifest saying `"browser"` is a
 * *valid manifest for something this host does not load* (ADR-0034 point 9), and modelling it as
 * unrepresentable would make that refusal indistinguishable from a malformed file.
 */
export interface VisualizerPluginManifest {
  id: string;
  name: string;
  version: string;
  type: string;
  /** Path to the bundle, relative to the plugin directory. Resolved by the host, not by this page. */
  main: string;
  description?: string;
  /** A lucide icon name. Advisory — the picker falls back when it does not recognise one. */
  icon?: string;
  author?: { name?: string; url?: string };
  familiar?: { apiVersion?: number };
  /**
   * What this visualizer suits (ADR-0064). **Optional, and its absence is not a refusal** — which
   * is why adding it did not bump `VISUALIZER_API_VERSION`: a bump refuses every manifest declaring
   * the old version, so raising it for an additive field would have refused both working samples to
   * add a feature neither uses.
   */
  affinity?: VisualizerAffinity;
}

/** One bound a visualizer declares over a numeric analysis column. Either end may be open. */
export interface VisualizerFeatureRange {
  feature: string;
  minimum?: number;
  maximum?: number;
}

/** What a visualizer says it suits — matched against a track's analysis by the server. */
export interface VisualizerAffinity {
  tags: string[];
  ranges: VisualizerFeatureRange[];
}

/** One entry as the native host lists it, before anything has been checked. */
export interface DiscoveredPlugin {
  source: VisualizerPluginSource;
  /** Unvalidated: this is parsed JSON from a file the user supplied. */
  manifest?: unknown;
  /**
   * The directory's name on disk. The only name there is when the manifest could not be read, which
   * is exactly when the user needs to be told which folder to look at.
   */
  folder?: string;
  /**
   * Set by the native host when it could not offer the folder at all — unreadable file, not JSON.
   * Carried through rather than dropped, because a folder the user placed and that then produces no
   * row anywhere is the silent failure this whole surface keeps re-inventing.
   */
  problem?: string;
}

/** Why a plugin was refused. The tag is for tests and telemetry; `detail` is what a person reads. */
export type PluginRefusal =
  | 'malformed'
  | 'api-version'
  | 'not-a-visualizer'
  | 'shadowed'
  | 'reserved-id'
  | 'fetch-failed'
  | 'threw'
  | 'registered-nothing';

export type PluginVerdict =
  | {
      ok: true;
      source: VisualizerPluginSource;
      manifest: VisualizerPluginManifest;
      /**
       * Declarations dropped while parsing, for a plugin that loaded anyway (ADR-0064 point 3).
       * Not a refusal and deliberately not one: an unusable optional field is not a reason to
       * withhold a working visualizer. It rides on the *ok* verdict because that is the case it
       * describes — a refused plugin has a `detail` instead.
       */
      ignored: string[];
    }
  | {
      ok: false;
      source: VisualizerPluginSource;
      /** Best-effort — a manifest too malformed to have an id still needs a row in the picker. */
      id: string | null;
      name: string | null;
      refusal: PluginRefusal;
      detail: string;
    };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value : null;
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/**
 * Parse the optional `affinity` block (ADR-0064 point 1).
 *
 * **Structure only.** Whether `"dreamy"` is a tag this server knows, or `energy` a column it can
 * range over, is decided where the analysis lives — the server, which reports back what it ignored.
 * Checking it here as well would put the 48-descriptor vocabulary in TypeScript and in Python, and
 * ADR-0034 already names the consequence: "two copies of that rule in two languages is how the
 * picker comes to disagree with what actually loaded."
 *
 * So this drops only what cannot be sent at all, and says which, because an author whose typo
 * vanished silently has no way to find it.
 */
export function parseAffinity(raw: unknown): { affinity?: VisualizerAffinity; ignored: string[] } {
  if (raw === undefined) return { ignored: [] };
  if (!isRecord(raw)) return { ignored: ['affinity (not an object)'] };

  const ignored: string[] = [];
  const tags: string[] = [];
  const ranges: VisualizerFeatureRange[] = [];

  const rawTags = Array.isArray(raw.tags) ? raw.tags : [];
  if (raw.tags !== undefined && !Array.isArray(raw.tags)) ignored.push('affinity.tags (not an array)');
  for (const tag of rawTags) {
    const value = nonEmptyString(tag);
    if (value) tags.push(value);
    else ignored.push(`affinity.tags entry ${JSON.stringify(tag)}`);
  }

  const rawRanges = Array.isArray(raw.ranges) ? raw.ranges : [];
  if (raw.ranges !== undefined && !Array.isArray(raw.ranges)) {
    ignored.push('affinity.ranges (not an array)');
  }
  for (const entry of rawRanges) {
    if (!isRecord(entry)) {
      ignored.push(`affinity.ranges entry ${JSON.stringify(entry)}`);
      continue;
    }
    const feature = nonEmptyString(entry.feature);
    if (!feature) {
      ignored.push('affinity.ranges entry with no "feature"');
      continue;
    }
    const minimum = finiteNumber(entry.minimum);
    const maximum = finiteNumber(entry.maximum);
    if (minimum === null && maximum === null) {
      // Bounds neither of which is a number constrains nothing; sending it would only produce a
      // server-side "ignored" a step further from the author.
      ignored.push(`affinity.ranges "${feature}" (no numeric minimum or maximum)`);
      continue;
    }
    ranges.push({
      feature,
      ...(minimum === null ? {} : { minimum }),
      ...(maximum === null ? {} : { maximum }),
    });
  }

  if (tags.length === 0 && ranges.length === 0) return { ignored };
  return { affinity: { tags, ranges }, ignored };
}

/**
 * Parse and validate one manifest. Returns the reason as a string rather than throwing, because
 * every caller wants to show it rather than handle it.
 */
export function parseManifest(
  raw: unknown
): { manifest: VisualizerPluginManifest; ignored: string[] } | { error: string } {
  if (!isRecord(raw)) return { error: 'The manifest is not a JSON object.' };

  const id = nonEmptyString(raw.id);
  if (!id) return { error: 'The manifest has no "id".' };

  // **Constrained because it becomes part of a URL** the native host parses back into a directory.
  // The host resolves paths from its own discovery rather than from anything this page sends, so a
  // traversal attempt cannot reach the filesystem — but an id containing a slash would still split
  // the URL wrongly and produce a confusing failure a long way from its cause.
  if (!/^[a-z0-9][a-z0-9-]*$/.test(id)) {
    return { error: `"${id}" is not a usable id — lowercase letters, digits and hyphens only.` };
  }

  const name = nonEmptyString(raw.name);
  if (!name) return { error: `Plugin "${id}" has no "name".` };

  const main = nonEmptyString(raw.main);
  if (!main) return { error: `Plugin "${id}" has no "main".` };

  const type = nonEmptyString(raw.type);
  if (!type) return { error: `Plugin "${id}" has no "type".` };

  const version = nonEmptyString(raw.version) ?? '0.0.0';

  const familiar = isRecord(raw.familiar) ? raw.familiar : undefined;
  const apiVersion = familiar && typeof familiar.apiVersion === 'number' ? familiar.apiVersion : undefined;

  const author = isRecord(raw.author)
    ? { name: nonEmptyString(raw.author.name) ?? undefined, url: nonEmptyString(raw.author.url) ?? undefined }
    : undefined;

  // Parsed rather than copied: this function rebuilds the manifest field by field, so anything it
  // does not name is dropped. An `affinity` block that was never parsed here would reach nothing.
  const { affinity, ignored } = parseAffinity(raw.affinity);

  return {
    manifest: {
      id,
      name,
      version,
      type,
      main,
      description: nonEmptyString(raw.description) ?? undefined,
      icon: nonEmptyString(raw.icon) ?? undefined,
      author,
      familiar: apiVersion === undefined ? undefined : { apiVersion },
      affinity,
    },
    ignored,
  };
}

/**
 * Decide what to load, in one pass, before anything is fetched or executed.
 *
 * **Refusing before execution is the whole design.** ADR-0034 point 7 says an unsupported
 * `apiVersion` is refused "rather than loaded and left to fail somewhere inside a render loop" —
 * and a bundle that has already run cannot be un-run, because registration is a side effect of
 * evaluating it and `visualizerRegistry` has no removal.
 *
 * `builtInIds` is the set of compile-time visualizers. A dropped-in plugin claiming one of those ids
 * would overwrite it in the registry with no way back short of deleting the file, so it is refused
 * rather than allowed to shadow — see `reserved-id` below.
 */
export function reviewPlugins(
  discovered: DiscoveredPlugin[],
  options: { builtInIds?: Iterable<string>; hostApiVersion?: number } = {}
): PluginVerdict[] {
  const reserved = new Set(options.builtInIds ?? []);
  const hostApiVersion = options.hostApiVersion ?? VISUALIZER_API_VERSION;

  // **Local before shipped, so a local plugin wins a collision.** Overriding is what a drop-in
  // directory is *for*: a shipped bundle lives inside a code-signed app the user cannot edit, so if
  // shipped won there would be no way to replace one. The loser gets a `shadowed` row rather than
  // vanishing, because a plugin that is present and silently ignored is the shape of defect this
  // surface keeps producing.
  const ordered = [
    ...discovered.filter((d) => d.source === 'local'),
    ...discovered.filter((d) => d.source !== 'local'),
  ];

  const verdicts: PluginVerdict[] = [];
  const claimed = new Set<string>();

  for (const entry of ordered) {
    // The host already gave up on this one. Its sentence names the folder, so it is used as-is.
    if (entry.problem) {
      verdicts.push({
        ok: false,
        source: entry.source,
        id: null,
        name: entry.folder ?? null,
        refusal: 'malformed',
        detail: entry.problem,
      });
      continue;
    }

    const parsed = parseManifest(entry.manifest);
    if ('error' in parsed) {
      verdicts.push({
        ok: false,
        source: entry.source,
        id: null,
        name: entry.folder ?? null,
        refusal: 'malformed',
        detail: entry.folder ? `${entry.folder}: ${parsed.error}` : parsed.error,
      });
      continue;
    }

    const manifest = parsed.manifest;
    const identify = { source: entry.source, id: manifest.id, name: manifest.name } as const;

    if (manifest.type !== 'visualizer') {
      verdicts.push({
        ...identify,
        ok: false,
        refusal: 'not-a-visualizer',
        detail: `"${manifest.name}" is a ${manifest.type} plugin. Only visualizers can be loaded.`,
      });
      continue;
    }

    // ADR-0034 point 7. A missing `familiar.apiVersion` is refused too rather than assumed to be 1:
    // the samples all declare it, so an absent one means a file that was not written against this
    // contract, and guessing on its behalf is how it ends up failing inside a render loop instead.
    const declared = manifest.familiar?.apiVersion;
    if (declared !== hostApiVersion) {
      verdicts.push({
        ...identify,
        ok: false,
        refusal: 'api-version',
        detail:
          declared === undefined
            ? `"${manifest.name}" does not declare familiar.apiVersion. This app implements version ${hostApiVersion}.`
            : `"${manifest.name}" needs plugin API version ${declared}; this app implements ${hostApiVersion}.`,
      });
      continue;
    }

    if (reserved.has(manifest.id)) {
      verdicts.push({
        ...identify,
        ok: false,
        refusal: 'reserved-id',
        detail: `"${manifest.id}" is a built-in visualizer. Give the plugin a different id.`,
      });
      continue;
    }

    if (claimed.has(manifest.id)) {
      verdicts.push({
        ...identify,
        ok: false,
        refusal: 'shadowed',
        detail: `Another plugin with the id "${manifest.id}" was loaded instead.`,
      });
      continue;
    }

    claimed.add(manifest.id);
    verdicts.push({ ok: true, source: entry.source, manifest, ignored: parsed.ignored });
  }

  return verdicts;
}
