/**
 * Beat Tiles — album-art visualizer.
 *
 * The current cover is split into a grid of 3D box tiles. Each tile tracks a band
 * of the spectrum, and every onset launches a "pop" that ripples outward from the
 * centre. Tiles are boxes with glowing palette-coloured sides; strong beats flip
 * some of them (flip-dot style) and the sides shift hue with the spectrum. The grid
 * sits over a reflective floor + a soft blurred-cover backdrop, the camera drifts,
 * and the grid breathes gently when the music is quiet. The album art still
 * reassembles on the box fronts, so it stays recognizable.
 */
import { useRef, useMemo, useState, useEffect } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { Reflector } from 'three/examples/jsm/objects/Reflector.js';
import { AudioReactiveEffects, FrameScheduler, getAudioData, useArtworkPalette, useAudioAnalyser, type VisualizerProps } from '@familiar/visualizer-sdk';
const isMobile = () => window.matchMedia('(max-width: 768px)').matches;

const mobile = isMobile();
const GRID = mobile ? 6 : 10;
const COVER = 5; // world size of the cover

const FOV = 55; // vertical, degrees
const REST_DISTANCE = 7; // the camera's distance in a wide frame
const DOLLY = 0.5; // how far a big beat pulls the camera in

/**
 * How far back the camera sits so the whole grid's width fits the frame (2026-11-08).
 *
 * The field of view is vertical, so a tall frame sees less width. At 7 units a phone in
 * portrait (aspect ~0.46) saw about two thirds of the grid, and the outer columns were cut
 * off. Backing off by the frame's aspect keeps every tile in view with a margin, plus room
 * for a popped tile to come forward and for the beat's dolly. A wide frame never comes
 * closer than ``REST_DISTANCE``, so the Mac looks as it always has.
 */
export function fitDistance(aspect: number): number {
  const halfWidth = COVER / 2 + 0.25; // the outer tiles' edges, and a margin
  const popAllowance = 1.3; // a popped edge tile comes forward and looks wider
  const tan = Math.tan(THREE.MathUtils.degToRad(FOV / 2));
  const fit = halfWidth / (tan * Math.max(aspect, 0.1)) + popAllowance + DOLLY;
  return Math.max(REST_DISTANCE, fit);
}

// Ripple timing (seconds).
const RIPPLE_DELAY = 0.34; // extra delay for the farthest tile (wave travel time)
const RIPPLE_W = 0.32; // width of each pop pulse
const RIPPLE_MAXAGE = RIPPLE_DELAY + RIPPLE_W + 0.05;

// Side-face shader: holographic foil (view-angle fresnel hue shift) embossed by the
// album cover (normal perturbed from cover luminance). Brightness rides uGlow.
const SIDE_VERT = /* glsl */ `
  varying vec3 vNormalV;
  varying vec3 vViewDir;
  varying vec2 vUv;
  void main() {
    vUv = uv;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vNormalV = normalize(normalMatrix * normal);
    vViewDir = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`;

