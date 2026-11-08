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
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { Reflector } from 'three/examples/jsm/objects/Reflector.js';
import { HDRLoader } from 'three/examples/jsm/loaders/HDRLoader.js';
import { AudioReactiveEffects, FrameScheduler, getAudioData, useArtworkPalette, useAudioAnalyser, type VisualizerProps } from '@familiar/visualizer-sdk';
const isMobile = () => window.matchMedia('(max-width: 768px)').matches;

const mobile = isMobile();
const GRID = mobile ? 6 : 10;
const COVER = 5; // world size of the cover

/**
 * **What glows is chosen, not found.** The bloom picks every pixel brighter than its
 * threshold, and a cover's brightness is whatever the album's art is. So a low threshold
 * bloomed white covers across the whole frame (1.7 builds 74-75) and a high one never
 * reached a dark cover (builds 76-78). Now the threshold sits at 1 and stays there, a cover
 * is capped at 0.9 so it never reaches it, and only a pop is driven past 1: a popped tile's
 * sides, and a coverless tile's face. The bloom's strength no longer has to guess.
 */
// Dialled in by eye on an iPhone 13 with the temporary tuner (2026-11-08): bloom 1.32,
// threshold 0.82, pop glow 0.99. Covers are capped at 0.9, so the brightest parts of a
// cover can glow faintly on a pop; the rest of it never reaches the threshold.
const BLOOM_THRESHOLD = 0.62;
const BLOOM_STRENGTH = 0.24;
const COVERLESS_BLOOM_THRESHOLD = 1.1;

// Dialled in on the phone with a temporary on-screen tuner (2026-11-08): how far a popped tile's
// glow is driven, and the exposure that lights the textured coverless tiles.
const tuning = { popGlow: 0.64, exposure: 1.66 } as const;

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

