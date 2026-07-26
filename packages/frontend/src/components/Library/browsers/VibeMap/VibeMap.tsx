/**
 * Vibe Map — a single "browse by vibe" view.
 *
 * Consolidates the former Mood Grid, 2D Music Map, Ego Music Map and 3D UMAP
 * Explorer into one 2D canvas:
 *
 * - Position: global CLAP-similarity layout (server UMAP of artist embeddings).
 * - Feature lens: color points by any audio feature (energy/valence/…).
 * - Hover: artwork tooltip + 30s audio preview.
 * - Single-click: focus the artist (camera centers + highlights nearest neighbors).
 * - Double-click: open the artist.
 * - Drag (lasso): select a cluster → generate a playlist via the assistant.
 * - Space+drag to pan, wheel to zoom. k-NN edges are off by default.
 */
import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Map as MapIcon, Loader2, ZoomIn, ZoomOut, Maximize2, Sparkles, X, Music,
  Volume2, VolumeX, Share2,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { libraryApi, tracksApi, type MapNode } from '../../../../api';
import { STALE_TIME } from '../../../../api/queryDefaults';
import { registerBrowser, type BrowserProps } from '../../types';
import { useUIStore } from '../../../../stores/uiStore';
import { useOfflineStatus } from '../../../../hooks/useOfflineStatus';
import { usePreviewAudio } from '../../../../hooks/usePreviewAudio';

// Lens features in display order, with friendly labels. Only those actually
// present in the data are shown in the picker.
const LENS_OPTIONS: { key: string; label: string }[] = [
  { key: 'energy', label: 'Energy' },
  { key: 'valence', label: 'Valence' },
  { key: 'danceability', label: 'Danceability' },
  { key: 'acousticness', label: 'Acousticness' },
  { key: 'instrumentalness', label: 'Instrumentalness' },
  { key: 'speechiness', label: 'Speechiness' },
  { key: 'harmonic_complexity', label: 'Harmonic complexity' },
  { key: 'swing_ratio', label: 'Swing' },
  { key: 'syncopation', label: 'Syncopation' },
  { key: 'brightness', label: 'Brightness' },
];

// Register this browser
registerBrowser(
  {
    id: 'vibe-map',
    name: 'Music Map',
    description: 'Explore artists by how they sound',
    icon: 'Map',
    category: 'spatial',
    requiresFeatures: false,
    requiresEmbeddings: true,
  },
  VibeMap
);

interface HoveredNode {
  node: MapNode;
  screenX: number;
  screenY: number;
}

const FOCUS_ZOOM = 3;