const SIDE_FRAG = /* glsl */ `
  precision highp float;
  uniform float uHue;
  uniform float uGlow;
  uniform float uTime;
  uniform sampler2D uCover;
  uniform vec2 uUvOffset;
  uniform float uUvScale;
  uniform float uHasCover;
  varying vec3 vNormalV;
  varying vec3 vViewDir;
  varying vec2 vUv;

  vec3 hsl2rgb(float h, float s, float l) {
    vec3 r = clamp(abs(mod(h * 6.0 + vec3(0.0, 4.0, 2.0), 6.0) - 3.0) - 1.0, 0.0, 1.0);
    return l + s * (r - 0.5) * (1.0 - abs(2.0 * l - 1.0));
  }
  float lum(vec3 c) { return dot(c, vec3(0.299, 0.587, 0.114)); }

  void main() {
    vec2 cuv = uUvOffset + clamp(vUv, 0.0, 1.0) * uUvScale;
    vec3 N = normalize(vNormalV);
    if (uHasCover > 0.5) {
      // Emboss: perturb the normal by the cover's luminance gradient.
      float e = uUvScale * 0.05;
      float hL = lum(texture2D(uCover, cuv - vec2(e, 0.0)).rgb);
      float hR = lum(texture2D(uCover, cuv + vec2(e, 0.0)).rgb);
      float hD = lum(texture2D(uCover, cuv - vec2(0.0, e)).rgb);
      float hU = lum(texture2D(uCover, cuv + vec2(0.0, e)).rgb);
      N = normalize(N + vec3(hL - hR, hD - hU, 0.0) * 1.6);
    }
    vec3 V = normalize(vViewDir);
    float fres = pow(1.0 - max(dot(N, V), 0.0), 3.0); // grazing-angle sheen
    vec3 L = normalize(vec3(0.4, 0.6, 0.85));
    float relief = 0.72 + 0.45 * max(dot(N, L), 0.0); // relief catches the light
    vec3 base = hsl2rgb(fract(uHue), 0.85, 0.5);
    vec3 irid = hsl2rgb(fract(uHue + fres * 0.55 + uTime * 0.04), 0.95, 0.6);
    vec3 col = mix(base, irid, fres) * relief * uGlow;
    gl_FragColor = vec4(col, 1.0);
  }
`;

interface Ripple {
  t0: number;
  strength: number;
}

interface Tile {
  geometry: THREE.BoxGeometry;
  front: THREE.MeshBasicMaterial;
  side: THREE.ShaderMaterial;
  materials: THREE.Material[];
  x: number;
  y: number;
  dist: number; // 0..1 from centre
  phase: number;
  hue: number; // side base hue
  flip: number; // current flip angle
  flipTarget: number;
  rest: THREE.Color | null; // the front's colour at rest when there is no cover
}

