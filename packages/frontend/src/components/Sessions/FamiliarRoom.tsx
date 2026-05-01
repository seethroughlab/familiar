import type { CSSProperties } from 'react';
import type { SessionParticipant } from '../../hooks/useListeningSession';
import {
  FAMILIAR_ACCENTS,
  FAMILIAR_VARIANTS,
  SESSION_REACTIONS,
  type FamiliarConfig,
  type SessionReaction,
  type SessionReactionKind,
} from '../../services/listeningSessionFamiliars';

interface FamiliarRoomProps {
  participants: SessionParticipant[];
  reactions: SessionReaction[];
  myUserId?: string | null;
  isLight?: boolean;
}

interface FamiliarPickerProps {
  value: FamiliarConfig;
  onChange: (next: FamiliarConfig) => void;
  isLight?: boolean;
}

interface ReactionBarProps {
  onReact: (kind: SessionReactionKind) => void;
  isLight?: boolean;
}

const reactionCopy: Record<SessionReactionKind, string> = {
  cheer: 'Cheer',
  pulse: 'Pulse',
  wave: 'Wave',
  spark: 'Spark',
};

function withAlpha(hex: string, alpha: string): string {
  return `${hex}${alpha}`;
}

function familiarSurfaceStyle(familiar: FamiliarConfig): CSSProperties {
  return {
    background: `radial-gradient(circle at 30% 30%, ${withAlpha(familiar.color, 'cc')}, ${withAlpha(familiar.color, '0d')} 65%, transparent 100%)`,
    boxShadow: `0 0 0 1px ${withAlpha(familiar.color, '33')}, 0 18px 35px ${withAlpha(familiar.color, '22')}`,
  };
}

function FamiliarGlyph({
  familiar,
  size = 'md',
}: {
  familiar: FamiliarConfig;
  size?: 'sm' | 'md';
}) {
  const wrapperSize = size === 'sm' ? 'w-9 h-9' : 'w-14 h-14';
  const coreSize = size === 'sm' ? 'w-4 h-4' : 'w-6 h-6';
  return (
    <div
      className={`${wrapperSize} relative rounded-full backdrop-blur-sm overflow-hidden`}
      style={familiarSurfaceStyle(familiar)}
    >
      <div
        className={`absolute inset-2 rounded-full border ${familiar.accent === 'ripple' ? 'animate-pulse' : ''}`}
        style={{ borderColor: withAlpha(familiar.color, '55') }}
      />
      {familiar.accent === 'orbit' && (
        <div className="absolute inset-1 rounded-full border border-white/10 animate-[spin_10s_linear_infinite]">
          <span
            className="absolute -top-0.5 left-1/2 w-1.5 h-1.5 -translate-x-1/2 rounded-full"
            style={{ backgroundColor: familiar.color }}
          />
        </div>
      )}
      <div className="absolute inset-0 flex items-center justify-center">
        {familiar.variant === 'halo' && (
          <div
            className={`${coreSize} rounded-full border`}
            style={{ borderColor: familiar.color, boxShadow: `0 0 18px ${withAlpha(familiar.color, '55')}` }}
          />
        )}
        {familiar.variant === 'ember' && (
          <>
            <div
              className={`${coreSize} rounded-full blur-sm opacity-75`}
              style={{ backgroundColor: withAlpha(familiar.color, '88') }}
            />
            <div
              className={`${coreSize} absolute rounded-full`}
              style={{ backgroundColor: withAlpha(familiar.color, 'dd') }}
            />
          </>
        )}
        {familiar.variant === 'prism' && (
          <div
            className={`${coreSize} rotate-45 rounded-[0.4rem] border`}
            style={{ borderColor: familiar.color, backgroundColor: withAlpha(familiar.color, '33') }}
          />
        )}
      </div>
      {familiar.accent === 'drift' && (
        <div
          className="absolute inset-x-3 bottom-2 h-px rounded-full opacity-80"
          style={{ backgroundColor: withAlpha(familiar.color, 'aa') }}
        />
      )}
    </div>
  );
}

