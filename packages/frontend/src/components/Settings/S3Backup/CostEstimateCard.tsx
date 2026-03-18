import {
  Loader2,
  DollarSign,
  HardDrive,
  Database,
  Music,
  Image,
  Video,
  Settings,
  User,
} from 'lucide-react';
import type { S3CostEstimate } from '../../../api';
import { formatBytes } from './utils';

export function CostEstimateCard({
  estimate,
  isLoading,
}: {
  estimate: S3CostEstimate | null;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-zinc-400 py-2">
        <Loader2 className="w-4 h-4 animate-spin" />
        Calculating library size...
      </div>
    );
  }

  if (!estimate) return null;

  const categoryIcons: Record<string, React.ReactNode> = {
    audio: <Music className="w-3.5 h-3.5" />,
    artwork: <Image className="w-3.5 h-3.5" />,
    videos: <Video className="w-3.5 h-3.5" />,
    database: <Database className="w-3.5 h-3.5" />,
    settings: <Settings className="w-3.5 h-3.5" />,
    profiles: <User className="w-3.5 h-3.5" />,
  };

  return (
    <div className="bg-zinc-900/50 rounded-lg p-3 space-y-2">
      <div className="flex items-center gap-2 text-sm">
        <DollarSign className="w-4 h-4 text-green-400" />
        <span className="text-zinc-300 font-medium">Cost Estimate</span>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        {Object.entries(estimate.by_category).map(([name, cat]) => (
          <div key={name} className="flex items-center justify-between text-zinc-400">
            <div className="flex items-center gap-1.5">
              {categoryIcons[name] || <HardDrive className="w-3.5 h-3.5" />}
              <span className="capitalize">{name}</span>
            </div>
            <span>{formatBytes(cat.size_bytes)}</span>
          </div>
        ))}
      </div>

      <div className="border-t border-zinc-700 pt-2 space-y-1">
        <div className="flex justify-between text-sm">
          <span className="text-zinc-300">Total: {estimate.storage_gb.toFixed(1)} GB</span>
          <span className="text-green-400 font-medium">
            ${estimate.monthly_cost.toFixed(2)}/mo
          </span>
        </div>
        <div className="flex justify-between text-xs text-zinc-500">
          <span>Initial upload: ~${estimate.initial_upload_cost.toFixed(2)}</span>
          <span>Full restore: ~${estimate.estimated_restore_cost.toFixed(2)}</span>
        </div>
      </div>
    </div>
  );
}