function TilesScene({
  tex,
  backdrop,
  palette,
  coverlessHueValue,
}: {
  tex: THREE.Texture | null;
  backdrop: THREE.Texture | null;
  palette: string[];
  coverlessHueValue: number;
}) {
  useAudioAnalyser(true);
  const meshRefs = useRef<(THREE.Mesh | null)[]>([]);
  const ripples = useRef<Ripple[]>([]);
  const energyEMA = useRef(0);

  const tiles = useMemo<Tile[]>(() => {
    const out: Tile[] = [];
    const size = COVER / GRID;
    const depth = size * 0.9; // near-cube so the colour side-faces are full squares
    const baseHSL = { h: 0.78, s: 0.7, l: 0.5 };
    if (tex) new THREE.Color(palette[0] ?? '#7c3aed').getHSL(baseHSL);
    else baseHSL.h = coverlessHueValue;
    for (let row = 0; row < GRID; row++) {
      for (let col = 0; col < GRID; col++) {
        const geometry = new THREE.BoxGeometry(size * 0.94, size * 0.94, depth);
        // Map the +Z (front) AND -Z (back) faces to this tile's sub-rect of the cover.
        // Rows count down from the top, but the texture's v counts up from the bottom
        // (flipY), so row 0 takes the top strip: until 1.7 the cover was drawn with its
        // rows in reverse order.
        //
        // so a flipped tile still shows the art. The back is mirrored in U so it reads
        // correctly after a 180° flip. The 4 thin edge faces stay palette-coloured.
        const uv = geometry.attributes.uv as THREE.BufferAttribute;
        for (let k = 16; k < 20; k++) {
          const ux = uv.getX(k);
          const uy = uv.getY(k);
          uv.setXY(k, (col + ux) / GRID, (GRID - 1 - row + uy) / GRID);
        }
        for (let k = 20; k < 24; k++) {
          const ux = uv.getX(k);
          const uy = uv.getY(k);
          uv.setXY(k, (col + (1 - ux)) / GRID, (GRID - 1 - row + uy) / GRID);
        }
        uv.needsUpdate = true;

        const dist = Math.min(1, Math.hypot(col - (GRID - 1) / 2, row - (GRID - 1) / 2) / (GRID / 2));
        const rest = tex ? null : coverlessTileColor(baseHSL.h, col, row, dist);
        const front = new THREE.MeshBasicMaterial({
          map: tex ?? null,
          color: rest ? rest.clone() : new THREE.Color(1, 1, 1),
          toneMapped: false,
        });
        // Without a cover the side faces stay near the album's hue rather than sweeping
        // the whole wheel, so a flipped tile reads as part of the same picture.
        const hue = (baseHSL.h + dist * (tex ? 0.42 : 0.12)) % 1;
        const side = new THREE.ShaderMaterial({
          uniforms: {
            uHue: { value: hue },
            uGlow: { value: 0.42 },
            uTime: { value: 0 },
            uCover: { value: tex },
            uUvOffset: { value: new THREE.Vector2(col / GRID, (GRID - 1 - row) / GRID) },
            uUvScale: { value: 1 / GRID },
            uHasCover: { value: tex ? 1 : 0 },
          },
          vertexShader: SIDE_VERT,
          fragmentShader: SIDE_FRAG,
        });
        // Box face order: px, nx, py, ny, pz(front), nz(back). Art on front + back,
        // palette glow on the 4 thin edges.
        const materials = [side, side, side, side, front, front];

        const x = (col - (GRID - 1) / 2) * size;
        const y = ((GRID - 1) / 2 - row) * size;
        out.push({ geometry, front, side, materials, x, y, dist, phase: Math.random(), hue, flip: 0, flipTarget: 0, rest });
      }
    }
    return out;
  }, [tex, palette, coverlessHueValue]);

  useEffect(() => {
    return () => {
      for (const t of tiles) {
        t.geometry.dispose();
        t.front.dispose();
        t.side.dispose();
      }
    };
  }, [tiles]);

  // Reflective floor (desktop only — the reflection costs an extra render pass).
  const reflector = useMemo<Reflector | null>(() => {
    if (mobile) return null;
    const r = new Reflector(new THREE.PlaneGeometry(24, 24), {
      color: 0x141420,
      textureWidth: 1024,
      textureHeight: 1024,
    });
    r.rotation.x = -Math.PI / 2;
    r.position.y = -COVER * 0.6;
    return r;
  }, []);
  useEffect(() => () => reflector?.geometry.dispose(), [reflector]);

  useFrame((state, delta) => {
    const d = Math.min(delta, 0.05);
    const elapsed = state.clock.elapsedTime;
    const audio = getAudioData();
    const fd = audio?.frequencyData;
    const bass = audio?.bass ?? 0;
    const beat = audio?.beat ?? 0;

    // Ripples: spawn on each onset, cull when expired.
    ripples.current = ripples.current.filter((r) => elapsed - r.t0 < RIPPLE_MAXAGE);
    let strongOnset = false;
    if (audio?.onset) {
      const strength = 0.7 + bass * 0.8;
      ripples.current.push({ t0: elapsed, strength });
      if (ripples.current.length > 4) ripples.current.shift();
      strongOnset = strength > 1.1;
    }

    // Idle "breathing" amplitude — strong when quiet, ~0 when loud.
    energyEMA.current += 0.05 * (bass + beat - energyEMA.current);
    const idleAmp = Math.max(0, 0.25 - energyEMA.current * 1.5);

    for (let i = 0; i < tiles.length; i++) {
      const mesh = meshRefs.current[i];
      if (!mesh) continue;
      const t = tiles[i];

      // Per-tile spectrum band (centre = lows, edges = highs).
      let energy = 0;
      if (fd && fd.length) {
        energy = fd[Math.floor(t.dist * (fd.length - 1) * 0.7)] / 255;
      }

      // Sum the ripple pulses — the wavefront reaches farther tiles later.
      let pop = 0;
      for (const r of ripples.current) {
        const age = elapsed - r.t0 - t.dist * RIPPLE_DELAY;
        if (age > 0 && age < RIPPLE_W) pop += r.strength * Math.sin((age / RIPPLE_W) * Math.PI);
      }

      pop = Math.min(pop, 1.6);
      const idle = idleAmp * Math.sin(elapsed * 0.9 + t.dist * 5.0);
      // Ripple is the main driver of the glow; the spectrum band is a gentle bias
      // (so it's not just the bass-lit centre that glows).
      const targetZ = energy * 0.28 + pop * 1.6 + idle;
      mesh.position.z += (targetZ - mesh.position.z) * Math.min(1, d * 16);
      const z = Math.max(0, mesh.position.z);

      // Small extra extrude on pop (they're already cubes).
      mesh.scale.z = 1 + Math.min(z, 1.5) * 0.5;

      // Flips on strong beats: a quarter turn lands on a colour side-face, a half
      // turn lands on the (art) back. Ease toward the target.
      if (strongOnset && Math.random() < 0.25) {
        t.flipTarget += Math.random() < 0.55 ? Math.PI / 2 : Math.PI;
      }
      t.flip += (t.flipTarget - t.flip) * Math.min(1, d * 8);
      mesh.rotation.y = t.flip;
      mesh.rotation.x = z * 0.18 * Math.sin(t.phase * 6.28);

      // Brightness is CLAMPED so a screenful of popped tiles can never wash the frame
      // out. The caps stay under 1: the side shader's colour is already near white at
      // full glow, and on a phone the popped tiles fill most of the screen. A popped
      // side (up to 0.9) still crosses the bloom threshold, so pops glow and rest doesn't.
      // (1.05 and 1.5 turned the whole frame white on every beat, glow or no glow.)
      // Without a cover the front keeps its own shade and a pop lifts it, up to about 2.6
      // times its rest. (Until 1.7 this set every coverless tile to the same flat grey.)
      if (t.rest) t.front.color.copy(t.rest).multiplyScalar(1 + Math.min(z, 1) * 1.6);
      else t.front.color.setScalar(THREE.MathUtils.clamp(0.5 + z * 0.25, 0.5, 0.9));
      t.side.uniforms.uGlow.value = THREE.MathUtils.clamp(0.35 + z * 0.4, 0.3, 0.9);
      t.side.uniforms.uTime.value = elapsed;
    }

    // Camera drift + dolly-in on big beats; idle parallax keeps it alive.
    const cam = state.camera;
    cam.position.x = Math.sin(elapsed * 0.12) * 0.7;
    cam.position.y = 0.4 + Math.sin(elapsed * 0.09) * 0.4;
    cam.position.z = fitDistance(state.size.width / Math.max(state.size.height, 1)) - beat * DOLLY;
    cam.lookAt(0, 0, 0);
  });

  return (
    <>
      <color attach="background" args={['#060608']} />
      {backdrop && (
        <mesh position={[0, 0, -6]}>
          <planeGeometry args={[18, 18]} />
          <meshBasicMaterial map={backdrop} color={0x484848} depthWrite={false} />
        </mesh>
      )}
      {reflector && <primitive object={reflector} />}
      <group>
        {tiles.map((t, i) => (
          <mesh
            key={i}
            ref={(el) => (meshRefs.current[i] = el)}
            position={[t.x, t.y, 0]}
            geometry={t.geometry}
            material={t.materials}
          />
        ))}
      </group>
      <AudioReactiveEffects
        enableBloom
        enableVignette
        // Tuned on rendered frames at phone width (1.7 builds 74-75): 0.45 with a 0.6
        // threshold washed the frame white on every beat, 0.2 with 0.85 never glowed at
        // all. This lets a popped tile's bright edge halo while the cover holds.
        bloomIntensity={mobile ? 0.25 : 0.35}
        bloomThreshold={0.75}
        bloomRadius={0.45}
        bloomBassBoost={0.1}
        halfResolution={mobile}
      />
      <FrameScheduler />
    </>
  );
}

