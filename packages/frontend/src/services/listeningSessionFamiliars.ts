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

