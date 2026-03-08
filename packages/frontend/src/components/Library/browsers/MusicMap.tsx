/**
 * MusicMap Browser - Similarity-based spatial layout of artists/albums.
 *
 * Uses UMAP dimensionality reduction on CLAP embeddings to position
 * entities so that similar-sounding music appears close together.
 *
 * - Nodes represent artists (or albums)
 * - Edges connect similar entities (k-NN based on cosine similarity)
 * - Click a node to filter library to that artist
 */
import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { Map as MapIcon, Loader2, ZoomIn, ZoomOut, Maximize2, Users, Disc, Music } from 'lucide-react';
import {
  tracksApi,
  mapStreamApi,
  parseMapErrorMessage,
  parseMapProgressEvent,
  type MapNode,
  type MusicMapResponse,
} from '../../../api';
import { registerBrowser, type BrowserProps } from '../types';
import { useOfflineStatus } from '../../../hooks/useOfflineStatus';

import { createLogger } from '../../../utils/logger';

const log = createLogger('MusicMap');

interface MapProgress {
  phase: string;
  progress: number;
  message: string;
}

// Register this browser
registerBrowser(
  {
    id: 'music-map',
    name: 'Music Map',
    description: 'Similarity-based layout of artists',
    icon: 'Map',
    category: 'spatial',
    requiresFeatures: false,
    requiresEmbeddings: true,
  },
  MusicMap
);

interface HoveredNode {
  node: MapNode;
  screenX: number;
  screenY: number;
}

type EntityType = 'artists' | 'albums';

