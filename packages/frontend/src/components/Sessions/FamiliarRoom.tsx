import { useEffect, useRef, type CSSProperties } from 'react';
import { Crown } from 'lucide-react';
import type { SessionParticipant } from '../../hooks/useListeningSession';
import {
  BOB_AMPLITUDE_CROWD_PX,
  BOB_AMPLITUDE_HOST_PX,
  FAMILIAR_ACCENTS,
  FAMILIAR_VARIANTS,
  SESSION_REACTIONS,
  computeBeatPhase,
  computeRoomPosition,
  type BeatAnchor,
  type FamiliarConfig,
  type SessionReaction,
  type SessionReactionKind,
} from '../../services/listeningSessionFamiliars';

const TRACK_GLOW_DURATION_MS = 1200;

interface FamiliarRoomProps {
  participants: SessionParticipant[];
  reactions: SessionReaction[];
  myUserId?: string | null;
  isLight?: boolean;
  beatAnchor?: BeatAnchor | null;
}

function useStageBeat(
  anchor: BeatAnchor | null | undefined,
  stageRef: React.RefObject<HTMLDivElement | null>,
) {
  const lastTrackIdRef = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    let raf = 0;
    const loop = () => {
      const now = Date.now();
      const phase = computeBeatPhase(anchor ?? null, now);
      const sinPhase = Math.sin(phase * 2 * Math.PI);
      stage.style.setProperty('--bob-y', `${sinPhase * BOB_AMPLITUDE_CROWD_PX}px`);
      stage.style.setProperty('--bob-y-host', `${sinPhase * BOB_AMPLITUDE_HOST_PX}px`);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [anchor, stageRef]);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const trackId = anchor?.trackId ?? null;
    const previous = lastTrackIdRef.current;
    lastTrackIdRef.current = trackId;
    if (previous === undefined) return; // first observation, no glow
    if (previous === trackId) return;
    if (!trackId) return; // don't glow when track clears
    stage.classList.add('familiar-room-glowing');
    const timer = window.setTimeout(() => {
      stage.classList.remove('familiar-room-glowing');
    }, TRACK_GLOW_DURATION_MS);
    return () => {
      window.clearTimeout(timer);
      stage.classList.remove('familiar-room-glowing');
    };
  }, [anchor?.trackId, stageRef]);
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
  beatAnchor,
}: FamiliarRoomProps) {
  const stageRef = useRef<HTMLDivElement>(null);
  useStageBeat(beatAnchor, stageRef);

  const latestReactionByUser = new Map<string, SessionReaction>();
  for (const reaction of reactions) {
    latestReactionByUser.set(reaction.user_id, reaction);
  }

  const host = participants.find((p) => p.role === 'host') ?? null;
  const crowd = participants
    .filter((p) => p.role !== 'host')
    .slice()
    .sort((a, b) => (a.user_id < b.user_id ? -1 : a.user_id > b.user_id ? 1 : 0));

  const stageBg = isLight
    ? 'bg-[radial-gradient(ellipse_at_top,_rgba(228,228,231,0.9),_rgba(255,255,255,0.98)_55%,_rgba(244,244,245,1))]'
    : 'bg-[radial-gradient(ellipse_at_top,_rgba(39,39,42,0.95),_rgba(17,17,20,0.98)_55%,_rgba(9,9,11,1))]';
  const floorLine = isLight ? 'bg-zinc-200/80' : 'bg-zinc-700/40';
  const stageLabel = isLight ? 'text-zinc-500' : 'text-zinc-500';

  return (
    <div
      className={`rounded-xl border overflow-hidden ${
        isLight ? 'border-zinc-200' : 'border-zinc-800'
      }`}
    >
      <div className="flex items-center justify-between px-3 pt-2 pb-1">
        <div className={`text-[10px] uppercase tracking-[0.22em] ${stageLabel}`}>The Room</div>
        <div className={`text-xs ${stageLabel}`}>{participants.length} present</div>
      </div>
      <div ref={stageRef} className={`relative w-full aspect-[3/2] ${stageBg}`}>
        <div
          className={`absolute left-0 right-0 h-px ${floorLine}`}
          style={{ top: '44%' }}
          aria-hidden
        />
        <div
          className={`absolute left-1/2 -translate-x-1/2 text-[9px] uppercase tracking-[0.28em] ${stageLabel}`}
          style={{ top: '4%' }}
          aria-hidden
        >
          DJ Booth
        </div>

        {host && (
          <RoomAvatar
            participant={host}
            position={computeRoomPosition(host, 0, 0)}
            isHost
            isSelf={host.user_id === myUserId}
            isLive
            reaction={latestReactionByUser.get(host.user_id)}
            isLight={isLight}
          />
        )}

        {crowd.map((participant, index) => (
          <RoomAvatar
            key={participant.user_id}
            participant={participant}
            position={computeRoomPosition(participant, index, crowd.length)}
            isHost={false}
            isSelf={participant.user_id === myUserId}
            isLive={participant.webrtc_connected ?? false}
            reaction={latestReactionByUser.get(participant.user_id)}
            isLight={isLight}
          />
        ))}
      </div>
    </div>
  );
}

