/**
 * UMAP Explorer - 3D visualization of the entire music library.
 *
 * Uses UMAP dimensionality reduction to position all artists in 3D space
 * based on audio similarity. Similar-sounding artists appear close together.
 */
import { useState, useCallback, Suspense, useRef, useEffect } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { RotateCcw, Info, Volume2, VolumeX, Music } from 'lucide-react';
import * as THREE from 'three';
import { getApiUrl } from '../../../../api/base';
import { tracksApi } from '../../../../api/client';
import type { MapNode3D, MusicMap3DResponse } from '../../../../api/client';
import { registerBrowser } from '../../types';
import type { BrowserProps } from '../../types';
import { ArtistPoints, POSITION_SCALE } from './ArtistPoints';
import { usePreviewAudio } from '../../../../hooks/usePreviewAudio';

import { createLogger } from '../../../../utils/logger';

const log = createLogger('UMAPExplorer');

// Progress state from SSE
interface LoadProgress {
  phase: string;
  progress: number;
  message: string;
}

// Selected artist panel
interface ArtistPanelProps {
  artist: MapNode3D;
  onClose: () => void;
  onGoToArtist: (name: string) => void;
}

function ArtistPanel({ artist, onClose, onGoToArtist }: ArtistPanelProps) {
  const [imageError, setImageError] = useState(false);

  // Reset error state when artist changes
  useEffect(() => {
    setImageError(false);
  }, [artist.id]);

  return (
    <div className="absolute bottom-4 left-4 right-4 md:left-auto md:right-4 md:w-80 bg-zinc-900/95 backdrop-blur-md rounded-xl border border-zinc-700 shadow-2xl overflow-hidden z-10">
      <div className="p-4 flex gap-4">
        {!imageError ? (
          <img
            src={tracksApi.getArtworkUrl(artist.first_track_id, 'thumb')}
            alt=""
            className="w-16 h-16 rounded-lg object-cover bg-zinc-800 flex-shrink-0"
            onError={() => setImageError(true)}
          />
        ) : (
          <div className="w-16 h-16 rounded-lg bg-zinc-800 flex-shrink-0 flex items-center justify-center">
            <Music className="w-8 h-8 text-zinc-600" />
          </div>
        )}
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-white truncate">{artist.name}</h3>
          <p className="text-sm text-zinc-400">{artist.track_count} tracks</p>
          <button
            onClick={() => onGoToArtist(artist.name)}
            className="mt-2 px-3 py-1 text-sm bg-purple-600 hover:bg-purple-500 text-white rounded-lg transition-colors"
          >
            View Artist
          </button>
        </div>
        <button
          onClick={onClose}
          className="self-start p-1 text-zinc-400 hover:text-white"
        >
          &times;
        </button>
      </div>
    </div>
  );
}

// Loading overlay with progress bar
function LoadingOverlay({ progress }: { progress: LoadProgress }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center bg-zinc-900/80 backdrop-blur-sm z-20">
      <div className="w-72 max-w-[80%]">
        {/* Progress bar */}
        <div className="h-2 bg-zinc-800 rounded-full overflow-hidden mb-3">
          <div
            className="h-full bg-purple-500 transition-all duration-300 ease-out"
            style={{ width: `${progress.progress * 100}%` }}
          />
        </div>

        {/* Message */}
        <p className="text-zinc-400 text-sm text-center">{progress.message}</p>

        {/* Phase indicator */}
        <p className="text-zinc-600 text-xs text-center mt-1">
          {Math.round(progress.progress * 100)}%
        </p>
      </div>
    </div>
  );
}