export function MusicMap({ onGoToArtist, onGoToAlbum }: BrowserProps) {
  const { isOffline } = useOfflineStatus();
  const [hoveredNode, setHoveredNode] = useState<HoveredNode | null>(null);
  const [hoveredImageError, setHoveredImageError] = useState(false);
  const [entityType, setEntityType] = useState<EntityType>('artists');
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  // Pan and zoom state - will be set adaptively when data loads
  const [zoom, setZoom] = useState(1);
  const [hasAutoZoomed, setHasAutoZoomed] = useState(false);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const didPanRef = useRef(false); // Track if actual panning occurred (ref for sync updates)

  // Map data and loading state
  const [data, setData] = useState<MusicMapResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<MapProgress | null>(null);

  // Cache to avoid re-fetching
  const cacheRef = useRef<Map<EntityType, MusicMapResponse>>(new Map());

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

  // Fetch map data via SSE with progress updates
  useEffect(() => {
    if (isOffline) {
      setIsLoading(false);
      setError(null);
      setProgress(null);
      return;
    }

    // Check cache first
    const cached = cacheRef.current.get(entityType);
    if (cached) {
      setData(cached);
      setIsLoading(false);
      setProgress(null);
      return;
    }

    setIsLoading(true);
    setError(null);
    setProgress({ phase: 'connecting', progress: 0, message: 'Connecting...' });

    const abortController = new AbortController();

    const fetchWithSSE = async () => {
      try {
        const response = await mapStreamApi.fetch2DStream({
          entityType,
          limit: 200,
          signal: abortController.signal,
        });

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error('No response body');
        }

        const decoder = new TextDecoder();
        let buffer = '';
        let eventType = ''; // Track event type across chunks

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // Process complete events in buffer
          const lines = buffer.split('\n');
          buffer = lines.pop() || ''; // Keep incomplete line in buffer

          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              const dataStr = line.slice(6);
              try {
                const eventData = JSON.parse(dataStr);

                if (eventType === 'progress') {
                  const parsedProgress = parseMapProgressEvent(eventData);
                  if (parsedProgress) setProgress(parsedProgress);
                } else if (eventType === 'complete') {
                  const mapData = eventData as MusicMapResponse;
                  cacheRef.current.set(entityType, mapData);
                  setData(mapData);
                  setIsLoading(false);
                  setProgress(null);
                } else if (eventType === 'error') {
                  throw new Error(parseMapErrorMessage(eventData) || 'Unknown error');
                }
              } catch {
                // Ignore JSON parse errors for incomplete data
                if (eventType === 'error') {
                  throw new Error(dataStr);
                }
              }
            }
          }
        }
      } catch (err) {
        if ((err as Error).name === 'AbortError') return;
        log.error('MusicMap SSE error:', err);
        setError(err instanceof Error ? err.message : 'Failed to load map');
        setIsLoading(false);
        setProgress(null);
      }
    };

    fetchWithSSE();

    return () => abortController.abort();
  }, [entityType, isOffline]);

  // Zoom via native wheel event - zooms toward cursor position
  // Re-run when loading completes so we attach to the newly rendered SVG
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      const newZoom = Math.min(Math.max(zoom * delta, 0.5), 5);

      const rect = svg.getBoundingClientRect();
      // Mouse position relative to SVG center
      const mouseX = e.clientX - rect.left - dimensions.width / 2;
      const mouseY = e.clientY - rect.top - dimensions.height / 2;
      const zoomRatio = newZoom / zoom;

      // Adjust pan to keep the point under cursor stationary
      setPan({
        x: mouseX - (mouseX - pan.x) * zoomRatio,
        y: mouseY - (mouseY - pan.y) * zoomRatio,
      });
      setZoom(newZoom);
    };

    svg.addEventListener('wheel', handleWheel, { passive: false });
    return () => svg.removeEventListener('wheel', handleWheel);
  }, [isLoading, zoom, pan, dimensions.width, dimensions.height]);

  const handleZoomIn = useCallback(() => {
    setZoom((z) => Math.min(z * 1.3, 5));
  }, []);

  const handleZoomOut = useCallback(() => {
    setZoom((z) => Math.max(z * 0.7, 0.5));
  }, []);

  const handleReset = useCallback(() => {
    setPan({ x: 0, y: 0 });
    setHasAutoZoomed(false); // Triggers recalculation of optimal zoom
  }, []);

  // Pan handlers
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (e.button === 0) {
        setIsPanning(true);
        didPanRef.current = false; // Reset pan tracking (sync update)
        setPanStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
      }
    },
    [pan]
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (isPanning) {
        const newX = e.clientX - panStart.x;
        const newY = e.clientY - panStart.y;
        // Only count as panning if moved more than 3 pixels
        if (Math.abs(newX - pan.x) > 3 || Math.abs(newY - pan.y) > 3) {
          didPanRef.current = true;
        }
        setPan({ x: newX, y: newY });
      }
    },
    [isPanning, panStart, pan]
  );

  const handleMouseUp = useCallback(() => {
    setIsPanning(false);
  }, []);

  const handleMouseLeave = useCallback(() => {
    setIsPanning(false);
    setHoveredNode(null);
  }, []);

  // Handle node click - navigate to artist/album
  const handleNodeClick = useCallback(
    (node: MapNode) => {
      // Ignore click if we were panning
      if (didPanRef.current) return;

      if (entityType === 'artists') {
        onGoToArtist(node.name);
      } else {
        // Album format: "Artist - Album"
        const parts = node.name.split(' - ');
        if (parts.length >= 2) {
          const artist = parts[0];
          const album = parts.slice(1).join(' - '); // Handle albums with " - " in name
          onGoToAlbum(artist, album);
        }
      }
    },
    [entityType, onGoToArtist, onGoToAlbum]
  );

  // Calculate node radius based on track count
  const getNodeRadius = useCallback(
    (trackCount: number, maxCount: number) => {
      const minRadius = 6;
      const maxRadius = 20;
      const normalized = Math.sqrt(trackCount / maxCount); // sqrt for better distribution
      return minRadius + normalized * (maxRadius - minRadius);
    },
    []
  );

  // Build lookup maps for edges
  const { nodePositions, maxTrackCount } = useMemo(() => {
    if (!data?.nodes) return { nodePositions: new Map(), maxTrackCount: 1 };

    const positions = new Map<string, { x: number; y: number }>();
    let maxCount = 1;

    for (const node of data.nodes) {
      positions.set(node.id, { x: node.x, y: node.y });
      if (node.track_count > maxCount) maxCount = node.track_count;
    }

    return { nodePositions: positions, maxTrackCount: maxCount };
  }, [data]);

  // Auto-zoom to fit nodes when data first loads
  useEffect(() => {
    if (!data?.nodes?.length || hasAutoZoomed) return;

    // Calculate bounding box of all nodes (coordinates are in [0,1] range)
    let minX = 1, maxX = 0, minY = 1, maxY = 0;
    for (const node of data.nodes) {
      minX = Math.min(minX, node.x);
      maxX = Math.max(maxX, node.x);
      minY = Math.min(minY, node.y);
      maxY = Math.max(maxY, node.y);
    }

    // Calculate the span of data
    const dataWidth = maxX - minX;
    const dataHeight = maxY - minY;

    if (dataWidth > 0 && dataHeight > 0) {
      // Calculate zoom to fill ~85% of view (leave some margin)
      const targetFill = 0.85;
      const zoomX = targetFill / dataWidth;
      const zoomY = targetFill / dataHeight;
      // Use the smaller zoom to ensure everything fits
      const optimalZoom = Math.min(zoomX, zoomY, 3); // Cap at 3x

      setZoom(Math.max(optimalZoom, 1)); // At least 1x
    }

    setHasAutoZoomed(true);
  }, [data, hasAutoZoomed]);

  // Reset auto-zoom flag when entity type changes
  useEffect(() => {
    setHasAutoZoomed(false);
  }, [entityType]);

  if (isOffline) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-zinc-500 gap-2 px-6 text-center">
        <p className="text-zinc-300">Music Map is not available offline.</p>
        <p className="text-sm">Reconnect to load similarity embeddings.</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <Loader2 className="w-8 h-8 animate-spin text-purple-400 mb-4" />

        {/* Progress message */}
        <p className="text-zinc-300 mb-2">
          {progress?.message || 'Computing music map...'}
        </p>

        {/* Progress bar */}
        {progress && (
          <div className="w-64 mt-2">
            <div className="flex justify-between text-xs text-zinc-500 mb-1">
              <span className="capitalize">{progress.phase.replace('_', ' ')}</span>
              <span>{Math.round(progress.progress * 100)}%</span>
            </div>
            <div className="h-2 bg-zinc-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-purple-500 rounded-full transition-all duration-300"
                style={{ width: `${progress.progress * 100}%` }}
              />
            </div>
          </div>
        )}

        <p className="text-sm text-zinc-600 mt-3">
          {progress?.phase === 'checking_cache'
            ? 'Checking cache...'
            : progress?.phase === 'complete'
            ? 'Loading visualization...'
            : 'Large libraries may take longer'}
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <div className="text-red-500 mb-2">Error loading music map</div>
        <p className="text-sm text-zinc-500">{error}</p>
      </div>
    );
  }

  if (!data || data.nodes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
        <MapIcon className="w-12 h-12 mb-4 opacity-50" />
        <p>No {entityType} with audio embeddings</p>
        <p className="text-sm mt-1">
          Run audio analysis to generate the music map
        </p>
      </div>
    );
  }

  // Grid dimensions - use square grid centered in container
  const gridWidth = dimensions.width;
  const gridHeight = dimensions.height;
  const padding = { left: 40, right: 40, top: 40, bottom: 40 };
  const availableWidth = Math.max(gridWidth - padding.left - padding.right, 100);
  const availableHeight = Math.max(gridHeight - padding.top - padding.bottom, 100);

  // Keep it square
  const gridSide = Math.min(availableWidth, availableHeight);
  const offsetX = (availableWidth - gridSide) / 2;
  const offsetY = (availableHeight - gridSide) / 2;

  // Convert normalized [0,1] coordinates to SVG coordinates
  const dataToSvg = (x: number, y: number) => ({
    x: padding.left + offsetX + x * gridSide,
    y: padding.top + offsetY + (1 - y) * gridSide, // Flip Y so higher = up
  });

  return (
    <div className="flex flex-col h-full p-4">
      {/* Controls */}
      <div className="flex items-center justify-between mb-2 flex-shrink-0">
        <div className="flex items-center gap-4">
          {/* Entity type toggle */}
          <div className="flex items-center gap-1 bg-zinc-800 rounded-lg p-1">
            <button
              onClick={() => setEntityType('artists')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors ${
                entityType === 'artists'
                  ? 'bg-purple-600 text-white'
                  : 'text-zinc-400 hover:text-white'
              }`}
            >
              <Users className="w-4 h-4" />
              Artists
            </button>
            <button
              onClick={() => setEntityType('albums')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors ${
                entityType === 'albums'
                  ? 'bg-purple-600 text-white'
                  : 'text-zinc-400 hover:text-white'
              }`}
            >
              <Disc className="w-4 h-4" />
              Albums
            </button>
          </div>

          <span className="text-sm text-zinc-400">
            {data.total_entities} {entityType} mapped
          </span>
        </div>

        {/* Zoom controls */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-500">{Math.round(zoom * 100)}%</span>
          <button
            onClick={handleZoomOut}
            className="p-1.5 bg-zinc-800 hover:bg-zinc-700 rounded transition-colors"
            title="Zoom out"
          >
            <ZoomOut className="w-4 h-4" />
          </button>
          <button
            onClick={handleZoomIn}
            className="p-1.5 bg-zinc-800 hover:bg-zinc-700 rounded transition-colors"
            title="Zoom in"
          >
            <ZoomIn className="w-4 h-4" />
          </button>
          <button
            onClick={handleReset}
            className="p-1.5 bg-zinc-800 hover:bg-zinc-700 rounded transition-colors"
            title="Reset view"
          >
            <Maximize2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Map container */}
      <div
        ref={containerRef}
        className="relative flex-1 min-h-0 rounded-lg bg-zinc-900"
      >
        <svg
          ref={svgRef}
          width="100%"
          height="100%"
          viewBox={`0 0 ${gridWidth} ${gridHeight}`}
          preserveAspectRatio="none"
          className={isPanning ? 'cursor-grabbing' : 'cursor-grab'}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseLeave}
          style={{ display: 'block' }}
        >
          {/* Transform group for pan/zoom */}
          <g
            transform={`translate(${pan.x + gridWidth / 2}, ${pan.y + gridHeight / 2}) scale(${zoom}) translate(${-gridWidth / 2}, ${-gridHeight / 2})`}
          >
            {/* Background */}
            <rect
              x={padding.left + offsetX}
              y={padding.top + offsetY}
              width={gridSide}
              height={gridSide}
              fill="rgba(39, 39, 42, 0.5)"
              rx={8 / zoom}
            />

            {/* Edges (draw first so nodes are on top) */}
            {data.edges.map((edge, i) => {
              const sourcePos = nodePositions.get(edge.source);
              const targetPos = nodePositions.get(edge.target);
              if (!sourcePos || !targetPos) return null;

              const start = dataToSvg(sourcePos.x, sourcePos.y);
              const end = dataToSvg(targetPos.x, targetPos.y);

              return (
                <line
                  key={i}
                  x1={start.x}
                  y1={start.y}
                  x2={end.x}
                  y2={end.y}
                  stroke="rgba(168, 85, 247, 0.2)"
                  strokeWidth={(1 + edge.weight * 2) / zoom}
                />
              );
            })}

            {/* Nodes */}
            {data.nodes.map((node) => {
              const pos = dataToSvg(node.x, node.y);
              const radius = getNodeRadius(node.track_count, maxTrackCount);
              const isHovered = hoveredNode?.node.id === node.id;

              return (
                <g key={node.id}>
                  {/* Node circle */}
                  <circle
                    cx={pos.x}
                    cy={pos.y}
                    r={radius / zoom}
                    fill={isHovered ? '#a855f7' : '#7c3aed'}
                    stroke={isHovered ? '#fff' : '#a855f7'}
                    strokeWidth={(isHovered ? 2 : 1) / zoom}
                    className="cursor-pointer transition-all"
                    onMouseEnter={(e) => {
                      const rect = svgRef.current?.getBoundingClientRect();
                      if (rect) {
                        setHoveredImageError(false); // Reset image error state
                        setHoveredNode({
                          node,
                          screenX: e.clientX - rect.left,
                          screenY: e.clientY - rect.top,
                        });
                      }
                    }}
                    onMouseLeave={() => !isPanning && setHoveredNode(null)}
                    onClick={() => handleNodeClick(node)}
                  />

                  {/* Label for larger nodes or when hovered - more labels appear at higher zoom */}
                  {(isHovered || node.track_count > maxTrackCount * (0.3 / zoom)) && (
                    <text
                      x={pos.x}
                      y={pos.y + (radius + 12) / zoom}
                      textAnchor="middle"
                      className="fill-zinc-300 pointer-events-none"
                      style={{ fontSize: 10 / zoom }}
                    >
                      {node.name.length > 20
                        ? node.name.slice(0, 18) + '...'
                        : node.name}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        </svg>

        {/* Hover tooltip */}
        {hoveredNode && !isPanning && (
          <div
            className="absolute z-10 p-3 bg-zinc-800 border border-zinc-700 rounded-lg shadow-lg max-w-xs pointer-events-none"
            style={{
              left: Math.min(hoveredNode.screenX + 15, gridWidth - 200),
              top: Math.max(hoveredNode.screenY - 80, 10),
            }}
          >
            {/* Artwork thumbnail */}
            <div className="flex items-start gap-3">
              {!hoveredImageError ? (
                <img
                  src={tracksApi.getArtworkUrl(hoveredNode.node.first_track_id, 'thumb')}
                  alt=""
                  className="w-12 h-12 rounded object-cover bg-zinc-700"
                  onError={() => setHoveredImageError(true)}
                />
              ) : (
                <div className="w-12 h-12 rounded bg-zinc-700 flex items-center justify-center">
                  <Music className="w-6 h-6 text-zinc-500" />
                </div>
              )}
              <div className="flex-1 min-w-0">
                <div className="font-medium text-white truncate">
                  {hoveredNode.node.name}
                </div>
                <div className="text-sm text-zinc-400 mt-1">
                  {hoveredNode.node.track_count} track
                  {hoveredNode.node.track_count !== 1 ? 's' : ''}
                </div>
              </div>
            </div>
            <div className="text-xs text-purple-400 mt-2">
              Click to view {entityType === 'artists' ? 'artist' : 'album'}
            </div>
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="mt-2 flex-shrink-0 flex justify-center items-center gap-4 text-sm text-zinc-500">
        <span>Scroll to zoom, drag to pan</span>
        <span className="text-zinc-600">|</span>
        <span>Similar {entityType} appear close together</span>
      </div>
    </div>
  );
}