// Color for a 0-1 lens value: cool blue (low) → warm orange (high).
function lensColor(v: number): string {
  const lo = [37, 99, 235];
  const hi = [249, 115, 22];
  const c = lo.map((l, i) => Math.round(l + (hi[i] - l) * Math.max(0, Math.min(1, v))));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

export function VibeMap({ onGoToArtist }: BrowserProps) {
  const { isOffline } = useOfflineStatus();
  const [searchParams] = useSearchParams();
  const urlCenter = searchParams.get('center');

  const { startPreview, stopPreview } = usePreviewAudio();

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  // View state
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const [isSpacePressed, setIsSpacePressed] = useState(false);
  const lastClickTime = useRef(0);

  // Lasso selection
  const [isLassoing, setIsLassoing] = useState(false);
  const [lassoStart, setLassoStart] = useState<{ x: number; y: number } | null>(null);
  const [lassoEnd, setLassoEnd] = useState<{ x: number; y: number } | null>(null);
  const [selectedArtists, setSelectedArtists] = useState<Set<string>>(new Set());

  // Hover + focus + lens
  const [hovered, setHovered] = useState<HoveredNode | null>(null);
  const [hoveredImageError, setHoveredImageError] = useState(false);
  const [focusedArtist, setFocusedArtist] = useState<string | null>(urlCenter);
  const [lensFeature, setLensFeature] = useState<string | null>(null);
  const [previewEnabled, setPreviewEnabled] = useState(true);
  const [showEdges, setShowEdges] = useState(false);

  const camAnimRef = useRef<number | null>(null);
  const didInitialFocus = useRef(false);

  // Fetch global similarity map
  const { data, isLoading, error } = useQuery({
    queryKey: ['library', 'vibe-map', 'artists', 200],
    queryFn: () => libraryApi.getMusicMap({ entity_type: 'artists', limit: 200 }),
    enabled: !isOffline,
    staleTime: STALE_TIME.LONG,
  });

  // Adjacency from k-NN edges (id → neighbor ids)
  const adjacency = useMemo(() => {
    const map = new Map<string, Set<string>>();
    if (!data) return map;
    for (const e of data.edges) {
      if (!map.has(e.source)) map.set(e.source, new Set());
      if (!map.has(e.target)) map.set(e.target, new Set());
      map.get(e.source)!.add(e.target);
      map.get(e.target)!.add(e.source);
    }
    return map;
  }, [data]);

  const nodeById = useMemo(() => {
    const map = new Map<string, MapNode>();
    if (data) for (const n of data.nodes) map.set(n.id, n);
    return map;
  }, [data]);

  // Lens features that actually have values in this dataset
  const availableLenses = useMemo(() => {
    if (!data) return [];
    const present = new Set<string>();
    for (const n of data.nodes) {
      if (n.features) for (const k of Object.keys(n.features)) present.add(k);
    }
    return LENS_OPTIONS.filter((o) => present.has(o.key));
  }, [data]);

  const maxTrackCount = useMemo(() => {
    if (!data || data.nodes.length === 0) return 1;
    return Math.max(...data.nodes.map((n) => n.track_count));
  }, [data]);

  // Measure container
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) setDimensions({ width, height });
      }
    });
    ro.observe(container);
    return () => ro.disconnect();
  }, []);

  // Space-to-pan
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.code === 'Space' && !e.repeat) {
        e.preventDefault();
        setIsSpacePressed(true);
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.code === 'Space') setIsSpacePressed(false);
    };
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
    };
  }, []);

  // Data → screen ([0,1] box centered + fit, with zoom/pan; Y flipped so up = higher)
  const dataToScreen = useCallback(
    (x: number, y: number) => {
      const size = Math.min(dimensions.width, dimensions.height) * 0.9 * zoom;
      const originX = dimensions.width / 2 + pan.x - size / 2;
      const originY = dimensions.height / 2 + pan.y - size / 2;
      return { x: originX + x * size, y: originY + (1 - y) * size };
    },
    [dimensions, zoom, pan]
  );

  // Smoothly move the camera so (dataX, dataY) ends up centered at FOCUS_ZOOM.
  const animateCameraTo = useCallback(
    (dataX: number, dataY: number) => {
      const size = Math.min(dimensions.width, dimensions.height) * 0.9 * FOCUS_ZOOM;
      const toPan = { x: size * (0.5 - dataX), y: size * (dataY - 0.5) };
      const toZoom = FOCUS_ZOOM;
      const fromPan = pan;
      const fromZoom = zoom;
      const start = performance.now();
      const dur = 350;
      if (camAnimRef.current) cancelAnimationFrame(camAnimRef.current);
      const step = (now: number) => {
        const t = Math.min((now - start) / dur, 1);
        const e = 1 - Math.pow(1 - t, 3);
        setZoom(fromZoom + (toZoom - fromZoom) * e);
        setPan({ x: fromPan.x + (toPan.x - fromPan.x) * e, y: fromPan.y + (toPan.y - fromPan.y) * e });
        if (t < 1) camAnimRef.current = requestAnimationFrame(step);
      };
      camAnimRef.current = requestAnimationFrame(step);
    },
    [dimensions, pan, zoom]
  );

  // Once data is available, center on the initial ?center= artist if present.
  useEffect(() => {
    if (!data || didInitialFocus.current) return;
    didInitialFocus.current = true;
    if (urlCenter) {
      const n = nodeById.get(urlCenter);
      if (n) {
        setFocusedArtist(urlCenter);
        animateCameraTo(n.x, n.y);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  // Render
  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = dimensions.width * dpr;
    canvas.height = dimensions.height * dpr;
    ctx.scale(dpr, dpr);

    ctx.fillStyle = '#18181b';
    ctx.fillRect(0, 0, dimensions.width, dimensions.height);

    const neighborIds = focusedArtist ? adjacency.get(focusedArtist) : undefined;

    // Edges: all (faint) when toggled, or just the focused artist's neighbors.
    if (showEdges || focusedArtist) {
      for (const e of data.edges) {
        const focusEdge = focusedArtist && (e.source === focusedArtist || e.target === focusedArtist);
        if (!showEdges && !focusEdge) continue;
        const a = nodeById.get(e.source);
        const b = nodeById.get(e.target);
        if (!a || !b) continue;
        const pa = dataToScreen(a.x, a.y);
        const pb = dataToScreen(b.x, b.y);
        ctx.beginPath();
        ctx.moveTo(pa.x, pa.y);
        ctx.lineTo(pb.x, pb.y);
        ctx.strokeStyle = focusEdge ? 'rgba(34,197,94,0.5)' : 'rgba(113,113,122,0.15)';
        ctx.lineWidth = focusEdge ? 1.5 : 1;
        ctx.stroke();
      }
    }

    for (const node of data.nodes) {
      const screen = dataToScreen(node.x, node.y);
      const radius = 4 + Math.sqrt(node.track_count / maxTrackCount) * 12;
      const isSelected = selectedArtists.has(node.id);
      const isHovered = hovered?.node.id === node.id;
      const isFocused = focusedArtist === node.id;
      const isNeighbor = !!neighborIds?.has(node.id);
      const dim = !!focusedArtist && !isFocused && !isNeighbor;

      // Fill color: lens value, or default purple. Gray when lens has no value.
      let fill = '#7c3aed';
      if (lensFeature) {
        const v = node.features?.[lensFeature];
        fill = v == null ? '#3f3f46' : lensColor(v);
      }
      if (isHovered) fill = '#a855f7';

      ctx.globalAlpha = dim ? 0.2 : 1;

      if (isSelected) {
        ctx.beginPath();
        ctx.arc(screen.x, screen.y, radius + 4, 0, Math.PI * 2);
        ctx.strokeStyle = '#22c55e';
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      ctx.beginPath();
      ctx.arc(screen.x, screen.y, radius, 0, Math.PI * 2);
      ctx.fillStyle = fill;
      ctx.fill();

      if (isFocused) {
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2.5;
        ctx.stroke();
      } else if (isNeighbor) {
        ctx.strokeStyle = 'rgba(34,197,94,0.8)';
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      // Labels for prominent / interesting nodes
      if (zoom > 1.4 || isHovered || isSelected || isFocused || isNeighbor) {
        ctx.font = `${isFocused ? 'bold ' : ''}12px system-ui, sans-serif`;
        ctx.fillStyle = isFocused ? '#ffffff' : isSelected ? '#22c55e' : '#a1a1aa';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText(node.name, screen.x, screen.y + radius + 4);
      }

      ctx.globalAlpha = 1;
    }

    // Lasso rectangle
    if (isLassoing && lassoStart && lassoEnd) {
      const x = Math.min(lassoStart.x, lassoEnd.x);
      const y = Math.min(lassoStart.y, lassoEnd.y);
      const w = Math.abs(lassoEnd.x - lassoStart.x);
      const h = Math.abs(lassoEnd.y - lassoStart.y);
      ctx.strokeStyle = '#22c55e';
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 5]);
      ctx.strokeRect(x, y, w, h);
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(34, 197, 94, 0.1)';
      ctx.fillRect(x, y, w, h);
    }
  }, [
    data, dimensions, zoom, dataToScreen, hovered, selectedArtists, focusedArtist,
    adjacency, nodeById, lensFeature, showEdges, maxTrackCount, isLassoing, lassoStart, lassoEnd,
  ]);

  useEffect(() => {
    render();
  }, [render]);

  useEffect(() => () => {
    if (camAnimRef.current) cancelAnimationFrame(camAnimRef.current);
  }, []);

  // Wheel zoom toward cursor
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data) return;
    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      const zoomFactor = e.deltaY > 0 ? 0.9 : 1.1;
      const newZoom = Math.max(0.3, Math.min(8, zoom * zoomFactor));
      const scale = newZoom / zoom;
      const centerX = dimensions.width / 2;
      const centerY = dimensions.height / 2;
      const dx = mouseX - centerX - pan.x;
      const dy = mouseY - centerY - pan.y;
      setPan({ x: pan.x + dx - dx * scale, y: pan.y + dy - dy * scale });
      setZoom(newZoom);
    };
    canvas.addEventListener('wheel', handleWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', handleWheel);
  }, [data, zoom, pan, dimensions]);

  const findNodeAt = useCallback(
    (sx: number, sy: number): MapNode | null => {
      if (!data) return null;
      for (let i = data.nodes.length - 1; i >= 0; i--) {
        const node = data.nodes[i];
        const screen = dataToScreen(node.x, node.y);
        const radius = 4 + Math.sqrt(node.track_count / maxTrackCount) * 12;
        const dx = sx - screen.x;
        const dy = sy - screen.y;
        if (dx * dx + dy * dy <= radius * radius) return node;
      }
      return null;
    },
    [data, dataToScreen, maxTrackCount]
  );

  const findNodesInRect = useCallback(
    (x1: number, y1: number, x2: number, y2: number): string[] => {
      if (!data) return [];
      const minX = Math.min(x1, x2), maxX = Math.max(x1, x2);
      const minY = Math.min(y1, y2), maxY = Math.max(y1, y2);
      const result: string[] = [];
      for (const node of data.nodes) {
        const screen = dataToScreen(node.x, node.y);
        if (screen.x >= minX && screen.x <= maxX && screen.y >= minY && screen.y <= maxY) {
          result.push(node.id);
        }
      }
      return result;
    },
    [data, dataToScreen]
  );

  // Hover audio preview
  useEffect(() => {
    if (!previewEnabled) return;
    if (hovered?.node.first_track_id) {
      startPreview(hovered.node.first_track_id);
    } else {
      stopPreview();
    }
  }, [hovered, previewEnabled, startPreview, stopPreview]);

  useEffect(() => () => stopPreview(), [stopPreview]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
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
        setLassoEnd({ x: mouseX, y: mouseY });
      } else if (isPanning) {
        setPan({ x: e.clientX - panStart.x, y: e.clientY - panStart.y });
      } else {
        const node = findNodeAt(mouseX, mouseY);
        if (node) {
          setHoveredImageError(false);
          setHovered({ node, screenX: mouseX, screenY: mouseY });
        } else {
          setHovered(null);
        }
      }
    },
    [isLassoing, isPanning, panStart, findNodeAt]
  );

  const handleMouseUp = useCallback(() => {
    if (isLassoing && lassoStart && lassoEnd) {
      const inRect = findNodesInRect(lassoStart.x, lassoStart.y, lassoEnd.x, lassoEnd.y);
      if (inRect.length > 0) {
        setSelectedArtists((prev) => {
          const next = new Set(prev);
          for (const id of inRect) next.add(id);
          return next;
        });
      }
    }
    setIsLassoing(false);
    setLassoStart(null);
    setLassoEnd(null);
    setIsPanning(false);
  }, [isLassoing, lassoStart, lassoEnd, findNodesInRect]);

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      if (!data) return;
      const rect = canvasRef.current?.getBoundingClientRect();
      if (!rect) return;
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      const now = Date.now();
      const isDoubleClick = now - lastClickTime.current < 300;
      lastClickTime.current = now;
      const node = findNodeAt(mouseX, mouseY);
      if (!node) return;
      if (isDoubleClick) {
        onGoToArtist(node.name);
      } else {
        setFocusedArtist(node.id);
        animateCameraTo(node.x, node.y);
      }
    },
    [data, findNodeAt, onGoToArtist, animateCameraTo]
  );

  const handleZoomIn = useCallback(() => setZoom((z) => Math.min(8, z * 1.3)), []);
  const handleZoomOut = useCallback(() => setZoom((z) => Math.max(0.3, z / 1.3)), []);
  const handleReset = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setFocusedArtist(null);
  }, []);

  const handleClearSelection = useCallback(() => setSelectedArtists(new Set()), []);

  const handleCreatePlaylist = useCallback(() => {
    if (selectedArtists.size === 0) return;
    const artistList = Array.from(selectedArtists)
      .map((id) => nodeById.get(id)?.name ?? id)
      .join(', ');
    useUIStore.getState().triggerChat(`Create a playlist from these artists: ${artistList}`);
    setSelectedArtists(new Set());
  }, [selectedArtists, nodeById]);

  if (isOffline) {
    return (
      <div ref={containerRef} className="flex flex-col items-center justify-center h-full text-zinc-500 gap-2 px-6 text-center">
        <p className="text-zinc-300">The Music Map is not available offline.</p>
        <p className="text-sm">Reconnect to explore artist similarity.</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div ref={containerRef} className="flex flex-col items-center justify-center h-full">
        <Loader2 className="w-8 h-8 animate-spin text-purple-400 mb-4" />
        <p className="text-zinc-300">Computing the music map…</p>
        <p className="text-sm text-zinc-500 mt-1">Positioning artists by how they sound</p>
      </div>
    );
  }

  if (error) {
    const axiosError = error as { response?: { data?: { detail?: string } } };
    const detail = axiosError.response?.data?.detail || (error instanceof Error ? error.message : 'Unknown error');
    return (
      <div ref={containerRef} className="flex flex-col items-center justify-center h-full">
        <div className="text-red-500 mb-2">Error loading the music map</div>
        <p className="text-sm text-zinc-500">{detail}</p>
      </div>
    );
  }

  if (!data || data.nodes.length === 0) {
    return (
      <div ref={containerRef} className="flex flex-col items-center justify-center h-full text-zinc-500">
        <MapIcon className="w-12 h-12 mb-4 opacity-50" />
        <p>No artists with audio embeddings yet</p>
        <p className="text-sm mt-1">Run audio analysis to generate the music map</p>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="relative w-full h-full overflow-hidden">
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
      {hovered && (
        <div
          className="absolute pointer-events-none bg-zinc-800 rounded-lg shadow-xl border border-zinc-700 p-3 z-10"
          style={{
            left: Math.min(hovered.screenX + 12, dimensions.width - 220),
            top: Math.min(hovered.screenY + 12, dimensions.height - 110),
          }}
        >
          <div className="flex items-center gap-3">
            {!hoveredImageError ? (
              <img
                src={tracksApi.getArtworkUrl(hovered.node.first_track_id, 'thumb')}
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
              <div className="font-medium text-white">{hovered.node.name}</div>
              <div className="text-sm text-zinc-400">{hovered.node.track_count} tracks</div>
              {lensFeature && hovered.node.features?.[lensFeature] != null && (
                <div className="text-xs text-zinc-500 mt-0.5">
                  {LENS_OPTIONS.find((o) => o.key === lensFeature)?.label}:{' '}
                  {Math.round((hovered.node.features[lensFeature] as number) * 100)}%
                </div>
              )}
              <div className="text-xs text-zinc-500 mt-1">Click to focus · Double-click to open</div>
            </div>
          </div>
        </div>
      )}

      {/* Top-left: lens + edges + preview controls */}
      <div className="absolute top-4 left-4 flex items-center gap-2">
        <select
          value={lensFeature ?? ''}
          onChange={(e) => setLensFeature(e.target.value || null)}
          className="px-3 py-2 bg-zinc-800/90 backdrop-blur-sm text-white text-sm rounded-lg border border-zinc-700 focus:outline-none focus:ring-2 focus:ring-purple-500"
          title="Color points by an audio feature"
        >
          <option value="">Lens: none</option>
          {availableLenses.map((o) => (
            <option key={o.key} value={o.key}>{o.label}</option>
          ))}
        </select>
        <button
          onClick={() => setShowEdges((v) => !v)}
          className={`flex items-center gap-1.5 px-3 py-2 backdrop-blur-sm text-sm rounded-lg border transition-colors ${
            showEdges ? 'bg-purple-600/80 text-white border-purple-500' : 'bg-zinc-800/90 text-zinc-300 border-zinc-700 hover:bg-zinc-700'
          }`}
          title="Show similarity connections"
        >
          <Share2 className="w-4 h-4" />
          Edges
        </button>
        <button
          onClick={() => setPreviewEnabled((v) => !v)}
          className={`p-2 backdrop-blur-sm rounded-lg border transition-colors ${
            previewEnabled ? 'bg-zinc-800/90 text-purple-300 border-zinc-700' : 'bg-zinc-800/90 text-zinc-500 border-zinc-700'
          }`}
          title={previewEnabled ? 'Disable hover audio preview' : 'Enable hover audio preview'}
        >
          {previewEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
        </button>
      </div>

      {/* Lens legend */}
      {lensFeature && (
        <div className="absolute top-16 left-4 flex items-center gap-2 bg-zinc-800/90 backdrop-blur-sm rounded-lg px-3 py-1.5 border border-zinc-700 text-xs text-zinc-400">
          <span>Low</span>
          <span className="h-2 w-24 rounded-full" style={{ background: 'linear-gradient(to right, rgb(37,99,235), rgb(249,115,22))' }} />
          <span>High</span>
        </div>
      )}

      {/* Zoom controls */}
      <div className="absolute top-4 right-4 flex flex-col gap-1">
        <button onClick={handleZoomIn} className="p-2 bg-zinc-800/90 backdrop-blur-sm text-zinc-300 rounded-lg hover:bg-zinc-700 hover:text-white border border-zinc-700" title="Zoom in">
          <ZoomIn className="w-4 h-4" />
        </button>
        <button onClick={handleZoomOut} className="p-2 bg-zinc-800/90 backdrop-blur-sm text-zinc-300 rounded-lg hover:bg-zinc-700 hover:text-white border border-zinc-700" title="Zoom out">
          <ZoomOut className="w-4 h-4" />
        </button>
        <button onClick={handleReset} className="p-2 bg-zinc-800/90 backdrop-blur-sm text-zinc-300 rounded-lg hover:bg-zinc-700 hover:text-white border border-zinc-700" title="Reset view">
          <Maximize2 className="w-4 h-4" />
        </button>
        <div className="mt-1 text-center text-xs text-zinc-500 bg-zinc-800/90 backdrop-blur-sm rounded px-2 py-1 border border-zinc-700">
          {Math.round(zoom * 100)}%
        </div>
      </div>

      {/* Stats */}
      <div className="absolute bottom-4 left-4 text-xs text-zinc-500 bg-zinc-800/90 backdrop-blur-sm rounded-lg px-3 py-2 border border-zinc-700">
        <div>Showing {data.nodes.length} of {data.total_entities} artists</div>
        <div className="mt-1 text-zinc-600">Drag to select · Space+drag to pan · Click to focus</div>
      </div>

      {/* Selection → playlist */}
      {selectedArtists.size > 0 && (
        <div className="absolute bottom-4 right-4 flex items-center gap-2 bg-zinc-800/95 backdrop-blur-sm rounded-lg px-4 py-3 border border-green-800 shadow-xl">
          <div className="text-sm text-white">
            <span className="font-medium text-green-400">{selectedArtists.size}</span>
            <span className="text-zinc-400"> {selectedArtists.size === 1 ? 'artist' : 'artists'} selected</span>
          </div>
          <div className="flex items-center gap-2 ml-2">
            <button onClick={handleCreatePlaylist} className="flex items-center gap-2 px-3 py-1.5 bg-green-600 text-white text-sm rounded-lg hover:bg-green-500 transition-colors">
              <Sparkles className="w-4 h-4" />
              Create Playlist
            </button>
            <button onClick={handleClearSelection} className="p-1.5 text-zinc-400 hover:text-white hover:bg-zinc-700 rounded-lg transition-colors" title="Clear selection">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
