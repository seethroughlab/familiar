/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  forbidden: [
    {
      // ADR-0083 point 5. This replaces `scripts/check-audio-guardrails.mjs`, which asserted the
      // same property by `readFileSync`-ing `player/useAudioEngine.ts` and `player/queueStore.ts` —
      // so it would have *crashed* the moment those were deleted rather than reporting anything.
      //
      // **The rule exists because the violation was invisible.** Every Discovery component, both
      // shared row components, `PlayIndicator`, `useTrackContextMenu` and `useAudioAnalyser` held a
      // selector against `playerStore`. On `/embed` and `/visualizer` that store is never mounted,
      // so each selector returned nothing, nothing rendered wrong, and the only consequence was a
      // 1,016-line queue store and IndexedDB pinned into two bundles that cannot play anything.
      // Nothing failed, so nothing said so.
      name: 'embedded-surfaces-own-no-player-state',
      comment:
        'Code reachable from /embed or /visualizer must not import a store. Those surfaces mount ' +
        'none, so a store read there is silently inert — and drags the graph behind it into the bundle.',
      severity: 'error',
      from: { path: '^src/(components/(Embed|Discovery|shared)|audio)/' },
      to: {
        path: '^src/stores/',
        // The surfaces' *own* state is allowed, and naming it is the point: a table's column
        // choice, which visualizer is showing, and why a plugin was refused are decisions the
        // embedded page makes and owns. What must never come back is player state — a queue, a
        // transport, a now-playing track — because the native app owns those (ADR-0016 point 5),
        // so a store read for them here is inert by construction.
        pathNot: '^src/stores/(columnStore|visualizerStore|visualizerPluginStore|selectionStore)',
      },
    },
    {
      name: 'no-capacitor-in-frontend',
      comment: '@familiar/frontend must not import @capacitor — use the registration pattern instead',
      severity: 'error',
      from: { path: '^src/' },
      to: { path: '@capacitor' },
    },
    {
      name: 'no-service-to-store',
      comment: 'Services should not depend on UI stores — invert the dependency via callbacks or events',
      severity: 'warn',
      from: { path: '^src/services/' },
      to: { path: '^src/stores/' },
    },
  ],
  options: {
    doNotFollow: {
      path: 'node_modules',
    },
    tsPreCompilationDeps: true,
    tsConfig: {
      fileName: '../web/tsconfig.json',
    },
    enhancedResolveOptions: {
      exportsFields: ['exports'],
      conditionNames: ['import', 'require', 'node', 'default'],
    },
    reporterOptions: {
      text: {
        highlightFocused: true,
      },
    },
  },
};