/**
 * A coverless album's hue, from its name, so each album looks like itself rather than like
 * every other album without a cover. FNV-1a: stable across sessions and devices.
 */
export function coverlessHue(seed: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0) / 0x100000000;
}

/**
 * A tile's resting colour when there is no cover: a dark shade of the album's hue, a little
 * lighter toward the centre and drifting in hue across the diagonal, so the grid reads as one
 * picture. Kept dark so a beat has room to brighten it without washing the frame out.
 */
export function coverlessTileColor(hue: number, col: number, row: number, dist: number): THREE.Color {
  const h = (hue + ((col - row) / GRID) * 0.06 + 1) % 1;
  return new THREE.Color().setHSL(h, 0.5, 0.11 + 0.1 * (1 - dist), THREE.SRGBColorSpace);
}

// A coverless backdrop: the album's hue as a dim glow behind the grid.
function makeCoverlessBackdrop(hue: number): THREE.CanvasTexture | null {
  try {
    const S = 256;
    const c = document.createElement('canvas');
    c.width = c.height = S;
    const ctx = c.getContext('2d');
    if (!ctx) return null;
    const deg = Math.round(hue * 360);
    const g = ctx.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S * 0.7);
    g.addColorStop(0, `hsl(${deg} 45% 14%)`);
    g.addColorStop(1, 'hsl(0 0% 3%)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, S, S);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  } catch {
    return null;
  }
}

