/**
 * LyricWordField — ambient 3D word particles drifting behind the lyrics.
 *
 * A revival of the old LyricStorm "WordParticles" effect: the song's own words
 * float through a dark 3D space, drifting in from the edges, faded and slowly
 * tumbling, gently reacting to the music (drift speed/spawn rate with bass,
 * shimmer with treble) with a soft bloom. It is purely a *background* layer —
 * the readable, synced lyric column is rendered as crisp DOM on top of this.
 *
 * Lives in its own file (a WebGL <Canvas>) so it can be mocked out of jsdom
 * unit tests for the DOM lyric column.
 */
import { useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Text } from '@react-three/drei';
import * as THREE from 'three';
import type { VisualizerProps } from '../types';
import { useAudioAnalyser, getAudioData, useArtworkPalette } from '../hooks';
import { AudioReactiveEffects } from '../effects/AudioReactiveEffects';
import { FrameScheduler } from '../effects/FrameScheduler';
import { isMobile } from '../../../utils/platform';

const mobile = isMobile();
const MAX_WORDS = mobile ? 7 : 16;
const SPAWN_BASE = mobile ? 0.03 : 0.06;

interface FloatingWord {
  id: number;
  text: string;
  position: THREE.Vector3;
  velocity: THREE.Vector3;
  rotation: THREE.Euler;
  rotationSpeed: THREE.Vector3;
  scale: number;
  baseOpacity: number;
  color: THREE.Color;
  life: number;
  maxLife: number;
  shimmerPhase: number;
}

let wordIdCounter = 0;