// Front-face shader for a coverless album: a lit block rather than a flat swatch. A soft
// falloff across the face (lit from the upper left), a bevelled rim that catches the light,
// and a sheen in the album's hue that moves as the camera drifts. uGlow is the pop: at rest
// the face stays dark, and a pop drives it past 1 so the bloom picks it up.
const COVERLESS_FRAG = /* glsl */ `
  precision highp float;
  uniform vec3 uColor;
  uniform vec3 uSheen;
  uniform float uGlow;
  varying vec3 vNormalV;
  varying vec3 vViewDir;
  varying vec2 vUv;

  void main() {
    vec2 uv = clamp(vUv, 0.0, 1.0);
    vec3 N = normalize(vNormalV);
    vec3 V = normalize(vViewDir);
    vec3 L = normalize(vec3(-0.45, 0.6, 0.8));
    float diffuse = 0.55 + 0.6 * max(dot(N, L), 0.0);
    float falloff = mix(0.8, 1.25, (uv.y + (1.0 - uv.x)) * 0.5);
    float edge = min(min(uv.x, 1.0 - uv.x), min(uv.y, 1.0 - uv.y));
    float rim = 1.0 - smoothstep(0.0, 0.07, edge);
    float fres = pow(1.0 - max(dot(N, V), 0.0), 2.0);
    vec3 col = uColor * diffuse * falloff;
    col += uSheen * (rim * 0.35 + fres * 0.5);
    col *= uGlow;
    // A strong pop lights the face's centre from within, so it blooms as a glow
    // rather than as a brighter flat square.
    float core = 1.0 - smoothstep(0.0, 0.62, length(uv - 0.5));
    col += uSheen * core * max(uGlow - 2.0, 0.0) * 1.2;
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
  lit: THREE.ShaderMaterial | null; // the coverless front, lit; null when there's a cover
  std: THREE.MeshStandardMaterial | null; // the coverless cube's material, once the maps load
  stdMaps: THREE.Texture[]; // this tile's clones of the shared maps, to dispose
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
  materialMaps,
}: {
  tex: THREE.Texture | null;
  backdrop: THREE.Texture | null;
  palette: string[];
  coverlessHueValue: number;
  materialMaps: MaterialMaps[] | null;
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
        // A coverless cube keeps whole-face UVs: its material is tiled per face, not cut
        // from one picture.
        for (let k = tex ? 16 : 24; k < 20; k++) {
          const ux = uv.getX(k);
          const uy = uv.getY(k);
          uv.setXY(k, (col + ux) / GRID, (GRID - 1 - row + uy) / GRID);
        }
        for (let k = tex ? 20 : 24; k < 24; k++) {
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
        const lit = rest
          ? new THREE.ShaderMaterial({
              uniforms: {
                uColor: { value: rest.clone() },
                uSheen: { value: new THREE.Color().setHSL((baseHSL.h + 0.04) % 1, 0.6, 0.45, THREE.SRGBColorSpace) },
                uGlow: { value: 1 },
              },
              vertexShader: SIDE_VERT,
              fragmentShader: COVERLESS_FRAG,
              toneMapped: false,
            })
          : null;
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
        // With the materials loaded, a coverless tile is a real cube: one lit, textured
        // material on every face, lit by the studio environment. The emissive is the pop.
        let std: THREE.MeshStandardMaterial | null = null;
        const stdMaps: THREE.Texture[] = [];
        if (!tex && materialMaps) {
          const [main, a, b] = albumMaterials(baseHSL.h);
          const r = hash01(baseHSL.h, row * GRID + col);
          const set = materialMaps[r < 0.6 ? main : r < 0.85 ? a : b];
          // Each tile shows its own quarter of the texture, so neighbours don't repeat.
          const ox = hash01(baseHSL.h, row * GRID + col + 500) * 0.5;
          const oy = hash01(baseHSL.h, row * GRID + col + 900) * 0.5;
          const own = (t: THREE.Texture) => {
            const c = t.clone();
            c.repeat.set(0.5, 0.5);
            c.offset.set(ox, oy);
            stdMaps.push(c);
            return c;
          };
          const orm = own(set.orm);
          std = new THREE.MeshStandardMaterial({
            map: own(set.color),
            normalMap: own(set.normal),
            roughnessMap: orm,
            metalnessMap: orm,
            aoMap: orm,
            metalness: 1,
            roughness: 1,
            color: new THREE.Color(1, 1, 1).lerp(new THREE.Color().setHSL(baseHSL.h, 0.6, 0.6), 0.22),
            emissive: new THREE.Color().setHSL(baseHSL.h, 0.8, 0.6, THREE.SRGBColorSpace),
            emissiveMap: getRimMask(),
            emissiveIntensity: 0,
            envMapIntensity: 1.6,
          });
        }
        const face = lit ?? front;
        const materials = std ? [std, std, std, std, std, std] : [side, side, side, side, face, face];

        const x = (col - (GRID - 1) / 2) * size;
        const y = ((GRID - 1) / 2 - row) * size;
        out.push({ geometry, front, lit, std, stdMaps, side, materials, x, y, dist, phase: Math.random(), hue, flip: 0, flipTarget: 0, rest });
      }
    }
    return out;
  }, [tex, palette, coverlessHueValue, materialMaps]);

  useEffect(() => {
    return () => {
      for (const t of tiles) {
        t.geometry.dispose();
        t.front.dispose();
        t.lit?.dispose();
        t.std?.dispose();
        for (const m of t.stdMaps) m.dispose();
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
      // Without a cover the lit front rests dark and a pop drives it past 1, into the bloom.
      // (Until 1.7 this set every coverless tile to the same flat grey.)
      // A pop lights the cube from inside, past the bloom threshold, so it glows.
      if (t.std) t.std.emissiveIntensity = Math.min(Math.max(z - 0.35, 0), 1.0) * 2.0 * tuning.popGlow;
      if (t.lit) t.lit.uniforms.uGlow.value = 1 + Math.min(z, 1.4) * 1.2 * tuning.popGlow;
      else t.front.color.setScalar(THREE.MathUtils.clamp(0.5 + z * 0.25, 0.5, 0.9));
      // Up to 0.9 the sides track the pop as before; past that, a strong pop drives them
      // over the bloom threshold so the tile's edges glow.
      // Without a cover every side shares one hue, so they all cross together: dimmer.
      t.side.uniforms.uGlow.value =
        (THREE.MathUtils.clamp(0.35 + z * 0.4, 0.3, 0.9) + Math.max(z - 0.8, 0) * 0.5 * tuning.popGlow) *
        (t.lit ? 0.6 : 1);
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
      {!tex && materialMaps && (
        <>
          <StudioEnvironment />
          {/* Key light from the upper left. The fill is a hemisphere light, which brightens
              surfaces without a reflection: a directional fill near the camera mirrored off
              the flat metal fronts straight into the lens and bloomed as a hot spot. */}
          <directionalLight position={[-3, 4, 6]} intensity={1.6} />
          <hemisphereLight args={['#ffffff', '#202020', 0.9]} />
        </>
      )}
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
        // See BLOOM_THRESHOLD: the threshold is fixed, and only pops cross it.
        bloomIntensity={BLOOM_STRENGTH}
        // A lit, textured cube's brightest face sits near 1, so the coverless scene blooms
        // only above that; the pop's rim is driven well past it.
        bloomThreshold={tex ? BLOOM_THRESHOLD : COVERLESS_BLOOM_THRESHOLD}
        bloomThresholdFollowsMusic={false}
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

/**
 * Materials for an album with no cover: eight CC0 sets from ambientCG, packed at 512 px into
 * colour, normal and occlusion/roughness/metalness (``public/m-<name>-*.jpg``; credits in
 * ``public/CREDITS.md``). Each album uses three of them, chosen from its name, so it always
 * looks the same and different albums look different.
 */
const MATERIAL_NAMES = ['plaster', 'gold', 'red', 'teal', 'plates', 'tiles', 'rust', 'steel'] as const;
type MaterialMaps = { color: THREE.Texture; normal: THREE.Texture; orm: THREE.Texture };

let materialsPromise: Promise<MaterialMaps[]> | null = null;
function loadMaterials(): Promise<MaterialMaps[]> {
  if (!materialsPromise) {
    const loader = new THREE.TextureLoader();
    loader.setCrossOrigin('anonymous');
    const load = (file: string, srgb: boolean) =>
      loader.loadAsync(file).then((t) => {
        t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
        t.wrapS = t.wrapT = THREE.RepeatWrapping;
        t.anisotropy = 4;
        return t;
      });
    materialsPromise = Promise.all(
      MATERIAL_NAMES.map(async (name) => ({
        color: await load(`m-${name}-c.jpg`, true),
        normal: await load(`m-${name}-n.jpg`, false),
        orm: await load(`m-${name}-orm.jpg`, false),
      }))
    ).catch((err) => {
      materialsPromise = null; // try again next time rather than never
      throw err;
    });
  }
  return materialsPromise;
}

function useCoverlessMaterials(wanted: boolean): MaterialMaps[] | null {
  const [maps, setMaps] = useState<MaterialMaps[] | null>(null);
  useEffect(() => {
    if (!wanted || maps) return;
    let live = true;
    loadMaterials().then((m) => live && setMaps(m), () => undefined);
    return () => {
      live = false;
    };
  }, [wanted, maps]);
  return maps;
}

/**
 * Something for the metal to reflect: a CC0 studio HDRI from Poly Haven (``public/env.hdr``),
 * prefiltered once and set as the scene's environment. Without it a metallic material has
 * nothing to show and reads as flat grey.
 */
function StudioEnvironment() {
  const { gl, scene } = useThree();
  // Exposure brightens the picture after the bloom has picked what glows, so it lifts the
  // cubes at rest without lighting up more of the frame. Only while there is no cover.
  useFrame(() => {
    gl.toneMappingExposure = tuning.exposure;
  });
  useEffect(() => () => void (gl.toneMappingExposure = 1), [gl]);
  useEffect(() => {
    let live = true;
    let target: THREE.WebGLRenderTarget | null = null;
    new HDRLoader().setDataType(THREE.FloatType).load('env.hdr', (hdr) => {
      if (!live) return hdr.dispose();
      // Clamp the studio's lights. Its softboxes are many times brighter than 1, so every
      // reflection of one crossed the bloom threshold and the cube edges lit up as a grid of
      // white lines. Below the threshold, reflections stay reflections and only a pop glows.
      const data = hdr.image.data as Float32Array;
      for (let i = 0; i < data.length; i++) if (data[i] > ENV_CEILING) data[i] = ENV_CEILING;
      hdr.mapping = THREE.EquirectangularReflectionMapping;
      const pmrem = new THREE.PMREMGenerator(gl);
      target = pmrem.fromEquirectangular(hdr);
      scene.environment = target.texture;
      scene.environmentIntensity = 1.8; // x ENV_CEILING stays under the bloom threshold
      hdr.dispose();
      pmrem.dispose();
    });
    return () => {
      live = false;
      scene.environment = null;
      target?.dispose();
    };
  }, [gl, scene]);
  return null;
}

/**
 * Where a coverless cube glows on a pop: its rim, fading to nothing a fifth of the way in.
 * A whole-face glow lit most of the grid at once on a loud passage and washed the frame white;
 * a rim reads as light catching the edge, as the cover version's side faces do.
 */
let rimMask: THREE.CanvasTexture | null = null;
function getRimMask(): THREE.CanvasTexture {
  if (rimMask) return rimMask;
  const S = 128;
  const c = document.createElement('canvas');
  c.width = c.height = S;
  const ctx = c.getContext('2d')!;
  const img = ctx.createImageData(S, S);
  for (let y = 0; y < S; y++) {
    for (let x = 0; x < S; x++) {
      const e = Math.min(x, S - 1 - x, y, S - 1 - y) / S; // 0 at the edge, 0.5 at the centre
      const v = Math.round(255 * Math.pow(Math.max(0, 1 - e / 0.2), 2.2));
      const i = (y * S + x) * 4;
      img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
      img.data[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  rimMask = new THREE.CanvasTexture(c);
  return rimMask;
}

/** The brightest the studio environment may be, so a reflection never blooms. */
const ENV_CEILING = 0.55;

/** A small deterministic hash of a string and a number, in [0, 1). */
function hash01(seed: number, i: number): number {
  let h = Math.imul((seed * 0x100000000) ^ (i + 0x9e3779b9), 0x85ebca6b);
  h ^= h >>> 13;
  h = Math.imul(h, 0xc2b2ae35);
  h ^= h >>> 16;
  return (h >>> 0) / 0x100000000;
}

/** The album's three materials, by index into MATERIAL_NAMES: one main, two accents. */
export function albumMaterials(hue: number): [number, number, number] {
  const order = MATERIAL_NAMES.map((_, i) => i).sort((a, b) => hash01(hue, a + 101) - hash01(hue, b + 101));
  return [order[0], order[1], order[2]];
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

  const materialMaps = useCoverlessMaterials(!tex);

  // Shown while there is no cover: before one loads, and for an album that has none.
  const coverlessBackdrop = useMemo(() => (tex ? null : makeCoverlessBackdrop(hue)), [tex, hue]);
  useEffect(() => () => coverlessBackdrop?.dispose(), [coverlessBackdrop]);

  return (
    <div className="w-full h-full" style={{ position: 'relative' }}>
      <Canvas camera={{ position: [0, 0.4, REST_DISTANCE], fov: FOV }} gl={{ antialias: !mobile, alpha: false }}>
        <TilesScene tex={tex} backdrop={backdrop ?? coverlessBackdrop} palette={palette} coverlessHueValue={hue} materialMaps={materialMaps} />
      </Canvas>
    </div>
  );
}

export default BeatTiles;