// Build a soft, blurred + dimmed backdrop from the cover image.
function makeBackdrop(img: HTMLImageElement): THREE.CanvasTexture | null {
  try {
    const S = 512;
    const c = document.createElement('canvas');
    c.width = c.height = S;
    const ctx = c.getContext('2d');
    if (!ctx) return null;
    ctx.filter = 'blur(26px)';
    ctx.drawImage(img, -48, -48, S + 96, S + 96); // overscan so the blur fills the edges
    ctx.filter = 'none';
    // Darken heavily (works for light covers too) so the backdrop never overpowers.
    const g = ctx.createRadialGradient(S / 2, S / 2, 60, S / 2, S / 2, S * 0.72);
    g.addColorStop(0, 'rgba(6,6,9,0.74)');
    g.addColorStop(1, 'rgba(6,6,9,0.97)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, S, S);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  } catch {
    return null;
  }
}

export function BeatTiles({ artworkUrl, track }: VisualizerProps) {
  const palette = useArtworkPalette(artworkUrl);
  const seed = track ? track.album || track.artist || track.title || track.id : '';
  const hue = useMemo(() => coverlessHue(seed), [seed]);
  const [tex, setTex] = useState<THREE.Texture | null>(null);
  const [backdrop, setBackdrop] = useState<THREE.Texture | null>(null);

  useEffect(() => {
    if (!artworkUrl) {
      setTex(null);
      setBackdrop(null);
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
        const img = t.image as HTMLImageElement | undefined;
        if (img) setBackdrop(makeBackdrop(img));
      },
      undefined,
      () => {
        setTex(null);
        setBackdrop(null);
      }
    );
    return () => {
      cancelled = true;
    };
  }, [artworkUrl]);

  // Shown while there is no cover: before one loads, and for an album that has none.
  const coverlessBackdrop = useMemo(() => (tex ? null : makeCoverlessBackdrop(hue)), [tex, hue]);
  useEffect(() => () => coverlessBackdrop?.dispose(), [coverlessBackdrop]);

  return (
    <div className="w-full h-full">
      <Canvas camera={{ position: [0, 0.4, REST_DISTANCE], fov: FOV }} gl={{ antialias: !mobile, alpha: false }}>
        <TilesScene tex={tex} backdrop={backdrop ?? coverlessBackdrop} palette={palette} coverlessHueValue={hue} />
      </Canvas>
    </div>
  );
}

export default BeatTiles;
