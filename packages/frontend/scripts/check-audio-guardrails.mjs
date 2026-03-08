import fs from 'node:fs';
import path from 'node:path';

const repoRoot = path.resolve(import.meta.dirname, '..');
const useAudioEnginePath = path.join(repoRoot, 'src', 'player', 'useAudioEngine.ts');
const playerStorePath = path.join(repoRoot, 'src', 'player', 'playerStore.ts');

const useAudioEngineSource = fs.readFileSync(useAudioEnginePath, 'utf8');
const playerStoreSource = fs.readFileSync(playerStorePath, 'utf8');

const failures = [];

const syncPendingMatch = useAudioEngineSource.match(
  /\/\/ Effect: Sync pending next\/previous track info to native[\s\S]*?\/\/ --------------------------------------------------------------------------/
);

if (!syncPendingMatch) {
  failures.push('Could not locate pending-track sync effect block in useAudioEngine.ts');
} else if (syncPendingMatch[0].includes('tracksApi.getStreamUrl(')) {
  failures.push(
    'Pending-track sync uses tracksApi.getStreamUrl directly. Use resolver-backed URLs from engine.resolveTrackUrl.'
  );
}

const addToQueueMatch = playerStoreSource.match(/addToQueue:\s*\(track[\s\S]*?\n  },\n\n  removeFromQueue:/);
if (!addToQueueMatch) {
  failures.push('Could not locate addToQueue action block in playerStore.ts');
} else {
  const block = addToQueueMatch[0];
  if (!block.includes('offlineModeActive') || !block.includes('offlineTrackIds.has(track.id)')) {
    failures.push(
      'addToQueue is missing offline invariant guard (must block non-downloaded tracks while offlineModeActive).'
    );
  }
}

if (failures.length > 0) {
  console.error('Audio guardrail checks failed:');
  failures.forEach((failure) => console.error(`- ${failure}`));
  process.exit(1);
}

console.log('Audio guardrail checks passed.');
