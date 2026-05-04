export type FamiliarVariant = 'halo' | 'ember' | 'prism';
export type FamiliarAccent = 'drift' | 'orbit' | 'ripple';
export type SessionReactionKind = 'cheer' | 'pulse' | 'wave' | 'spark';

export interface FamiliarConfig {
  variant: FamiliarVariant;
  color: string;
  accent: FamiliarAccent;
  seed: number;
}

export interface SessionReaction {
  user_id: string;
  username?: string;
  kind: SessionReactionKind;
  timestamp: Date;
}

export const FAMILIAR_VARIANTS: FamiliarVariant[] = ['halo', 'ember', 'prism'];
export const FAMILIAR_ACCENTS: FamiliarAccent[] = ['drift', 'orbit', 'ripple'];
export const SESSION_REACTIONS: SessionReactionKind[] = ['cheer', 'pulse', 'wave', 'spark'];

const DEFAULT_COLOR = '#7dd3fc';
const DEFAULT_PALETTE = ['#7dd3fc', '#a7f3d0', '#c4b5fd', '#f9a8d4', '#fcd34d', '#fdba74'];
const STORAGE_KEY_PREFIX = 'familiar:listening-session:familiar:';

export function hashString(value: string): number {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
  }
  return hash;
}

export function normalizeFamiliarColor(value?: string | null): string {
  if (!value) return DEFAULT_COLOR;
  const text = value.trim();
  if (/^#[0-9a-fA-F]{6}$/.test(text)) return text.toLowerCase();
  return DEFAULT_COLOR;
}

export function createGeneratedFamiliar(name: string, color?: string | null): FamiliarConfig {
  const seed = hashString(name || 'Anonymous');
  const normalizedColor = color ? normalizeFamiliarColor(color) : null;
  return {
    variant: FAMILIAR_VARIANTS[seed % FAMILIAR_VARIANTS.length],
    color: normalizedColor ?? DEFAULT_PALETTE[seed % DEFAULT_PALETTE.length],
    accent: FAMILIAR_ACCENTS[Math.floor(seed / 3) % FAMILIAR_ACCENTS.length],
    seed: seed % 10_000,
  };
}

export function sanitizeFamiliar(
  value: Partial<FamiliarConfig> | null | undefined,
  fallbackName: string,
  fallbackColor?: string | null,
): FamiliarConfig {
  const fallback = createGeneratedFamiliar(fallbackName, fallbackColor);
  return {
    variant: FAMILIAR_VARIANTS.includes(value?.variant as FamiliarVariant)
      ? (value?.variant as FamiliarVariant)
      : fallback.variant,
    color: value?.color || fallbackColor ? normalizeFamiliarColor(value?.color ?? fallbackColor) : fallback.color,
    accent: FAMILIAR_ACCENTS.includes(value?.accent as FamiliarAccent)
      ? (value?.accent as FamiliarAccent)
      : fallback.accent,
    seed: typeof value?.seed === 'number' && Number.isFinite(value.seed)
      ? Math.max(0, Math.floor(value.seed))
      : fallback.seed,
  };
}

export function getFamiliarStorageKey(profileId: string): string {
  return `${STORAGE_KEY_PREFIX}${profileId}`;
}

export function loadStoredFamiliar(profileId: string | null): FamiliarConfig | null {
  if (!profileId || typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(getFamiliarStorageKey(profileId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<FamiliarConfig>;
    return sanitizeFamiliar(parsed, profileId);
  } catch {
    return null;
  }
}

export function saveStoredFamiliar(profileId: string | null, familiar: FamiliarConfig): void {
  if (!profileId || typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(getFamiliarStorageKey(profileId), JSON.stringify(familiar));
  } catch {
    // Ignore storage failures; session joining should still work.
  }
}

export type SessionRole = 'host' | 'listener' | 'guest';

export interface RoomPosition {
  xPct: number;
  yPct: number;
}

export const STAGE_HOST_POSITION: RoomPosition = { xPct: 50, yPct: 22 };

const CROWD_ROW_Y_PCTS: Record<1 | 2 | 3, number[]> = {
  1: [66],
  2: [56, 80],
  3: [50, 68, 84],
};
const CROWD_X_INSET = 10;

function pickRowCount(totalCrowd: number): 1 | 2 | 3 {
  if (totalCrowd <= 4) return 1;
  if (totalCrowd <= 8) return 2;
  return 3;
}

export interface BeatAnchor {
  bpm: number | null;
  positionMs: number;
  receivedAt: number;
  isPlaying: boolean;
  trackId: string | null;
}

export const FALLBACK_BOB_PERIOD_MS = 2600;
export const BOB_AMPLITUDE_CROWD_PX = 3;
export const BOB_AMPLITUDE_HOST_PX = 4;

export function computeBeatPhase(anchor: BeatAnchor | null, now: number): number {
  if (!anchor) return 0;
  const elapsed = anchor.isPlaying
    ? Math.max(0, anchor.positionMs + (now - anchor.receivedAt))
    : Math.max(0, now - anchor.receivedAt);
  const period =
    anchor.bpm && anchor.bpm > 0 && Number.isFinite(anchor.bpm)
      ? 60_000 / anchor.bpm
      : FALLBACK_BOB_PERIOD_MS;
  const phase = (elapsed % period) / period;
  return phase >= 0 ? phase : phase + 1;
}

export function computeRoomPosition(
  participant: { user_id: string; role: SessionRole },
  indexAmongCrowd: number,
  totalCrowd: number,
): RoomPosition {
  if (participant.role === 'host') {
    return { ...STAGE_HOST_POSITION };
  }
  const safeTotal = Math.max(1, totalCrowd);
  const rows = pickRowCount(safeTotal);
  const perRow = Math.ceil(safeTotal / rows);
  const row = Math.min(rows - 1, Math.floor(indexAmongCrowd / perRow));
  const col = indexAmongCrowd % perRow;
  const innerWidth = 100 - 2 * CROWD_X_INSET;
  const colCenter =
    perRow === 1 ? 50 : CROWD_X_INSET + (col + 0.5) * (innerWidth / perRow);
  const yBase = CROWD_ROW_Y_PCTS[rows][row];
  const seed = hashString(participant.user_id);
  const xJitter = ((seed % 100) / 100 - 0.5) * 6;
  const yJitter = (((seed >> 8) % 100) / 100 - 0.5) * 4;
  const xPct = Math.max(6, Math.min(94, colCenter + xJitter));
  const yPct = Math.max(50, Math.min(96, yBase + yJitter));
  return { xPct, yPct };
}
