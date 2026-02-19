/**
 * Ego-Centric Music Map Browser.
 *
 * Displays artists in a radial layout centered on a user-selected artist.
 * Similar artists appear closer to the center, dissimilar artists further out.
 *
 * - Click an artist to recenter the map on them
 * - Double-click to navigate to artist detail view
 * - Pan and zoom to explore
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Map as MapIcon, Loader2, ZoomIn, ZoomOut, Maximize2, Search, Sparkles, X, Music } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { libraryApi, tracksApi, type EgoMapArtist } from '../../../../api/client';
import { registerBrowser, type BrowserProps } from '../../types';
import { ArtistPicker } from './ArtistPicker';

// Register this browser
registerBrowser(
  {
    id: 'ego-music-map',
    name: 'Music Map',
    description: 'Explore artists by similarity',
    icon: 'Map',
    category: 'spatial',
    requiresFeatures: false,
    requiresEmbeddings: true,
  },
  EgoMusicMap
);

interface HoveredArtist {
  artist: EgoMapArtist;
  screenX: number;
  screenY: number;
}

// Animation state for smooth transitions
interface AnimationState {
  startTime: number;
  duration: number;
  fromPositions: Map<string, { x: number; y: number }>;
  toPositions: Map<string, { x: number; y: number }>;
}

export function EgoMusicMap({ onGoToArtist }: BrowserProps) {
  const [searchParams, setSearchParams] = useSearchParams();

  // Read initial center from URL params
  const urlCenter = searchParams.get('center');
  const [centerArtist, setCenterArtist] = useState<string | null>(urlCenter);
  const [showPicker, setShowPicker] = useState(!urlCenter);
  const [hoveredArtist, setHoveredArtist] = useState<HoveredArtist | null>(null);
  const [hoveredImageError, setHoveredImageError] = useState(false);

  // Sync center artist to URL
  useEffect(() => {
    if (centerArtist) {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set('center', centerArtist);
        return next;
      }, { replace: true });
    }
  }, [centerArtist, setSearchParams]);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  // Pan and zoom state
  const [zoom, setZoom] = useState(15);  // Start zoomed in (max zoom is 15)
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const lastClickTime = useRef(0);

  // Lasso selection state
  const [isLassoing, setIsLassoing] = useState(false);
  const [lassoStart, setLassoStart] = useState<{ x: number; y: number } | null>(null);
  const [lassoEnd, setLassoEnd] = useState<{ x: number; y: number } | null>(null);
  const [selectedArtists, setSelectedArtists] = useState<Set<string>>(new Set());

  // Space key state for Figma-style pan (space+drag to pan, regular drag to select)
  const [isSpacePressed, setIsSpacePressed] = useState(false);

  // Animation state
  const animationRef = useRef<AnimationState | null>(null);
  const animationFrameRef = useRef<number | null>(null);

  // Previous data for animation
  const prevDataRef = useRef<Map<string, { x: number; y: number }>>(new Map());

  // Fetch ego map data
  const { data, isLoading, error } = useQuery({
    queryKey: ['ego-map', centerArtist],
    queryFn: () => libraryApi.getEgoMap({ center: centerArtist!, limit: 200 }),
    enabled: !!centerArtist,
    staleTime: 30000,
  });

  // Measure container size
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          setDimensions({ width, height });
        }
      }
    });

    resizeObserver.observe(container);
    return () => resizeObserver.disconnect();
  }, []);

  // Start animation when data changes
  useEffect(() => {
    if (!data) return;

    // Build new positions map
    const newPositions = new Map<string, { x: number; y: number }>();
    newPositions.set(data.center.name, { x: 0, y: 0 });
    for (const artist of data.artists) {
      newPositions.set(artist.name, { x: artist.x, y: artist.y });
    }

    // If we have previous positions, animate
    if (prevDataRef.current.size > 0) {
      animationRef.current = {
        startTime: performance.now(),
        duration: 500,
        fromPositions: prevDataRef.current,
        toPositions: newPositions,
      };
    }

    prevDataRef.current = newPositions;
  }, [data]);

  // Track space key for Figma-style pan mode
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code === 'Space' && !e.repeat) {
        e.preventDefault(); // Prevent page scroll
        setIsSpacePressed(true);
      }
    };
    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.code === 'Space') {
        setIsSpacePressed(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
    };
  }, []);

  // Convert data coordinates to screen coordinates
  const dataToScreen = useCallback(
    (x: number, y: number) => {
      const centerX = dimensions.width / 2;
      const centerY = dimensions.height / 2;
      const scale = Math.min(dimensions.width, dimensions.height) * 0.4 * zoom;

      return {
        x: centerX + pan.x + x * scale,
        y: centerY + pan.y - y * scale, // Flip Y
      };
    },
    [dimensions, zoom, pan]
  );

  // Get interpolated positions for animation
  const getAnimatedPositions = useCallback(() => {
    if (!data) return null;

    const positions = new Map<string, { x: number; y: number }>();
    const anim = animationRef.current;

    if (anim) {
      const elapsed = performance.now() - anim.startTime;
      const t = Math.min(elapsed / anim.duration, 1);
      const eased = 1 - Math.pow(1 - t, 3); // Ease out cubic

      // Interpolate all positions
      for (const [name, toPos] of anim.toPositions) {
        const fromPos = anim.fromPositions.get(name) || toPos;
        positions.set(name, {
          x: fromPos.x + (toPos.x - fromPos.x) * eased,
          y: fromPos.y + (toPos.y - fromPos.y) * eased,
        });
      }

      // Clear animation when done
      if (t >= 1) {
        animationRef.current = null;
      }
    } else {
      // No animation, use data positions directly
      positions.set(data.center.name, { x: 0, y: 0 });
      for (const artist of data.artists) {
        positions.set(artist.name, { x: artist.x, y: artist.y });
      }
    }

    return positions;
  }, [data]);

  // Render canvas
  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = dimensions.width * dpr;
    canvas.height = dimensions.height * dpr;
    ctx.scale(dpr, dpr);

    // Clear canvas
    ctx.fillStyle = '#18181b';
    ctx.fillRect(0, 0, dimensions.width, dimensions.height);

    const positions = getAnimatedPositions();
    if (!positions) return;

    // Draw distance rings
    ctx.strokeStyle = '#27272a';
    ctx.lineWidth = 1;
    const centerScreen = dataToScreen(0, 0);
    const scale = Math.min(dimensions.width, dimensions.height) * 0.4 * zoom;
    for (const ring of [0.25, 0.5, 0.75, 1.0]) {
      ctx.beginPath();
      ctx.arc(centerScreen.x, centerScreen.y, ring * scale, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Find max track count for sizing
    const maxTrackCount = Math.max(
      data.center.track_count,
      ...data.artists.map((a) => a.track_count)
    );

    // Draw artists (smaller circles)
    for (const artist of data.artists) {
      const pos = positions.get(artist.name);
      if (!pos) continue;

      const screen = dataToScreen(pos.x, pos.y);
      const radius = 4 + Math.sqrt(artist.track_count / maxTrackCount) * 12;
      const isSelected = selectedArtists.has(artist.name);
      const isHovered = hoveredArtist?.artist.name === artist.name;

      // Selection ring
      if (isSelected) {
        ctx.beginPath();
        ctx.arc(screen.x, screen.y, radius + 4, 0, Math.PI * 2);
        ctx.strokeStyle = '#22c55e';
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Artist circle
      ctx.beginPath();
      ctx.arc(screen.x, screen.y, radius, 0, Math.PI * 2);
      ctx.fillStyle = isSelected ? '#22c55e' : isHovered ? '#a855f7' : '#6b21a8';
      ctx.fill();

      // Artist label (only when zoomed in, hovered, or selected)
      if (zoom > 0.8 || isHovered || isSelected) {
        const labelSize = Math.max(10, 12 / zoom);
        ctx.font = `${labelSize}px system-ui, sans-serif`;
        ctx.fillStyle = isSelected ? '#22c55e' : '#a1a1aa';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText(artist.name, screen.x, screen.y + radius + 4);
      }
    }

    // Draw center artist (larger, different color)
    const centerPos = positions.get(data.center.name);
    if (centerPos) {
      const screen = dataToScreen(centerPos.x, centerPos.y);
      const radius = 8 + Math.sqrt(data.center.track_count / maxTrackCount) * 16;

      // Glow effect
      const gradient = ctx.createRadialGradient(
        screen.x, screen.y, radius * 0.5,
        screen.x, screen.y, radius * 2
      );
      gradient.addColorStop(0, 'rgba(168, 85, 247, 0.4)');
      gradient.addColorStop(1, 'rgba(168, 85, 247, 0)');
      ctx.fillStyle = gradient;
      ctx.fillRect(screen.x - radius * 2, screen.y - radius * 2, radius * 4, radius * 4);

      // Center circle
      ctx.beginPath();
      ctx.arc(screen.x, screen.y, radius, 0, Math.PI * 2);
      ctx.fillStyle = '#a855f7';
      ctx.fill();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Center label
      ctx.font = 'bold 14px system-ui, sans-serif';
      ctx.fillStyle = '#ffffff';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(data.center.name, screen.x, screen.y + radius + 6);
    }

    // Draw lasso rectangle
    if (isLassoing && lassoStart && lassoEnd) {
      ctx.strokeStyle = '#22c55e';
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 5]);
      ctx.strokeRect(
        Math.min(lassoStart.x, lassoEnd.x),
        Math.min(lassoStart.y, lassoEnd.y),
        Math.abs(lassoEnd.x - lassoStart.x),
        Math.abs(lassoEnd.y - lassoStart.y)
      );
      ctx.setLineDash([]);

      // Fill with semi-transparent
      ctx.fillStyle = 'rgba(34, 197, 94, 0.1)';
      ctx.fillRect(
        Math.min(lassoStart.x, lassoEnd.x),
        Math.min(lassoStart.y, lassoEnd.y),
        Math.abs(lassoEnd.x - lassoStart.x),
        Math.abs(lassoEnd.y - lassoStart.y)
      );
    }

    // Request next frame if animating
    if (animationRef.current) {
      animationFrameRef.current = requestAnimationFrame(render);
    }
  }, [data, dimensions, zoom, pan, dataToScreen, getAnimatedPositions, hoveredArtist, selectedArtists, isLassoing, lassoStart, lassoEnd]);

  // Render on data/dimension changes
  useEffect(() => {
    render();
  }, [render]);

  // Trigger animation frame loop when animation starts
  useEffect(() => {
    if (animationRef.current) {
      animationFrameRef.current = requestAnimationFrame(render);
    }
    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, [data, render]);

  // Handle wheel zoom - re-attach when data loads so canvas is available
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data) return;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();

      const rect = canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      // Zoom toward mouse position
      const zoomFactor = e.deltaY > 0 ? 0.9 : 1.1;
      const newZoom = Math.max(0.1, Math.min(15, zoom * zoomFactor));

      // Adjust pan to keep mouse position stable
      const scale = newZoom / zoom;
      const centerX = dimensions.width / 2;
      const centerY = dimensions.height / 2;
      const dx = mouseX - centerX - pan.x;
      const dy = mouseY - centerY - pan.y;

      setPan({
        x: pan.x + dx - dx * scale,
        y: pan.y + dy - dy * scale,
      });
      setZoom(newZoom);
    };

    canvas.addEventListener('wheel', handleWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', handleWheel);
  }, [data, zoom, pan, dimensions]);

  // Find artist at screen position
  const findArtistAtPosition = useCallback(
    (screenX: number, screenY: number): EgoMapArtist | null => {
      if (!data) return null;

      const positions = getAnimatedPositions();
      if (!positions) return null;

      const maxTrackCount = Math.max(
        data.center.track_count,
        ...data.artists.map((a) => a.track_count)
      );

      // Check artists (in reverse order so top-drawn are checked first)
      for (let i = data.artists.length - 1; i >= 0; i--) {
        const artist = data.artists[i];
        const pos = positions.get(artist.name);
        if (!pos) continue;

        const screen = dataToScreen(pos.x, pos.y);
        const radius = 4 + Math.sqrt(artist.track_count / maxTrackCount) * 12;

        const dx = screenX - screen.x;
        const dy = screenY - screen.y;
        if (dx * dx + dy * dy <= radius * radius) {
          return artist;
        }
      }

      return null;
    },
    [data, dataToScreen, getAnimatedPositions]
  );

  // Find all artists inside a screen-space rectangle
  const findArtistsInRect = useCallback(
    (x1: number, y1: number, x2: number, y2: number): string[] => {
      if (!data) return [];

      const positions = getAnimatedPositions();
      if (!positions) return [];

      const minX = Math.min(x1, x2);
      const maxX = Math.max(x1, x2);
      const minY = Math.min(y1, y2);
      const maxY = Math.max(y1, y2);

      const result: string[] = [];

      // Check all artists
      for (const artist of data.artists) {
        const pos = positions.get(artist.name);
        if (!pos) continue;

        const screen = dataToScreen(pos.x, pos.y);
        if (screen.x >= minX && screen.x <= maxX && screen.y >= minY && screen.y <= maxY) {
          result.push(artist.name);
        }
      }

      // Also check center artist
      const centerPos = positions.get(data.center.name);
      if (centerPos) {
        const screen = dataToScreen(centerPos.x, centerPos.y);
        if (screen.x >= minX && screen.x <= maxX && screen.y >= minY && screen.y <= maxY) {
          result.push(data.center.name);
        }
      }

      return result;
    },
    [data, dataToScreen, getAnimatedPositions]
  );

  // Mouse handlers
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;

    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    // Figma-style: space+drag to pan, regular drag to lasso select
    if (isSpacePressed) {
      setIsPanning(true);
      setPanStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
    } else {
      setIsLassoing(true);
      setLassoStart({ x: mouseX, y: mouseY });
      setLassoEnd({ x: mouseX, y: mouseY });
    }
  }, [pan, isSpacePressed]);

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      const rect = canvasRef.current?.getBoundingClientRect();
      if (!rect) return;

      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      if (isLassoing) {
        // Update lasso end position
        setLassoEnd({ x: mouseX, y: mouseY });
      } else if (isPanning) {
        setPan({
          x: e.clientX - panStart.x,
          y: e.clientY - panStart.y,
        });
      } else {
        // Check for hover
        const artist = findArtistAtPosition(mouseX, mouseY);
        if (artist) {
          setHoveredImageError(false);
          setHoveredArtist({ artist, screenX: mouseX, screenY: mouseY });
        } else {
          setHoveredArtist(null);
        }
      }
    },
    [isLassoing, isPanning, panStart, findArtistAtPosition]
  );

  const handleMouseUp = useCallback(() => {
    if (isLassoing && lassoStart && lassoEnd) {
      // Find artists inside lasso rectangle
      const artistsInRect = findArtistsInRect(
        lassoStart.x, lassoStart.y,
        lassoEnd.x, lassoEnd.y
      );

      // Add to selection (merge with existing)
      if (artistsInRect.length > 0) {
        setSelectedArtists(prev => {
          const next = new Set(prev);
          for (const name of artistsInRect) {
            next.add(name);
          }
          return next;
        });
      }
    }

    setIsLassoing(false);
    setLassoStart(null);
    setLassoEnd(null);
    setIsPanning(false);
  }, [isLassoing, lassoStart, lassoEnd, findArtistsInRect]);

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      if (!data) return;

      const rect = canvasRef.current?.getBoundingClientRect();
      if (!rect) return;

      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      // Check for double-click
      const now = Date.now();
      const isDoubleClick = now - lastClickTime.current < 300;
      lastClickTime.current = now;

      const artist = findArtistAtPosition(mouseX, mouseY);

      if (artist) {
        if (isDoubleClick) {
          // Double-click: navigate to artist
          onGoToArtist(artist.name);
        } else {
          // Single click: recenter on this artist
          setCenterArtist(artist.name);
          // Reset view with default zoom
          setPan({ x: 0, y: 0 });
          setZoom(15);
        }
      }
    },
    [data, findArtistAtPosition, onGoToArtist]
  );

  // Zoom controls
  const handleZoomIn = useCallback(() => {
    setZoom((z) => Math.min(15, z * 1.3));
  }, []);

  const handleZoomOut = useCallback(() => {
    setZoom((z) => Math.max(0.1, z / 1.3));
  }, []);

  const handleReset = useCallback(() => {
    setZoom(15);  // Reset to default zoomed-in view
    setPan({ x: 0, y: 0 });
  }, []);

  const handleSelectArtist = useCallback((artistName: string) => {
    setCenterArtist(artistName);
    setShowPicker(false);
    setPan({ x: 0, y: 0 });
    setZoom(15);  // Start with default zoomed-in view
  }, []);

  const handleChangeCenterArtist = useCallback(() => {
    setShowPicker(true);
  }, []);

  // Clear selection
  const handleClearSelection = useCallback(() => {
    setSelectedArtists(new Set());
  }, []);

  // Create playlist from selected artists via LLM
  const handleCreatePlaylist = useCallback(() => {
    if (selectedArtists.size === 0) return;

    // Build a prompt for the LLM
    const artistList = Array.from(selectedArtists).join(', ');
    const message = `Create a playlist from these artists: ${artistList}`;

    // Dispatch trigger-chat event to send to chat panel
    window.dispatchEvent(new CustomEvent('trigger-chat', { detail: { message } }));

    // Clear selection after creating
    setSelectedArtists(new Set());
  }, [selectedArtists]);

  // Show picker if no center selected
  if (showPicker) {
    return (
      <div ref={containerRef} className="relative w-full h-full bg-zinc-900">
        <ArtistPicker
          onSelect={handleSelectArtist}
          onClose={() => centerArtist && setShowPicker(false)}
          initialValue=""
        />
      </div>
    );
  }

  // Loading state
  if (isLoading) {
    return (
      <div ref={containerRef} className="flex flex-col items-center justify-center h-full">
        <Loader2 className="w-8 h-8 animate-spin text-purple-400 mb-4" />
        <p className="text-zinc-300">Loading music map...</p>
        <p className="text-sm text-zinc-500 mt-1">Finding similar artists</p>
      </div>
    );
  }

  // Error state
  if (error) {
    // Extract the actual error detail from axios response if available
    const axiosError = error as { response?: { data?: { detail?: string } } };
    const errorDetail = axiosError.response?.data?.detail
      || (error instanceof Error ? error.message : 'Unknown error');

    return (
      <div ref={containerRef} className="flex flex-col items-center justify-center h-full">
        <div className="text-red-500 mb-2">Error loading music map</div>
        <p className="text-sm text-zinc-500">
          {errorDetail}
        </p>
        <button
          onClick={handleChangeCenterArtist}
          className="mt-4 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-500"
        >
          Choose another artist
        </button>
      </div>
    );
  }

  // No data state
  if (!data || data.artists.length === 0) {
    return (
      <div ref={containerRef} className="flex flex-col items-center justify-center h-full text-zinc-500">
        <MapIcon className="w-12 h-12 mb-4 opacity-50" />
        <p>No similar artists found with audio embeddings</p>
        <p className="text-sm mt-1">Run audio analysis to generate the music map</p>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="relative w-full h-full overflow-hidden">
      {/* Canvas */}
      <canvas
        ref={canvasRef}
        className={`w-full h-full ${isSpacePressed ? 'cursor-grab active:cursor-grabbing' : 'cursor-crosshair'}`}
        style={{ width: dimensions.width, height: dimensions.height }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onClick={handleClick}
      />

      {/* Hover tooltip */}
      {hoveredArtist && (
        <div
          className="absolute pointer-events-none bg-zinc-800 rounded-lg shadow-xl border border-zinc-700 p-3 z-10"
          style={{
            left: Math.min(hoveredArtist.screenX + 12, dimensions.width - 200),
            top: Math.min(hoveredArtist.screenY + 12, dimensions.height - 100),
          }}
        >
          <div className="flex items-center gap-3">
            {!hoveredImageError ? (
              <img
                src={tracksApi.getArtworkUrl(hoveredArtist.artist.first_track_id, 'thumb')}
                alt=""
                className="w-12 h-12 rounded-lg object-cover bg-zinc-700"
                onError={() => setHoveredImageError(true)}
              />
            ) : (
              <div className="w-12 h-12 rounded-lg bg-zinc-700 flex items-center justify-center">
                <Music className="w-6 h-6 text-zinc-500" />
              </div>
            )}
            <div>
              <div className="font-medium text-white">{hoveredArtist.artist.name}</div>
              <div className="text-sm text-zinc-400">
                {hoveredArtist.artist.track_count} tracks
              </div>
              <div className="text-xs text-zinc-500 mt-1">
                Click to center · Double-click to view
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Controls overlay */}
      <div className="absolute top-4 left-4 flex items-center gap-2">
        <button
          onClick={handleChangeCenterArtist}
          className="flex items-center gap-2 px-3 py-2 bg-zinc-800/90 backdrop-blur-sm text-white rounded-lg hover:bg-zinc-700 border border-zinc-700"
        >
          <Search className="w-4 h-4" />
          <span className="font-medium">{data.center.name}</span>
        </button>
      </div>

      {/* Zoom controls */}
      <div className="absolute top-4 right-4 flex flex-col gap-1">
        <button
          onClick={handleZoomIn}
          className="p-2 bg-zinc-800/90 backdrop-blur-sm text-zinc-300 rounded-lg hover:bg-zinc-700 hover:text-white border border-zinc-700"
          title="Zoom in"
        >
          <ZoomIn className="w-4 h-4" />
        </button>
        <button
          onClick={handleZoomOut}
          className="p-2 bg-zinc-800/90 backdrop-blur-sm text-zinc-300 rounded-lg hover:bg-zinc-700 hover:text-white border border-zinc-700"
          title="Zoom out"
        >
          <ZoomOut className="w-4 h-4" />
        </button>
        <button
          onClick={handleReset}
          className="p-2 bg-zinc-800/90 backdrop-blur-sm text-zinc-300 rounded-lg hover:bg-zinc-700 hover:text-white border border-zinc-700"
          title="Reset view"
        >
          <Maximize2 className="w-4 h-4" />
        </button>
        <div className="mt-1 text-center text-xs text-zinc-500 bg-zinc-800/90 backdrop-blur-sm rounded px-2 py-1 border border-zinc-700">
          {Math.round(zoom * 100)}%
        </div>
      </div>

      {/* Stats */}
      <div className="absolute bottom-4 left-4 text-xs text-zinc-500 bg-zinc-800/90 backdrop-blur-sm rounded-lg px-3 py-2 border border-zinc-700">
        <div>Showing {data.artists.length} of {data.total_artists} artists</div>
        <div className="mt-1 text-zinc-600">Drag to select · Space+drag to pan</div>
      </div>

      {/* Selection UI */}
      {selectedArtists.size > 0 && (
        <div className="absolute bottom-4 right-4 flex items-center gap-2 bg-zinc-800/95 backdrop-blur-sm rounded-lg px-4 py-3 border border-green-800 shadow-xl">
          <div className="text-sm text-white">
            <span className="font-medium text-green-400">{selectedArtists.size}</span>
            <span className="text-zinc-400"> {selectedArtists.size === 1 ? 'artist' : 'artists'} selected</span>
          </div>
          <div className="flex items-center gap-2 ml-2">
            <button
              onClick={handleCreatePlaylist}
              className="flex items-center gap-2 px-3 py-1.5 bg-green-600 text-white text-sm rounded-lg hover:bg-green-500 transition-colors"
            >
              <Sparkles className="w-4 h-4" />
              Create Playlist
            </button>
            <button
              onClick={handleClearSelection}
              className="p-1.5 text-zinc-400 hover:text-white hover:bg-zinc-700 rounded-lg transition-colors"
              title="Clear selection"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