/** Extract a clean, de-duplicated pool of words to float. */
function useWordPool(lyrics: VisualizerProps['lyrics'], track: VisualizerProps['track']): string[] {
  return useMemo(() => {
    const source =
      lyrics && lyrics.length > 0
        ? lyrics.map((l) => l.text).join(' ')
        : `${track?.title ?? ''} ${track?.artist ?? ''}`;
    const words = source
      .split(/\s+/)
      .map((w) => w.replace(/[^\p{L}\p{N}']/gu, ''))
      .filter((w) => w.length > 1);
    return [...new Set(words)];
  }, [lyrics, track]);
}

function WordParticles({ pool, palette }: { pool: string[]; palette: string[] }) {
  const groupRef = useRef<THREE.Group>(null);
  useAudioAnalyser(true);
  const [render, setRender] = useState<FloatingWord[]>([]);
  const wordsRef = useRef<FloatingWord[]>([]);
  const { viewport } = useThree();
  const timeRef = useRef(0);
  const frameRef = useRef(0);

  const colors = useMemo(() => palette.map((c) => new THREE.Color(c)), [palette]);

  useFrame((_, delta) => {
    // Guard against huge dt after a tab is backgrounded.
    const dt = Math.min(delta, 0.05);
    timeRef.current += dt;

    const audio = getAudioData();
    const bass = audio?.bass ?? 0;
    const mid = audio?.mid ?? 0;
    const treble = audio?.treble ?? 0;

    // Spawn ambient words from a random edge, more often on bass.
    if (pool.length > 0 && wordsRef.current.length < MAX_WORDS && Math.random() < SPAWN_BASE + bass * 0.14) {
      const hw = viewport.width / 2 + 2;
      const hh = viewport.height / 2 + 2;
      const edge = Math.floor(Math.random() * 4);
      let x = 0;
      let y = 0;
      let vx = 0;
      let vy = 0;
      switch (edge) {
        case 0: x = (Math.random() - 0.5) * hw * 2; y = -hh; vx = (Math.random() - 0.5) * 0.3; vy = 0.3 + Math.random() * 0.4; break;
        case 1: x = hw; y = (Math.random() - 0.5) * hh * 2; vx = -(0.3 + Math.random() * 0.4); vy = (Math.random() - 0.5) * 0.3; break;
        case 2: x = (Math.random() - 0.5) * hw * 2; y = hh; vx = (Math.random() - 0.5) * 0.3; vy = -(0.3 + Math.random() * 0.4); break;
        default: x = -hw; y = (Math.random() - 0.5) * hh * 2; vx = 0.3 + Math.random() * 0.4; vy = (Math.random() - 0.5) * 0.3;
      }
      wordsRef.current.push({
        id: ++wordIdCounter,
        text: pool[Math.floor(Math.random() * pool.length)],
        position: new THREE.Vector3(x, y, -9 + Math.random() * 5),
        velocity: new THREE.Vector3(vx, vy, 0),
        rotation: new THREE.Euler((Math.random() - 0.5) * 0.4, (Math.random() - 0.5) * 0.4, (Math.random() - 0.5) * 0.3),
        rotationSpeed: new THREE.Vector3((Math.random() - 0.5) * 0.06, (Math.random() - 0.5) * 0.06, (Math.random() - 0.5) * 0.05),
        scale: 0.5 + Math.random() * 0.7,
        baseOpacity: 0.16 + Math.random() * 0.2,
        color: colors[Math.floor(Math.random() * Math.max(1, colors.length))] ?? new THREE.Color('#a855f7'),
        life: 0,
        maxLife: 9 + Math.random() * 6,
        shimmerPhase: Math.random() * Math.PI * 2,
      });
    }

    // Advance physics + fade, recycle expired words.
    const speed = 1 + bass * 1.4;
    wordsRef.current = wordsRef.current.filter((w) => {
      w.life += dt;
      w.position.addScaledVector(w.velocity, dt * speed);
      w.rotation.x += w.rotationSpeed.x * dt * (1 + mid);
      w.rotation.y += w.rotationSpeed.y * dt * (1 + mid);
      w.rotation.z += w.rotationSpeed.z * dt;
      return w.life < w.maxLife;
    });

    // Sync to React a few times a second (cheap for ~16 words).
    frameRef.current++;
    if (frameRef.current % 6 === 0) {
      setRender(wordsRef.current.map((w) => ({ ...w })));
    }
    void treble;
  });

  const now = timeRef.current;
  return (
    <group ref={groupRef}>
      {render.map((w) => {
        const fadeIn = Math.min(1, w.life / 1.4);
        const fadeOut = Math.min(1, Math.max(0, (w.maxLife - w.life) / 2));
        const shimmer = 0.85 + 0.15 * Math.sin(now * 1.6 + w.shimmerPhase);
        const opacity = w.baseOpacity * fadeIn * fadeOut * shimmer;
        return (
          <Text
            key={w.id}
            position={[w.position.x, w.position.y, w.position.z]}
            rotation={[w.rotation.x, w.rotation.y, w.rotation.z]}
            fontSize={w.scale}
            color={w.color}
            anchorX="center"
            anchorY="middle"
            fillOpacity={opacity}
          >
            {w.text}
          </Text>
        );
      })}
    </group>
  );
}

function FieldScene({ pool, palette }: { pool: string[]; palette: string[] }) {
  useAudioAnalyser(true);
  return (
    <>
      <fog attach="fog" args={['#050308', 16, 60]} />
      <ambientLight intensity={0.4} />
      <WordParticles pool={pool} palette={palette} />
      <AudioReactiveEffects
        enableBloom
        enableVignette={false}
        bloomIntensity={mobile ? 0.5 : 0.8}
        bloomThreshold={0.35}
        bloomRadius={0.6}
        bloomBassBoost={0.6}
        halfResolution={mobile}
      />
      <FrameScheduler />
    </>
  );
}

export function LyricWordField({ lyrics, track, artworkUrl }: Pick<VisualizerProps, 'lyrics' | 'track' | 'artworkUrl'>) {
  const palette = useArtworkPalette(artworkUrl);
  const pool = useWordPool(lyrics, track);

  // Nothing to float — let the base aurora show through.
  if (pool.length === 0) return null;

  return (
    <Canvas
      className="absolute inset-0"
      camera={{ position: [0, 0, 15], fov: 50 }}
      gl={{ antialias: !mobile, alpha: true, powerPreference: 'high-performance' }}
      dpr={mobile ? [1, 1] : [1, 2]}
      frameloop={mobile ? 'demand' : 'always'}
    >
      <FieldScene pool={pool} palette={palette} />
    </Canvas>
  );
}

export default LyricWordField;