interface RoomAvatarProps {
  participant: SessionParticipant;
  position: { xPct: number; yPct: number };
  isHost: boolean;
  isSelf: boolean;
  isLive: boolean;
  reaction?: SessionReaction;
  isLight: boolean;
}

function RoomAvatar({
  participant,
  position,
  isHost,
  isSelf,
  isLive,
  reaction,
  isLight,
}: RoomAvatarProps) {
  const bobVar = isHost ? 'var(--bob-y-host, 0px)' : 'var(--bob-y, 0px)';
  const wrapperStyle: CSSProperties = {
    left: `${position.xPct}%`,
    top: `${position.yPct}%`,
    transform: `translate(-50%, calc(-50% + ${bobVar}))`,
  };
  const reactionKey = reaction
    ? `${reaction.user_id}-${reaction.kind}-${reaction.timestamp instanceof Date ? reaction.timestamp.getTime() : reaction.timestamp}`
    : undefined;
  const labelClass = isLight ? 'text-zinc-700' : 'text-zinc-300';
  const subtleLabel = isLight ? 'text-zinc-500' : 'text-zinc-500';

  return (
    <div
      className="absolute pointer-events-none"
      style={wrapperStyle}
    >
      {reaction && (
        <div
          key={reactionKey}
          className={`absolute left-1/2 -top-3 rounded-full px-1.5 py-px text-[9px] uppercase tracking-[0.18em] whitespace-nowrap border ${
            isLight ? 'bg-white text-zinc-700 border-zinc-200' : 'bg-zinc-950 text-zinc-200 border-zinc-700'
          }`}
          style={{ animation: 'familiar-reaction-rise 4s ease-out forwards' }}
          aria-hidden
        >
          {reactionCopy[reaction.kind]}
        </div>
      )}
      {isHost && (
        <div
          className="absolute left-1/2 -translate-x-1/2 rounded-[50%]"
          style={{
            top: 'calc(100% - 8px)',
            width: '64px',
            height: '14px',
            background: `radial-gradient(ellipse at center, ${withAlpha(participant.familiar.color, '55')}, transparent 70%)`,
            filter: 'blur(2px)',
          }}
          aria-hidden
        />
      )}
      <div
        className={`relative ${isSelf ? 'ring-2 ring-emerald-400/60 ring-offset-2 ring-offset-transparent rounded-full' : ''}`}
      >
        <FamiliarGlyph familiar={participant.familiar} size={isHost ? 'md' : 'sm'} />
        {isHost && (
          <Crown
            className="absolute -top-3 left-1/2 -translate-x-1/2 w-3.5 h-3.5 text-yellow-400"
            aria-hidden
          />
        )}
        {!isLive && !isHost && (
          <div
            className="absolute inset-0 rounded-full bg-black/30"
            aria-hidden
          />
        )}
      </div>
      <div
        className={`absolute left-1/2 -translate-x-1/2 mt-1 text-[9px] font-medium truncate max-w-[64px] text-center ${labelClass}`}
        style={{ top: '100%' }}
      >
        {participant.username}
        {isSelf && <span className={`ml-1 ${subtleLabel}`}>(you)</span>}
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