// Help overlay
function HelpOverlay({ onClose }: { onClose: () => void }) {
  return (
    <div
      className="absolute inset-0 flex items-center justify-center bg-black/60 backdrop-blur-sm z-30"
      onClick={onClose}
    >
      <div
        className="bg-zinc-900 rounded-xl border border-zinc-700 p-6 max-w-md m-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-white mb-4">
          3D Artist Explorer
        </h2>
        <ul className="space-y-2 text-zinc-300 text-sm">
          <li className="flex gap-2">
            <span className="text-zinc-500">Drag</span>
            <span>Rotate the view</span>
          </li>
          <li className="flex gap-2">
            <span className="text-zinc-500">Scroll</span>
            <span>Zoom in/out</span>
          </li>
          <li className="flex gap-2">
            <span className="text-zinc-500">Right-drag</span>
            <span>Pan the view</span>
          </li>
          <li className="flex gap-2">
            <span className="text-zinc-500">Hover</span>
            <span>Show artist name + audio preview</span>
          </li>
          <li className="flex gap-2">
            <span className="text-zinc-500">Click</span>
            <span>Select artist</span>
          </li>
          <li className="flex gap-2">
            <span className="text-zinc-500">Double-click</span>
            <span>Go to artist page</span>
          </li>
        </ul>
        <p className="mt-4 text-xs text-zinc-500">
          Artists are positioned based on how similar they sound.
          Nearby artists share sonic characteristics.
        </p>
        <button
          onClick={onClose}
          className="mt-4 w-full py-2 bg-zinc-800 hover:bg-zinc-700 text-white rounded-lg transition-colors"
        >
          Got it
        </button>
      </div>
    </div>
  );
}

// Camera controller for smooth focus on selected artist
interface CameraControllerProps {
  targetArtist: MapNode3D | null;
  controlsRef: React.RefObject<React.ComponentRef<typeof OrbitControls> | null>;
}

// How close to zoom in when selecting an artist (in world units)
const FOCUS_DISTANCE = 1;

function CameraController({ targetArtist, controlsRef }: CameraControllerProps) {
  const targetPosition = useRef(new THREE.Vector3());
  const targetCameraPos = useRef(new THREE.Vector3());
  const isAnimating = useRef(false);

  useEffect(() => {
    if (targetArtist && controlsRef.current) {
      const controls = controlsRef.current;
      const camera = controls.object;

      // Set the target position (what we're looking at)
      targetPosition.current.set(
        targetArtist.x * POSITION_SCALE,
        targetArtist.y * POSITION_SCALE,
        targetArtist.z * POSITION_SCALE
      );

      // Calculate camera position: maintain current viewing direction but zoom in
      const currentDirection = new THREE.Vector3();
      currentDirection.subVectors(camera.position, controls.target).normalize();

      // New camera position: target + direction * distance
      targetCameraPos.current.copy(targetPosition.current);
      targetCameraPos.current.addScaledVector(currentDirection, FOCUS_DISTANCE);

      isAnimating.current = true;
    }
  }, [targetArtist, controlsRef]);

  useFrame(() => {
    if (!isAnimating.current || !controlsRef.current) return;

    const controls = controlsRef.current;
    const camera = controls.object;
    const currentTarget = controls.target as THREE.Vector3;

    // Lerp both target and camera position
    currentTarget.lerp(targetPosition.current, 0.08);
    camera.position.lerp(targetCameraPos.current, 0.08);

    // Stop animating when close enough
    const targetDist = currentTarget.distanceTo(targetPosition.current);
    const cameraDist = camera.position.distanceTo(targetCameraPos.current);

    if (targetDist < 0.01 && cameraDist < 0.01) {
      currentTarget.copy(targetPosition.current);
      camera.position.copy(targetCameraPos.current);
      isAnimating.current = false;
    }

    controls.update();
  });

  return null;
}