export function FamiliarRoom({
  participants,
  reactions,
  myUserId,
  isLight = false,
}: FamiliarRoomProps) {
  const latestReactionByUser = new Map<string, SessionReaction>();
  for (const reaction of reactions) {
    latestReactionByUser.set(reaction.user_id, reaction);
  }

  return (
    <div
      className={`rounded-xl border p-4 ${
        isLight
          ? 'border-zinc-200 bg-[radial-gradient(circle_at_top,_rgba(244,244,245,0.9),_rgba(255,255,255,0.98))]'
          : 'border-zinc-800 bg-[radial-gradient(circle_at_top,_rgba(39,39,42,0.92),_rgba(9,9,11,0.98))]'
      }`}
    >
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className={`text-sm font-medium ${isLight ? 'text-zinc-800' : 'text-zinc-100'}`}>Mini Room</div>
          <div className={`text-xs ${isLight ? 'text-zinc-500' : 'text-zinc-500'}`}>
            Subtle familiars for everyone currently listening
          </div>
        </div>
        <div className={`text-xs ${isLight ? 'text-zinc-500' : 'text-zinc-500'}`}>
          {participants.length} present
        </div>
      </div>

      <div className="flex flex-wrap justify-center gap-3">
        {participants.map((participant) => {
          const reaction = latestReactionByUser.get(participant.user_id);
          const isSelf = participant.user_id === myUserId;
          const isLive = participant.role === 'host' || participant.webrtc_connected;
          return (
            <div
              key={participant.user_id}
              className={`relative w-24 rounded-xl border px-2 py-3 text-center ${
                isLight
                  ? 'border-zinc-200 bg-white/70'
                  : 'border-zinc-800 bg-black/20'
              } ${isSelf ? 'ring-1 ring-emerald-500/40' : ''}`}
            >
              {reaction && (
                <div
                  className={`absolute -top-2 left-1/2 -translate-x-1/2 rounded-full px-2 py-0.5 text-[10px] uppercase tracking-[0.2em] ${
                    isLight ? 'bg-white text-zinc-700 border border-zinc-200' : 'bg-zinc-950 text-zinc-200 border border-zinc-700'
                  }`}
                >
                  {reactionCopy[reaction.kind]}
                </div>
              )}
              <div className="mb-2 flex justify-center">
                <FamiliarGlyph familiar={participant.familiar} />
              </div>
              <div className={`truncate text-xs font-medium ${isLight ? 'text-zinc-800' : 'text-zinc-200'}`}>
                {participant.username}
              </div>
              <div className={`mt-1 text-[10px] uppercase tracking-[0.18em] ${isLight ? 'text-zinc-500' : 'text-zinc-500'}`}>
                {participant.role}
              </div>
              <div className="mt-2 flex items-center justify-center gap-1">
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    isLive ? 'bg-emerald-400 shadow-[0_0_10px_rgba(16,185,129,0.7)]' : 'bg-zinc-500'
                  }`}
                />
                <span className={`text-[10px] ${isLight ? 'text-zinc-500' : 'text-zinc-500'}`}>
                  {isLive ? 'Live' : 'Idle'}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function FamiliarPicker({ value, onChange, isLight = false }: FamiliarPickerProps) {
  const baseClasses = isLight
    ? 'border-zinc-200 bg-white text-zinc-700'
    : 'border-zinc-700 bg-zinc-800 text-zinc-200';

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <div className={`text-sm font-medium ${isLight ? 'text-zinc-800' : 'text-zinc-100'}`}>Your familiar</div>
          <div className={`text-xs ${isLight ? 'text-zinc-500' : 'text-zinc-500'}`}>
            Light-touch identity, synced for everyone in the room
          </div>
        </div>
        <FamiliarGlyph familiar={value} size="sm" />
      </div>

      <div className="grid grid-cols-3 gap-2">
        {FAMILIAR_VARIANTS.map((variant) => (
          <button
            key={variant}
            type="button"
            onClick={() => onChange({ ...value, variant })}
            className={`rounded-lg border px-2 py-2 text-xs capitalize transition-colors ${baseClasses} ${
              value.variant === variant ? 'ring-1 ring-emerald-500/50' : ''
            }`}
          >
            {variant}
          </button>
        ))}
      </div>

      <div className="flex gap-2">
        {['#7dd3fc', '#a7f3d0', '#c4b5fd', '#f9a8d4', '#fcd34d', '#fdba74'].map((color) => (
          <button
            key={color}
            type="button"
            aria-label={`Set familiar color ${color}`}
            onClick={() => onChange({ ...value, color })}
            className={`h-8 flex-1 rounded-full border ${value.color === color ? 'ring-2 ring-emerald-500/50 ring-offset-1 ring-offset-transparent' : ''}`}
            style={{ backgroundColor: color, borderColor: withAlpha(color, '66') }}
          />
        ))}
      </div>

      <div className="grid grid-cols-3 gap-2">
        {FAMILIAR_ACCENTS.map((accent) => (
          <button
            key={accent}
            type="button"
            onClick={() => onChange({ ...value, accent })}
            className={`rounded-lg border px-2 py-2 text-xs capitalize transition-colors ${baseClasses} ${
              value.accent === accent ? 'ring-1 ring-emerald-500/50' : ''
            }`}
          >
            {accent}
          </button>
        ))}
      </div>
    </div>
  );
}

export function ReactionBar({ onReact, isLight = false }: ReactionBarProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {SESSION_REACTIONS.map((reaction) => (
        <button
          key={reaction}
          type="button"
          onClick={() => onReact(reaction)}
          className={`rounded-full border px-3 py-1.5 text-xs uppercase tracking-[0.18em] transition-colors ${
            isLight
              ? 'border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50'
              : 'border-zinc-700 bg-zinc-800 text-zinc-200 hover:bg-zinc-700'
          }`}
        >
          {reactionCopy[reaction]}
        </button>
      ))}
    </div>
  );
}
