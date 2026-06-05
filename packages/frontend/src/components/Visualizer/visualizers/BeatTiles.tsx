/**
 * Beat Tiles — album-art visualizer.
 *
 * The current cover is split into a grid of 3D tiles. Each tile tracks a band of
 * the spectrum (bass near the centre, treble toward the edges) and every onset
 * gives all tiles a synchronized "pop" outward; they then settle back and the
 * cover reassembles. The image stays fully recognizable (unlike the old
 * kaleidoscope) while reacting tightly to the music.
 */
import { useRef, useMemo, useState, useEffect } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { type VisualizerProps } from '../types';
import { useAudioAnalyser, getAudioData, useArtworkPalette } from '../hooks';
import { AudioReactiveEffects } from '../effects/AudioReactiveEffects';
import { FrameScheduler } from '../effects/FrameScheduler';
import { isMobile } from '../../../utils/platform';

const mobile = isMobile();
const GRID = mobile ? 6 : 10;
const COVER = 5; // world size of the cover

interface Tile {
  geometry: THREE.PlaneGeometry;
  material: THREE.MeshBasicMaterial;
  x: number;
  y: number;
  bin: number; // frequency bin this tile reacts to
  phase: number; // per-tile randomness for the pop
}

function TilesScene({ tex, palette }: { tex: THREE.Texture | null; palette: string[] }) {
  useAudioAnalyser(true);
  const meshRefs = useRef<(THREE.Mesh | null)[]>([]);

  const tiles = useMemo<Tile[]>(() => {
    const out: Tile[] = [];
    const size = COVER / GRID;
    const fallback = new THREE.Color(palette[0] ?? '#7c3aed');
    for (let row = 0; row < GRID; row++) {
      for (let col = 0; col < GRID; col++) {
        const geometry = new THREE.PlaneGeometry(size * 0.96, size * 0.96);
        // Remap this tile's UVs to its sub-rectangle of the cover.
        const uv = geometry.attributes.uv as THREE.BufferAttribute;
        for (let k = 0; k < uv.count; k++) {
          const ux = uv.getX(k);
          const uy = uv.getY(k);
          uv.setXY(k, (col + ux) / GRID, (row + uy) / GRID);
        }
        uv.needsUpdate = true;

        const material = new THREE.MeshBasicMaterial({
          map: tex ?? null,
          color: tex ? new THREE.Color(1, 1, 1) : fallback,
          toneMapped: false,
        });

        const x = (col - (GRID - 1) / 2) * size;
        const y = ((GRID - 1) / 2 - row) * size;
        // Distance from centre 0..1 → bass at centre, treble at edges.
        const dist = Math.min(1, Math.hypot(col - (GRID - 1) / 2, row - (GRID - 1) / 2) / (GRID / 2));
        const bin = dist;
        out.push({ geometry, material, x, y, bin, phase: Math.random() });
      }
    }
    return out;
  }, [tex, palette]);

  // Dispose geometries/materials when the set changes.
  useEffect(() => {
    return () => {
      for (const t of tiles) {
        t.geometry.dispose();
        t.material.dispose();
      }
    };
  }, [tiles]);

  useFrame((_, delta) => {
    const d = Math.min(delta, 0.05);
    const audio = getAudioData();
    const fd = audio?.frequencyData;
    const bass = audio?.bass ?? 0;
    const beat = audio?.beat ?? 0;

    for (let i = 0; i < tiles.length; i++) {
      const mesh = meshRefs.current[i];
      if (!mesh) continue;
      const t = tiles[i];

      // Sample the spectrum for this tile (centre=lows, edges=highs).
      let energy = 0;
      if (fd && fd.length) {
        const idx = Math.floor(t.bin * (fd.length - 1) * 0.7);
        energy = fd[idx] / 255;
      }

      const pop = beat * (0.7 + t.phase * 0.9) * (0.6 + bass * 1.4);
      const targetZ = energy * 1.6 + pop * 2.1;
      mesh.position.z += (targetZ - mesh.position.z) * Math.min(1, d * 16);

      // Brighten popped tiles for bloom; tilt slightly with height.
      const b = 1 + mesh.position.z * 0.7;
      (mesh.material as THREE.MeshBasicMaterial).color.setScalar(t.material.map ? b : 1);
      if (!t.material.map) (mesh.material as THREE.MeshBasicMaterial).color.lerp(new THREE.Color(palette[i % palette.length] ?? '#7c3aed'), 0.02);
      mesh.rotation.x = mesh.position.z * 0.25 * Math.sin(t.phase * 6.28);
      mesh.rotation.y = mesh.position.z * 0.25 * Math.cos(t.phase * 6.28);
    }
  });

  return (
    <>
      <color attach="background" args={['#070709']} />
      <group>
        {tiles.map((t, i) => (
          <mesh
            key={i}
            ref={(el) => (meshRefs.current[i] = el)}
            position={[t.x, t.y, 0]}
            geometry={t.geometry}
            material={t.material}
          />
        ))}
      </group>
      <AudioReactiveEffects
        enableBloom
        enableVignette
        bloomIntensity={mobile ? 0.6 : 0.9}
        bloomThreshold={0.7}
        bloomRadius={0.5}
        halfResolution={mobile}
      />
      <FrameScheduler />
    </>
  );
}

export function BeatTiles({ artworkUrl }: VisualizerProps) {
  const palette = useArtworkPalette(artworkUrl);
  const [tex, setTex] = useState<THREE.Texture | null>(null);

  useEffect(() => {
    if (!artworkUrl) {
      setTex(null);
      return;
    }
    const loader = new THREE.TextureLoader();
    loader.setCrossOrigin('anonymous');
    let cancelled = false;
    loader.load(
      artworkUrl,
      (t) => {
        if (cancelled) {
          t.dispose();
          return;
        }
        t.colorSpace = THREE.SRGBColorSpace;
        setTex(t);
      },
      undefined,
      () => setTex(null)
    );
    return () => {
      cancelled = true;
    };
  }, [artworkUrl]);

  return (
    <div className="w-full h-full">
      <Canvas camera={{ position: [0, 0, 7], fov: 55 }} gl={{ antialias: !mobile, alpha: false }}>
        <TilesScene tex={tex} palette={palette} />
      </Canvas>
    </div>
  );
}

export default BeatTiles;
