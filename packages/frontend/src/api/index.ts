export { default as api, getApiUrl, getApiOrigin, encodePathSegment } from './base';
export * from './tracks';
export * from './library';
export * from './playlists';
export * from './integrations';
export * from './settings';
export * from './profiles';
export * from './admin';
export * from './metadata';
export * from './backup';
export * from './download';
export * from './analysis';
export * from './chat';
export * from './missingTracks';
export * from './importSession';
export * from './diagnosticsLogs';
export * from './mapStream';
// Default export: shared axios instance (for MusicBrainzLookup)
export { default } from './base';