// Custom hook for SSE-based 3D map loading
function use3DMapStream() {
  const [data, setData] = useState<MusicMap3DResponse | null>(null);
  const [progress, setProgress] = useState<LoadProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const receivedDataRef = useRef(false);

  useEffect(() => {
    // Check if we already have cached data in sessionStorage
    const cached = sessionStorage.getItem('music-map-3d');
    if (cached) {
      try {
        setData(JSON.parse(cached));
        setIsLoading(false);
        return;
      } catch {
        sessionStorage.removeItem('music-map-3d');
      }
    }

    // Start SSE connection
    const eventSource = new EventSource(getApiUrl('/library/map/3d/stream?entity_type=artists'));

    eventSource.addEventListener('progress', (event) => {
      try {
        const progressData = JSON.parse(event.data);
        setProgress(progressData);
      } catch (e) {
        log.error('Failed to parse progress:', e);
      }
    });

    eventSource.addEventListener('complete', (event) => {
      try {
        const mapData = JSON.parse(event.data);
        receivedDataRef.current = true;
        setData(mapData);
        setIsLoading(false);
        // Cache in sessionStorage (survives page navigation but not tab close)
        sessionStorage.setItem('music-map-3d', JSON.stringify(mapData));
        eventSource.close();
      } catch (e) {
        log.error('Failed to parse map data:', e);
        setError('Failed to parse map data');
        setIsLoading(false);
        eventSource.close();
      }
    });

    eventSource.addEventListener('error', (event) => {
      // Check if this is a custom error event with data or a connection error
      if (event instanceof MessageEvent && event.data) {
        // Server sent an error event with data
        try {
          const errorData = JSON.parse(event.data);
          setError(errorData.error || 'Failed to load 3D map');
        } catch {
          setError('Failed to load 3D map');
        }
        setIsLoading(false);
        eventSource.close();
      } else if (eventSource.readyState === EventSource.CLOSED) {
        // Connection was closed - only an error if we didn't receive data
        if (!receivedDataRef.current) {
          setError('Connection lost. Please refresh to try again.');
          setIsLoading(false);
        }
        eventSource.close();
      } else if (eventSource.readyState === EventSource.CONNECTING) {
        // Still trying to connect - EventSource will auto-retry
        // Don't set error yet, let it retry
        log.warn('3D map SSE connection interrupted, retrying...');
      } else {
        // Unknown error state
        if (!receivedDataRef.current) {
          setError('Connection error. Please refresh to try again.');
          setIsLoading(false);
        }
        eventSource.close();
      }
    });

    return () => {
      eventSource.close();
    };
  }, []);

  return { data, progress, error, isLoading };
}

