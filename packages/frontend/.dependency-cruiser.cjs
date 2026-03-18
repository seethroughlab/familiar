/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  forbidden: [
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
