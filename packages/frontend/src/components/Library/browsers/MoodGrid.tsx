/**
 * MoodGrid Browser - 2D heatmap of tracks by configurable audio features.
 *
 * Default axes: X=Valence, Y=Energy (backward compatible).
 * Users can select any 0-1 feature for either axis via dropdowns.
 *
 * When using the default energy/valence combo, shows mood quadrant labels.
 * Click a cell to navigate to filtered track list for that region.
 */
import { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Sparkles, Loader2, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react';
import { libraryApi, type MoodCell } from '../../../api';
import { queryKeys } from '../../../api/queryKeys';
import { registerBrowser, type BrowserProps } from '../types';
import { useOfflineStatus } from '../../../hooks/useOfflineStatus';

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

const AXIS_OPTIONS = [
  { value: 'energy', label: 'Energy', low: 'Calm', high: 'Energetic' },
  { value: 'valence', label: 'Valence', low: 'Sad', high: 'Happy' },
  { value: 'danceability', label: 'Danceability', low: 'Still', high: 'Danceable' },
  { value: 'acousticness', label: 'Acousticness', low: 'Produced', high: 'Acoustic' },
  { value: 'brightness', label: 'Brightness', low: 'Dark', high: 'Bright' },
  { value: 'harmonic_complexity', label: 'Harmonic Complexity', low: 'Simple', high: 'Complex' },
  { value: 'instrumentalness', label: 'Instrumentalness', low: 'Vocal', high: 'Instrumental' },
  { value: 'speechiness', label: 'Speechiness', low: 'Singing', high: 'Spoken' },
  { value: 'swing_ratio', label: 'Swing', low: 'Straight', high: 'Swung' },
  { value: 'syncopation', label: 'Syncopation', low: 'On-beat', high: 'Syncopated' },
] as const;

function getAxisMeta(value: string) {
  return AXIS_OPTIONS.find((a) => a.value === value) ?? AXIS_OPTIONS[0];
}

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
  const { isOffline } = useOfflineStatus();

  // Configurable axes
  const [xAxis, setXAxis] = useState('valence');
  const [yAxis, setYAxis] = useState('energy');
  const isDefaultAxes = xAxis === 'valence' && yAxis === 'energy';

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
    queryKey: queryKeys.libraryMoodDistribution.detail(xAxis, yAxis),
    queryFn: () => libraryApi.getMoodDistribution(10, xAxis, yAxis),
    enabled: !isOffline,
  });

  // Calculate max count for color scaling
  const maxCount = useMemo(() => {
    if (!data?.cells) return 1;
    return Math.max(...data.cells.map((c) => c.track_count), 1);
  }, [data]);

  // Axis metadata for labels
  const xMeta = getAxisMeta(xAxis);
  const yMeta = getAxisMeta(yAxis);

  // Handle navigating to tracks in a cell
  const handleCellClick = useCallback(
    (cell: MoodCell) => {
      // Ignore click if we were panning
      if (didPanRef.current) return;
      if (cell.track_count === 0) return;
      onGoToMood(xAxis, cell.x_min, cell.x_max, yAxis, cell.y_min, cell.y_max);
    },
    [onGoToMood, xAxis, yAxis]
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

  if (isOffline) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-zinc-500 gap-2 px-6 text-center">
        <p className="text-zinc-300">Similarity views are not available offline.</p>
        <p className="text-sm">Reconnect to load feature-based map data.</p>
      </div>
    );
  }

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

  // Quadrant labels (only for default energy/valence combo)
  const quadrants = isDefaultAxes
    ? [
        { label: 'Angry', sublabel: 'Intense', x: 0.25, y: 0.75 },
        { label: 'Happy', sublabel: 'Energetic', x: 0.75, y: 0.75 },
        { label: 'Sad', sublabel: 'Melancholic', x: 0.25, y: 0.25 },
        { label: 'Relaxed', sublabel: 'Peaceful', x: 0.75, y: 0.25 },
      ]
    : [];

  // Convert data coordinates (0-1) to SVG coordinates
  const dataToSvg = (xVal: number, yVal: number) => ({
    x: padding.left + offsetX + xVal * gridSide,
    y: padding.top + offsetY + (1 - yVal) * gridSide,
  });

  return (
    <div className="flex flex-col h-full p-4">
      {/* Stats and controls */}
      <div className="flex items-center justify-between mb-2 flex-shrink-0 flex-wrap gap-2">
        <div className="flex items-center gap-4 text-sm text-zinc-400">
          <span>{data.total_with_mood.toLocaleString()} tracks</span>
          {data.total_without_mood > 0 && (
            <span className="text-zinc-500">
              ({data.total_without_mood.toLocaleString()} without analysis)
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Axis selectors */}
          <div className="flex items-center gap-1.5 text-sm">
            <label className="text-zinc-500">X:</label>
            <select
              value={xAxis}
              onChange={(e) => setXAxis(e.target.value)}
              className="bg-zinc-800 text-zinc-200 border border-zinc-700 rounded px-2 py-1 text-sm focus:outline-none focus:border-purple-500"
            >
              {AXIS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-1.5 text-sm">
            <label className="text-zinc-500">Y:</label>
            <select
              value={yAxis}
              onChange={(e) => setYAxis(e.target.value)}
              className="bg-zinc-800 text-zinc-200 border border-zinc-700 rounded px-2 py-1 text-sm focus:outline-none focus:border-purple-500"
            >
              {AXIS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>

          {/* Zoom controls */}
          <div className="flex items-center gap-2 ml-2">
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
              {xMeta.label} ({xMeta.low} → {xMeta.high})
            </text>
            <text
              x={padding.left + offsetX - 25}
              y={padding.top + offsetY + gridSide / 2}
              textAnchor="middle"
              className="fill-zinc-400"
              style={{ fontSize: 11 }}
              transform={`rotate(-90, ${padding.left + offsetX - 25}, ${padding.top + offsetY + gridSide / 2})`}
            >
              {yMeta.label} ({yMeta.low} → {yMeta.high})
            </text>

            {/* Quadrant labels (only for default energy/valence) */}
            {quadrants.map((q, i) => {
              const pos = dataToSvg(q.x, q.y);
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
              const x = padding.left + offsetX + cell.x_min * gridSide;
              const y = padding.top + offsetY + (1 - cell.y_max) * gridSide;
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
                  {xMeta.label}: {Math.round(hoveredCell.cell.x_min * 100)}-
                  {Math.round(hoveredCell.cell.x_max * 100)}%
                </span>
                <span>
                  {yMeta.label}: {Math.round(hoveredCell.cell.y_min * 100)}-
                  {Math.round(hoveredCell.cell.y_max * 100)}%
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