// Main component
function UMAPExplorerInner({ onGoToArtist }: BrowserProps) {
  const [selectedArtist, setSelectedArtist] = useState<MapNode3D | null>(null);
  const [hoveredArtist, setHoveredArtist] = useState<MapNode3D | null>(null);
  const [showHelp, setShowHelp] = useState(false);
  const [previewEnabled, setPreviewEnabled] = useState(true);
  const controlsRef = useRef<React.ComponentRef<typeof OrbitControls>>(null);
  const lastClickTimeRef = useRef(0);

  // Fetch 3D map data via SSE
  const { data, progress, error, isLoading } = use3DMapStream();

  // Audio preview on hover
  const { startPreview, stopPreview } = usePreviewAudio();

  useEffect(() => {
    if (!previewEnabled) return;

    if (hoveredArtist) {
      // Use representative track (closest to centroid) if available, otherwise fall back to first track
      const previewTrackId = hoveredArtist.representative_track_id || hoveredArtist.first_track_id;
      startPreview(previewTrackId);
    } else {
      stopPreview();
    }
  }, [hoveredArtist, previewEnabled, startPreview, stopPreview]);

  // Handle artist click (with double-click detection)
  const handleArtistClick = useCallback(
    (artist: MapNode3D) => {
      const now = Date.now();
      const timeSinceLastClick = now - lastClickTimeRef.current;
      lastClickTimeRef.current = now;

      if (timeSinceLastClick < 300 && selectedArtist?.id === artist.id) {
        // Double-click - navigate to artist
        onGoToArtist(artist.name);
      } else {
        // Single click - select
        setSelectedArtist(artist);
      }
    },
    [selectedArtist, onGoToArtist]
  );

  // Handle click in empty space
  const handleEmptyClick = useCallback(() => {
    setSelectedArtist(null);
    stopPreview();
  }, [stopPreview]);

  // Reset camera
  const handleResetCamera = useCallback(() => {
    if (controlsRef.current) {
      controlsRef.current.reset();
    }
  }, []);

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center text-zinc-500">
        <div className="text-center">
          <p className="mb-2">Failed to load 3D map</p>
          <p className="text-sm text-zinc-600">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative w-full h-full bg-zinc-950 overflow-hidden">
      {/* 3D Canvas */}
      <Canvas
        camera={{ position: [0, 0, 15], fov: 60 }}
        dpr={[1, 2]}
        gl={{ antialias: true }}
      >
        <color attach="background" args={['#09090b']} />

        <Suspense fallback={null}>
          {data && (
            <ArtistPoints
              nodes={data.nodes}
              selectedId={selectedArtist?.id}
              hoveredArtist={hoveredArtist}
              onHover={setHoveredArtist}
              onClick={handleArtistClick}
              onClickEmpty={handleEmptyClick}
            />
          )}
        </Suspense>

        <OrbitControls
          ref={controlsRef}
          enableDamping
          dampingFactor={0.05}
          minDistance={0.5}
          maxDistance={50}
        />

        <CameraController
          targetArtist={selectedArtist}
          controlsRef={controlsRef}
        />
      </Canvas>

      {/* Loading overlay with progress */}
      {isLoading && progress && <LoadingOverlay progress={progress} />}
      {isLoading && !progress && (
        <LoadingOverlay
          progress={{ phase: 'connecting', progress: 0, message: 'Connecting...' }}
        />
      )}

      {/* Stats bar */}
      {data && (
        <div className="absolute top-4 left-4 px-3 py-2 bg-zinc-900/80 backdrop-blur-sm rounded-lg text-sm text-zinc-400 border border-zinc-800">
          {data.total_entities.toLocaleString()} artists
        </div>
      )}

      {/* Controls */}
      <div className="absolute top-4 right-4 flex gap-2">
        <button
          onClick={() => setPreviewEnabled(!previewEnabled)}
          className={`p-2 backdrop-blur-sm rounded-lg border border-zinc-800 transition-colors ${
            previewEnabled
              ? 'bg-purple-600/80 hover:bg-purple-500 text-white'
              : 'bg-zinc-900/80 hover:bg-zinc-800 text-zinc-400 hover:text-white'
          }`}
          title={previewEnabled ? 'Disable audio preview' : 'Enable audio preview'}
        >
          {previewEnabled ? <Volume2 className="w-5 h-5" /> : <VolumeX className="w-5 h-5" />}
        </button>
        <button
          onClick={handleResetCamera}
          className="p-2 bg-zinc-900/80 hover:bg-zinc-800 backdrop-blur-sm rounded-lg text-zinc-400 hover:text-white border border-zinc-800 transition-colors"
          title="Reset camera"
        >
          <RotateCcw className="w-5 h-5" />
        </button>
        <button
          onClick={() => setShowHelp(true)}
          className="p-2 bg-zinc-900/80 hover:bg-zinc-800 backdrop-blur-sm rounded-lg text-zinc-400 hover:text-white border border-zinc-800 transition-colors"
          title="Help"
        >
          <Info className="w-5 h-5" />
        </button>
      </div>

      {/* Selected artist panel */}
      {selectedArtist && (
        <ArtistPanel
          artist={selectedArtist}
          onClose={() => setSelectedArtist(null)}
          onGoToArtist={onGoToArtist}
        />
      )}

      {/* Help overlay */}
      {showHelp && <HelpOverlay onClose={() => setShowHelp(false)} />}
    </div>
  );
}

// Wrapper component that matches BrowserProps interface
function UMAPExplorer(props: BrowserProps) {
  return <UMAPExplorerInner {...props} />;
}

// Register the browser
registerBrowser(
  {
    id: 'umap-explorer',
    name: '3D Explorer',
    description: 'Explore your entire library in 3D space based on audio similarity',
    icon: 'Box',
    category: 'spatial',
    requiresFeatures: false,
    requiresEmbeddings: true,
  },
  UMAPExplorer
);

export { UMAPExplorer };
