/**
 * AmbientScreen — full-screen mobile overlay for ambient mode.
 *
 * Shows seed picker when idle, now-playing + controls when active.
 */

import { X, Play, Pause, SkipForward, SkipBack, Square, AlertCircle } from 'lucide-react';
import { useThemeStore } from '../../stores/themeStore';
import { useAmbientSession } from '../../player/ambient/useAmbientSession';
import { AmbientSeedPicker } from './AmbientSeedPicker';
import { AmbientNowPlaying } from './AmbientNowPlaying';
import { AmbientControls } from './AmbientControls';
import { AmbientHistory } from './AmbientHistory';

interface Props {
  onClose: () => void;
}

export function AmbientScreen({ onClose }: Props) {
  const light = useThemeStore((s) => s.resolvedTheme === 'light');
  const session = useAmbientSession();

  const isActive = session.status === 'playing' || session.status === 'paused';
  const isLoading = session.status === 'loading';

  const handleClose = async () => {
    if (isActive) {
      await session.stopSession();
    }
    onClose();
  };

  return (
    <div className={`fixed inset-0 z-50 md:hidden flex flex-col ${
      light ? 'bg-white' : 'bg-black'
    }`}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 pt-safe-top pb-2">
        <h1 className={`text-lg font-semibold ${light ? 'text-zinc-900' : 'text-white'}`}>
          Ambient
        </h1>
        <button
          onClick={handleClose}
          className={`p-2 rounded-lg transition-colors ${
            light ? 'hover:bg-zinc-100 active:bg-zinc-200' : 'hover:bg-zinc-800 active:bg-zinc-700'
          }`}
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto min-h-0 pb-safe-bottom">
        {/* Error state */}
        {session.status === 'error' && (
          <div className="flex flex-col items-center gap-3 p-6 text-center">
            <AlertCircle className="w-10 h-10 text-red-400" />
            <p className={`text-sm ${light ? 'text-zinc-600' : 'text-zinc-400'}`}>
              {session.error || 'Something went wrong'}
            </p>
            <button
              onClick={() => session.startSession({ surpriseMe: true })}
              className={`px-4 py-2 rounded-lg text-sm font-medium ${
                light ? 'bg-zinc-100 text-zinc-700' : 'bg-zinc-800 text-zinc-300'
              }`}
            >
              Try Again
            </button>
          </div>
        )}

        {/* Idle / Loading — show seed picker */}
        {(session.status === 'idle' || isLoading) && (
          <AmbientSeedPicker
            onSelectTrack={(trackId) => session.startSession({ trackId })}
            onSelectArtist={(artist) => session.startSession({ artist })}
            onSurpriseMe={() => session.startSession({ surpriseMe: true })}
            isLoading={isLoading}
          />
        )}

        {/* Active — show now playing + controls */}
        {isActive && session.currentSnippet && (
          <div className="flex flex-col gap-6 pt-4">
            {/* Now Playing */}
            <AmbientNowPlaying
              snippet={session.currentSnippet}
              snippetCurrentTime={session.snippetCurrentTime}
            />

            {/* Transport controls */}
            <div className="flex items-center justify-center gap-6">
              <button
                onClick={session.skipToPrevious}
                className={`p-3 rounded-full transition-colors ${
                  light ? 'active:bg-zinc-100' : 'active:bg-zinc-800'
                }`}
              >
                <SkipBack className="w-6 h-6" />
              </button>

              <button
                onClick={session.status === 'playing' ? session.pauseSession : session.resumeSession}
                className={`p-4 rounded-full ${
                  light ? 'bg-zinc-900 text-white' : 'bg-white text-black'
                }`}
              >
                {session.status === 'playing' ? (
                  <Pause className="w-7 h-7" />
                ) : (
                  <Play className="w-7 h-7 ml-0.5" />
                )}
              </button>

              <button
                onClick={session.skipToNext}
                className={`p-3 rounded-full transition-colors ${
                  light ? 'active:bg-zinc-100' : 'active:bg-zinc-800'
                }`}
              >
                <SkipForward className="w-6 h-6" />
              </button>
            </div>

            {/* Stop button */}
            <div className="flex justify-center">
              <button
                onClick={session.stopSession}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm ${
                  light ? 'text-zinc-500 active:bg-zinc-100' : 'text-zinc-400 active:bg-zinc-800'
                }`}
              >
                <Square className="w-4 h-4" />
                <span>Stop Session</span>
              </button>
            </div>

            {/* Controls */}
            <AmbientControls
              controls={session.controls}
              onChange={session.updateControls}
            />

            {/* Pool info */}
            {session.poolCollapsed && (
              <div className={`mx-4 px-3 py-2 rounded-lg text-xs text-center ${
                light ? 'bg-amber-50 text-amber-700' : 'bg-amber-900/20 text-amber-400'
              }`}>
                Running low on matching tracks. Try a different filter or intensity.
              </div>
            )}

            {/* History */}
            <AmbientHistory history={session.history} />
          </div>
        )}
      </div>
    </div>
  );
}
