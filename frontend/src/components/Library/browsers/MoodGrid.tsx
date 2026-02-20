/**
 * MoodGrid Browser - 2D heatmap of tracks by energy and valence.
 *
 * X-axis: Valence (sad to happy)
 * Y-axis: Energy (calm to energetic)
 *
 * Creates four quadrants:
 * - Top-right: Happy/Energetic
 * - Top-left: Angry/Intense
 * - Bottom-right: Relaxed/Peaceful
 * - Bottom-left: Sad/Melancholic
 *
 * Uses aggregated endpoint for efficient display of large libraries.
 * Click a cell to view tracks from that mood region.
 */
import { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Sparkles, Loader2, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react';
import { libraryApi, type MoodCell } from '../../../api';
import { registerBrowser, type BrowserProps } from '../types';

// Register this browser
registerBrowser(
  {
    id: 'mood-grid',
    name: 'Mood Grid',
    description: '2D map of tracks by energy and mood',
    icon: 'Sparkles',
    category: 'spatial',
    requiresFeatures: true,
    requiresEmbeddings: false,
  },
  MoodGrid
);

interface HoveredCell {
  cell: MoodCell;
  screenX: number;
  screenY: number;
}

export function MoodGrid({ onGoToMood }: BrowserProps) {
  const [hoveredCell, setHoveredCell] = useState<HoveredCell | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const gridContainerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  // Pan and zoom state
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const didPanRef = useRef(false); // Track if actual panning occurred (ref for sync updates)

  // Measure grid container size using ResizeObserver for accurate measurements
  useEffect(() => {
    const container = gridContainerRef.current;
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

  // Fetch aggregated mood distribution
  const { data, isLoading, error } = useQuery({
    queryKey: ['library-mood-distribution'],
    queryFn: () => libraryApi.getMoodDistribution(10), // 10x10 grid
  });

  // Calculate max count for color scaling
  const maxCount = useMemo(() => {
    if (!data?.cells) return 1;
    return Math.max(...data.cells.map((c) => c.track_count), 1);
  }, [data]);

  // Handle navigating to tracks in a cell
  const handleCellClick = useCallback(
    (cell: MoodCell) => {
      // Ignore click if we were panning
      if (didPanRef.current) return;
      if (cell.track_count === 0) return;
      onGoToMood(cell.energy_min, cell.energy_max, cell.valence_min, cell.valence_max);
    },
    [onGoToMood]
  );

  // Zoom via native wheel event (React uses passive listeners by default)
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      setZoom((z) => Math.min(Math.max(z * delta, 0.5), 5));
    };

    svg.addEventListener('wheel', handleWheel, { passive: false });
    return () => svg.removeEventListener('wheel', handleWheel);
  }, []);

  const handleZoomIn = useCallback(() => {
    setZoom((z) => Math.min(z * 1.3, 5));
  }, []);

  const handleZoomOut = useCallback(() => {
    setZoom((z) => Math.max(z * 0.7, 0.5));
  }, []);

  const handleReset = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
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
    setHoveredCell(null);
  }, []);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-red-500">Error loading mood data</div>
      </div>
    );
  }

  if (!data || data.total_with_mood === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
        <Sparkles className="w-12 h-12 mb-4 opacity-50" />
        <p>No tracks with mood analysis</p>
        <p className="text-sm mt-1">
          Run audio analysis to see tracks on the mood grid
        </p>
      </div>
    );
  }

  // Grid dimensions - use full container size but keep cells square
  const gridWidth = dimensions.width;
  const gridHeight = dimensions.height;
  const padding = { left: 50, right: 20, top: 20, bottom: 30 };
  const availableWidth = Math.max(gridWidth - padding.left - padding.right, 100);
  const availableHeight = Math.max(gridHeight - padding.top - padding.bottom, 100);
  const numCells = data.grid_size || 10;

  // Use the smaller dimension to keep cells square
  const gridSide = Math.min(availableWidth, availableHeight);
  const cellSize = gridSide / numCells;

  // Center the grid in the available space
  const offsetX = (availableWidth - gridSide) / 2;
  const offsetY = (availableHeight - gridSide) / 2;

  // Get cell color based on track count (purple gradient)
  const getCellColor = (count: number) => {
    if (count === 0) return 'transparent';
    const intensity = Math.pow(count / maxCount, 0.5); // sqrt for better distribution
    const alpha = 0.3 + intensity * 0.7;
    return `rgba(168, 85, 247, ${alpha})`; // purple-500
  };

  // Quadrant labels (in data space center of each quadrant)
  const quadrants = [
    { label: 'Angry', sublabel: 'Intense', valence: 0.25, energy: 0.75 },
    { label: 'Happy', sublabel: 'Energetic', valence: 0.75, energy: 0.75 },
    { label: 'Sad', sublabel: 'Melancholic', valence: 0.25, energy: 0.25 },
    { label: 'Relaxed', sublabel: 'Peaceful', valence: 0.75, energy: 0.25 },
  ];

  // Convert data coordinates (0-1) to SVG coordinates
  const dataToSvg = (valence: number, energy: number) => ({
    x: padding.left + offsetX + valence * gridSide,
    y: padding.top + offsetY + (1 - energy) * gridSide,
  });

  return (
    <div className="flex flex-col h-full p-4">
      {/* Stats and controls */}
      <div className="flex items-center justify-between mb-2 flex-shrink-0">
        <div className="flex items-center gap-4 text-sm text-zinc-400">
          <span>{data.total_with_mood.toLocaleString()} tracks with mood data</span>
          {data.total_without_mood > 0 && (
            <span className="text-zinc-500">
              ({data.total_without_mood.toLocaleString()} without analysis)
            </span>
          )}
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

      {/* Grid container - this is what we measure */}
      <div
        ref={gridContainerRef}
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
            {/* Grid background */}
            <defs>
              <linearGradient id="energyGradient" x1="0%" y1="100%" x2="0%" y2="0%">
                <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.1" />
                <stop offset="100%" stopColor="#ef4444" stopOpacity="0.1" />
              </linearGradient>
            </defs>

            {/* Transform group for pan/zoom */}
            <g
              transform={`translate(${pan.x + gridWidth / 2}, ${pan.y + gridHeight / 2}) scale(${zoom}) translate(${-gridWidth / 2}, ${-gridHeight / 2})`}
            >
              {/* Background gradient */}
              <rect
                x={padding.left + offsetX}
                y={padding.top + offsetY}
                width={gridSide}
                height={gridSide}
                fill="url(#energyGradient)"
              />

            {/* Grid lines */}
            {[0.25, 0.5, 0.75].map((v) => (
              <g key={v}>
                <line
                  x1={padding.left + offsetX + v * gridSide}
                  y1={padding.top + offsetY}
                  x2={padding.left + offsetX + v * gridSide}
                  y2={padding.top + offsetY + gridSide}
                  stroke="#333"
                  strokeDasharray={v === 0.5 ? '0' : '2,4'}
                  strokeWidth={v === 0.5 ? 1 : 0.5}
                />
                <line
                  x1={padding.left + offsetX}
                  y1={padding.top + offsetY + v * gridSide}
                  x2={padding.left + offsetX + gridSide}
                  y2={padding.top + offsetY + v * gridSide}
                  stroke="#333"
                  strokeDasharray={v === 0.5 ? '0' : '2,4'}
                  strokeWidth={v === 0.5 ? 1 : 0.5}
                />
              </g>
            ))}

            {/* Border */}
            <rect
              x={padding.left + offsetX}
              y={padding.top + offsetY}
              width={gridSide}
              height={gridSide}
              fill="none"
              stroke="#444"
              strokeWidth={2}
            />

            {/* Axis labels */}
            <text
              x={padding.left + offsetX + gridSide / 2}
              y={padding.top + offsetY + gridSide + 20}
              textAnchor="middle"
              className="fill-zinc-400"
              style={{ fontSize: 11 }}
            >
              Valence (Sad → Happy)
            </text>
            <text
              x={padding.left + offsetX - 25}
              y={padding.top + offsetY + gridSide / 2}
              textAnchor="middle"
              className="fill-zinc-400"
              style={{ fontSize: 11 }}
              transform={`rotate(-90, ${padding.left + offsetX - 25}, ${padding.top + offsetY + gridSide / 2})`}
            >
              Energy (Calm → Energetic)
            </text>

            {/* Quadrant labels */}
            {quadrants.map((q, i) => {
              const pos = dataToSvg(q.valence, q.energy);
              return (
                <g key={i}>
                  <text
                    x={pos.x}
                    y={pos.y - 8}
                    textAnchor="middle"
                    className="fill-zinc-500"
                    style={{ fontSize: 13, fontWeight: 500 }}
                  >
                    {q.label}
                  </text>
                  <text
                    x={pos.x}
                    y={pos.y + 8}
                    textAnchor="middle"
                    className="fill-zinc-600"
                    style={{ fontSize: 10 }}
                  >
                    {q.sublabel}
                  </text>
                </g>
              );
            })}

            {/* Heatmap cells */}
            {data.cells.map((cell, i) => {
              const x = padding.left + offsetX + cell.valence_min * gridSide;
              const y = padding.top + offsetY + (1 - cell.energy_max) * gridSide;
              const isHovered = hoveredCell?.cell === cell;

              return (
                <rect
                  key={i}
                  x={x}
                  y={y}
                  width={cellSize}
                  height={cellSize}
                  fill={getCellColor(cell.track_count)}
                  stroke={isHovered ? '#a855f7' : 'transparent'}
                  strokeWidth={2}
                  className="cursor-pointer transition-all"
                  onMouseEnter={(e) => {
                    const rect = svgRef.current?.getBoundingClientRect();
                    if (rect) {
                      setHoveredCell({
                        cell,
                        screenX: e.clientX - rect.left,
                        screenY: e.clientY - rect.top,
                      });
                    }
                  }}
                  onMouseLeave={() => !isPanning && setHoveredCell(null)}
                  onClick={() => handleCellClick(cell)}
                />
              );
            })}
            </g>
          </svg>

          {/* Hover tooltip */}
          {hoveredCell && !isPanning && (
            <div
              className="absolute z-10 p-3 bg-zinc-800 border border-zinc-700 rounded-lg shadow-lg max-w-xs pointer-events-none"
              style={{
                left: Math.min(hoveredCell.screenX + 15, gridWidth - 200),
                top: Math.max(hoveredCell.screenY - 80, 10),
              }}
            >
              <div className="font-medium text-white">
                {hoveredCell.cell.track_count.toLocaleString()} tracks
              </div>
              <div className="flex gap-3 mt-2 text-xs text-zinc-500">
                <span>
                  Energy: {Math.round(hoveredCell.cell.energy_min * 100)}-
                  {Math.round(hoveredCell.cell.energy_max * 100)}%
                </span>
                <span>
                  Valence: {Math.round(hoveredCell.cell.valence_min * 100)}-
                  {Math.round(hoveredCell.cell.valence_max * 100)}%
                </span>
              </div>
              {hoveredCell.cell.track_count > 0 && (
                <div className="text-xs text-purple-400 mt-2">
                  Click to view tracks
                </div>
              )}
            </div>
          )}
      </div>

      {/* Legend */}
      <div className="mt-2 flex-shrink-0 flex justify-center items-center gap-4">
        <div className="flex items-center gap-2 text-sm text-zinc-500">
          <span>Fewer</span>
          <div className="flex">
            {[0.3, 0.5, 0.7, 0.9, 1].map((alpha, i) => (
              <div
                key={i}
                className="w-5 h-3"
                style={{ backgroundColor: `rgba(168, 85, 247, ${alpha})` }}
              />
            ))}
          </div>
          <span>More</span>
        </div>
        <span className="text-zinc-600">|</span>
        <span className="text-sm text-zinc-500">
          Scroll to zoom, drag to pan
        </span>
      </div>
    </div>
  );
}
