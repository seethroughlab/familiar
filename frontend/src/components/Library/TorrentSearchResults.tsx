import { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Download,
  ExternalLink,
  HardDrive,
  Loader2,
  Check,
} from 'lucide-react';
import { torrentSearchApi } from '../../api';
import type { TorrentResult } from '../../api';

interface TorrentSearchButtonProps {
  artist: string;
  title?: string;
  album?: string;
}

export function TorrentSearchButton({ artist, title, album }: TorrentSearchButtonProps) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const toggle = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setOpen((v) => !v);
  }, []);

  // Click-outside and escape dismissal
  useEffect(() => {
    if (!open) return;

    const handleClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (buttonRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };

    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };

    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  const getPosition = () => {
    if (!buttonRef.current) return { top: 0, left: 0 };
    const rect = buttonRef.current.getBoundingClientRect();
    const menuWidth = 340;
    const menuHeight = 300;

    let top = rect.bottom + 4;
    let left = rect.right - menuWidth;

    if (top + menuHeight > window.innerHeight - 16) {
      top = rect.top - menuHeight - 4;
    }
    if (left < 8) {
      left = 8;
    }
    if (left + menuWidth > window.innerWidth - 8) {
      left = window.innerWidth - menuWidth - 8;
    }

    return { top, left };
  };

  return (
    <>
      <button
        ref={buttonRef}
        onClick={toggle}
        title="Search torrents"
        className={`px-1.5 py-0.5 text-[10px] font-medium rounded transition-colors ${
          open
            ? 'bg-violet-500 text-white'
            : 'bg-violet-500/20 text-violet-400 hover:bg-violet-500/30'
        }`}
      >
        DL
      </button>

      {open &&
        createPortal(
          <div
            ref={menuRef}
            className="fixed z-50 w-[340px] bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl overflow-hidden"
            style={getPosition()}
            onClick={(e) => e.stopPropagation()}
          >
            <TorrentSearchDropdown
              artist={artist}
              title={title}
              album={album}
            />
          </div>,
          document.body,
        )}
    </>
  );
}

function TorrentSearchDropdown({
  artist,
  title,
  album,
}: {
  artist: string;
  title?: string;
  album?: string;
}) {
  const [showAll, setShowAll] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ['torrent-search', artist, title, album],
    queryFn: () => torrentSearchApi.search({ artist, title, album }),
    staleTime: 5 * 60 * 1000,
  });

  const results = data?.results ?? [];
  const displayed = showAll ? results : results.slice(0, 5);
  const remaining = results.length - 5;

  return (
    <>
      {/* Header */}
      <div className="px-3 py-2 border-b border-zinc-700">
        <span className="text-xs text-zinc-400">
          {isLoading ? 'Searching...' : `${results.length} result${results.length !== 1 ? 's' : ''}`}
          {data?.query && <span className="text-zinc-500"> for &quot;{data.query}&quot;</span>}
        </span>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center justify-center gap-2 p-4 text-zinc-400 text-sm">
          <Loader2 className="w-4 h-4 animate-spin" />
          Searching...
        </div>
      )}

      {/* Error */}
      {(error || data?.error) && (
        <div className="px-3 py-2 text-xs text-red-400">
          {data?.error || 'Search failed'}
        </div>
      )}

      {/* Empty */}
      {!isLoading && results.length === 0 && !data?.error && (
        <div className="px-3 py-3 text-xs text-zinc-500 text-center">
          No torrents found
        </div>
      )}

      {/* Results (scrollable) */}
      <div className="max-h-[260px] overflow-y-auto">
        {displayed.map((result, i) => (
          <ResultRow key={`${result.title}-${i}`} result={result} />
        ))}
      </div>

      {/* Show more */}
      {!showAll && remaining > 0 && (
        <button
          onClick={() => setShowAll(true)}
          className="w-full px-3 py-1.5 text-xs text-zinc-400 hover:text-white hover:bg-zinc-700/50 transition-colors border-t border-zinc-700"
        >
          +{remaining} more
        </button>
      )}
    </>
  );
}

function ResultRow({ result }: { result: TorrentResult }) {
  const [downloadState, setDownloadState] = useState<'idle' | 'loading' | 'done' | 'error'>('idle');
  const [errorMsg, setErrorMsg] = useState('');

  const downloadUrl = result.magnet_url || result.torrent_url;

  async function handleDownload(e: React.MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    if (!downloadUrl || downloadState === 'loading') return;

    setDownloadState('loading');
    try {
      const resp = await torrentSearchApi.download(downloadUrl);
      if (resp.ok) {
        setDownloadState('done');
      } else {
        setDownloadState('error');
        setErrorMsg(resp.error || 'Failed');
      }
    } catch {
      setDownloadState('error');
      setErrorMsg('Request failed');
    }
  }

  const seederColor =
    result.seeders > 10
      ? 'text-green-400'
      : result.seeders > 0
        ? 'text-yellow-400'
        : 'text-red-400';

  const categoryBadge =
    result.category === 'lossless'
      ? 'bg-amber-500/20 text-amber-400'
      : 'bg-zinc-600/50 text-zinc-400';

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 border-t border-zinc-700/50 hover:bg-zinc-700/30 transition-colors">
      {/* Title + category */}
      <div className="flex-1 min-w-0">
        <p className="text-xs text-zinc-200 truncate" title={result.title}>
          {result.title}
        </p>
        <div className="flex items-center gap-2 mt-0.5">
          <span className={`px-1 py-0.5 text-[9px] font-medium rounded ${categoryBadge}`}>
            {result.category === 'lossless' ? 'FLAC' : result.category.toUpperCase()}
          </span>
          <span className="flex items-center gap-0.5 text-[10px] text-zinc-500">
            <HardDrive className="w-3 h-3" />
            {result.size_display}
          </span>
          <span className={`text-[10px] ${seederColor}`}>
            {result.seeders}S
          </span>
          {downloadState === 'error' && (
            <span className="text-[10px] text-red-400 truncate" title={errorMsg}>{errorMsg}</span>
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1 flex-shrink-0">
        {downloadUrl && (
          <button
            onClick={handleDownload}
            disabled={downloadState === 'loading' || downloadState === 'done'}
            title={downloadState === 'done' ? 'Sent to Transmission' : downloadState === 'error' ? errorMsg : 'Send to Transmission'}
            className={`p-1 transition-colors rounded ${
              downloadState === 'done'
                ? 'text-green-400'
                : downloadState === 'error'
                  ? 'text-red-400 hover:text-red-300 hover:bg-red-500/20'
                  : 'text-violet-400 hover:text-violet-300 hover:bg-violet-500/20'
            } disabled:opacity-50`}
          >
            {downloadState === 'loading' ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : downloadState === 'done' ? (
              <Check className="w-3.5 h-3.5" />
            ) : (
              <Download className="w-3.5 h-3.5" />
            )}
          </button>
        )}
        {result.info_url && (
          <a
            href={result.info_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            title="View on indexer"
            className="p-1 text-zinc-500 hover:text-white transition-colors rounded hover:bg-zinc-700/50"
          >
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        )}
      </div>
    </div>
  );
}
