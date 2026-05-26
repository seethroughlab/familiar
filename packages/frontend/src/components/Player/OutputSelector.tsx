import { useEffect, useRef, useState } from 'react';
import { Monitor, Wifi, Radio, Cast, Speaker, RefreshCw, Check } from 'lucide-react';
import { useOutputStore } from '../../stores/outputStore';
import type { OutputType } from '../../api/outputs';

const TYPE_ICONS: Record<OutputType, typeof Monitor> = {
  browser: Monitor,
  upnp: Wifi,
  airplay: Radio,
  chromecast: Cast,
  sonos: Speaker,
};

const TYPE_LABELS: Record<OutputType, string> = {
  browser: 'This Device',
  upnp: 'UPnP / WiiM',
  airplay: 'AirPlay',
  chromecast: 'Chromecast',
  sonos: 'Sonos',
};

export function OutputSelector() {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const { outputs, activeOutputId, isDiscovering, fetchOutputs, discover, setActive } =
    useOutputStore();

  // Load outputs on first open
  useEffect(() => {
    if (isOpen && outputs.length === 0) {
      fetchOutputs().catch(() => {});
    }
  }, [isOpen, outputs.length, fetchOutputs]);

  // Close on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen]);

  // Close on escape
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsOpen(false);
    };
    if (isOpen) {
      document.addEventListener('keydown', handleEscape);
      return () => document.removeEventListener('keydown', handleEscape);
    }
  }, [isOpen]);

  const activeOutput = outputs.find((o) => o.id === activeOutputId);
  const ActiveIcon = activeOutput ? TYPE_ICONS[activeOutput.type] ?? Monitor : Monitor;
  const isNetworkActive = !!activeOutputId;

  return (
    <div ref={containerRef} className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`p-2 rounded-full transition-colors ${
          isNetworkActive
            ? 'text-green-400 hover:bg-white/10'
            : 'text-zinc-400 hover:text-white hover:bg-white/10'
        }`}
        aria-label="Select audio output"
        title="Audio Output"
      >
        <ActiveIcon className="w-5 h-5" />
      </button>

      {isOpen && (
        <div className="absolute bottom-full right-0 mb-2 w-64 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl z-50 overflow-hidden">
          <div className="p-2 border-b border-zinc-700">
            <span className="text-xs text-zinc-500 uppercase tracking-wide">Play To</span>
          </div>

          <div className="max-h-72 overflow-y-auto">
            {/* Browser (This Device) is always first */}
            <OutputRow
              id={null}
              name="This Device"
              type="browser"
              isActive={!activeOutputId}
              onClick={() => {
                setActive(null);
                setIsOpen(false);
              }}
            />

            {/* Network outputs */}
            {outputs
              .filter((o) => o.type !== 'browser')
              .map((output) => (
                <OutputRow
                  key={output.id}
                  id={output.id}
                  name={output.name}
                  type={output.type}
                  isActive={activeOutputId === output.id}
                  onClick={() => {
                    setActive(output.id);
                    setIsOpen(false);
                  }}
                />
              ))}

            {outputs.filter((o) => o.type !== 'browser').length === 0 && (
              <div className="px-3 py-4 text-center text-zinc-500 text-sm">
                No network devices found
              </div>
            )}
          </div>

          <div className="border-t border-zinc-700 p-2">
            <button
              onClick={() => discover()}
              disabled={isDiscovering}
              className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-zinc-400 hover:text-white hover:bg-white/5 transition-colors text-sm disabled:opacity-50"
            >
              <RefreshCw className={`w-4 h-4 ${isDiscovering ? 'animate-spin' : ''}`} />
              {isDiscovering ? 'Scanning…' : 'Scan for devices'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function OutputRow({
  id: _id,
  name,
  type,
  isActive,
  onClick,
}: {
  id: string | null;
  name: string;
  type: OutputType;
  isActive: boolean;
  onClick(): void;
}) {
  const Icon = TYPE_ICONS[type] ?? Monitor;
  const typeLabel = TYPE_LABELS[type] ?? type;

  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-3 px-3 py-2.5 text-left transition-colors ${
        isActive ? 'bg-green-500/10 text-white' : 'text-zinc-300 hover:bg-white/5 hover:text-white'
      }`}
    >
      <div
        className={`p-1.5 rounded-lg shrink-0 ${isActive ? 'bg-green-500/20' : 'bg-zinc-800'}`}
      >
        <Icon className="w-4 h-4" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-medium text-sm truncate">{name}</div>
        <div className="text-xs text-zinc-500">{typeLabel}</div>
      </div>
      {isActive && <Check className="w-4 h-4 text-green-400 shrink-0" />}
    </button>
  );
}
