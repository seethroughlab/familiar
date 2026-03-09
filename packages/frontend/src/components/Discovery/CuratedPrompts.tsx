import {
  Music,
  Headphones,
  Radio,
  Mic,
  Sparkles,
  Sun,
  Moon,
  Coffee,
  Zap,
  Heart,
  RefreshCw,
  type LucideIcon,
} from 'lucide-react';
import type { CuratedPrompt } from '../../api/library';
import { useUIStore } from '../../stores/uiStore';

const ICON_MAP: Record<string, LucideIcon> = {
  music: Music,
  headphones: Headphones,
  radio: Radio,
  mic: Mic,
  sparkles: Sparkles,
  sun: Sun,
  moon: Moon,
  coffee: Coffee,
  zap: Zap,
  heart: Heart,
};

interface CuratedPromptsProps {
  prompts: CuratedPrompt[];
  loading: boolean;
  onRefresh: () => void;
}

export function CuratedPrompts({ prompts, loading, onRefresh }: CuratedPromptsProps) {
  if (!loading && prompts.length === 0) return null;

  const handleClick = (prompt: CuratedPrompt) => {
    useUIStore.getState().triggerChat(prompt.prompt);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-zinc-400 uppercase tracking-wider">
          Listening Ideas
        </h3>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="p-1 text-zinc-500 hover:text-zinc-300 transition-colors disabled:opacity-50"
          title="Generate new suggestions"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <div className="flex gap-3 overflow-x-auto pb-2 -mx-4 px-4 scrollbar-thin scrollbar-thumb-zinc-700">
        {loading
          ? Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="flex-shrink-0 w-64 h-24 rounded-lg bg-zinc-800/50 animate-pulse"
              />
            ))
          : prompts.map((prompt, i) => {
              const Icon = ICON_MAP[prompt.icon ?? ''] ?? Sparkles;
              return (
                <button
                  key={i}
                  onClick={() => handleClick(prompt)}
                  className="flex-shrink-0 w-64 rounded-lg bg-zinc-800/60 hover:bg-zinc-700/60 border border-zinc-700/50 hover:border-purple-500/30 p-3.5 text-left transition-all group"
                >
                  <div className="flex items-start gap-2.5">
                    <div className="mt-0.5 p-1.5 rounded-md bg-purple-500/10 text-purple-400 group-hover:bg-purple-500/20 transition-colors">
                      <Icon className="w-4 h-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-zinc-200 leading-snug line-clamp-2">
                        {prompt.prompt}
                      </p>
                      {prompt.context && (
                        <p className="text-xs text-zinc-500 mt-1 truncate">
                          {prompt.context}
                        </p>
                      )}
                    </div>
                  </div>
                </button>
              );
            })}
      </div>
    </div>
  );
}
