/**
 * Reactive Terrain — the flagship generative visualizer (default).
 *
 * A vaporwave landscape (à la Maxime Heckel's three.js scene): a flat neon road
 * down the middle with angular, flat-shaded peaks on the sides, lit by coloured
 * spotlights and scrolling forever via a two-plane treadmill. Behind it sits a
 * mood sky — a warm SUN for upbeat tracks (high valence) or a cool MOON for mellow
 * ones — and palm trees line the road. The side peaks swell with bass and jump on
 * every beat (the road stays flat because its heightmap is zero there); chromatic
 * aberration + bloom finish the look. Colours come from the album-art palette.
 */
import { useRef, useMemo, useEffect, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { type VisualizerProps } from '../types';
import type { TrackFeatures } from '../../../types';
import { useAudioAnalyser, getAudioData, useArtworkPalette } from '../hooks';
import { AudioReactiveEffects } from '../effects/AudioReactiveEffects';
import { FrameScheduler } from '../effects/FrameScheduler';
import { isMobile } from '../../../utils/platform';

const mobile = isMobile();

function hexColor(c: string | undefined, fallback: string): THREE.Color {
  return new THREE.Color(c ?? fallback);
}

// ---------------------------------------------------------------------------
// Generated heightmap (flat road + rolling hills on the sides).
// ---------------------------------------------------------------------------

// Shared height field (built once; deterministic per page load). Exposes the
// displacement texture AND a sampler so other layers (the CV overlay) can find
// the peak height at any (u,v).
interface HeightField {
  texture: THREE.DataTexture;
  sample: (u: number, v: number) => number; // 0..1
}
let _heightField: HeightField | null = null;
function getHeightField(): HeightField {
  if (_heightField) return _heightField;
  const W = 64;
  const H = 128;
  const data = new Uint8Array(W * H);

  // Coherent value-noise (smooth, tileable in V via modulo) → rolling hills, not
  // per-pixel spikes. fbm = a few octaves of interpolated random lattices.
  type Lat = { a: Float32Array; gw: number; gh: number };
  const makeLat = (gw: number, gh: number): Lat => {
    const a = new Float32Array(gw * gh);
    for (let i = 0; i < a.length; i++) a[i] = Math.random();
    return { a, gw, gh };
  };
  const sampleLat = (L: Lat, u: number, v: number) => {
    const fx = u * L.gw;
    const fy = v * L.gh;
    const x0 = Math.floor(fx);
    const y0 = Math.floor(fy);
    const tx = THREE.MathUtils.smoothstep(fx - x0, 0, 1);
    const ty = THREE.MathUtils.smoothstep(fy - y0, 0, 1);
    const at = (xi: number, yi: number) =>
      L.a[(((yi % L.gh) + L.gh) % L.gh) * L.gw + (((xi % L.gw) + L.gw) % L.gw)];
    const top = at(x0, y0) + (at(x0 + 1, y0) - at(x0, y0)) * tx;
    const bot = at(x0, y0 + 1) + (at(x0 + 1, y0 + 1) - at(x0, y0 + 1)) * tx;
    return top + (bot - top) * ty;
  };
  const oct1 = makeLat(5, 9); // big rolling hills
  const oct2 = makeLat(11, 20); // medium
  const oct3 = makeLat(23, 40); // fine detail

  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const u = x / (W - 1);
      const v = y / (H - 1);
      // Flat in the middle (the road), ramping to peaks toward the edges.
      const sideMask = THREE.MathUtils.smoothstep(Math.abs(u - 0.5), 0.06, 0.2);
      let n = 0.6 * sampleLat(oct1, u, v) + 0.3 * sampleLat(oct2, u, v) + 0.12 * sampleLat(oct3, u, v);
      n /= 1.02;
      // Taller toward the outer edges (distant "mountains").
      const edge = THREE.MathUtils.smoothstep(Math.abs(u - 0.5), 0.3, 0.5);
      const h = sideMask * Math.pow(n, 1.3) * (0.7 + 0.7 * edge);
      data[y * W + x] = Math.min(255, Math.floor(h * 255));
    }
  }
  const texture = new THREE.DataTexture(data, W, H, THREE.RedFormat);
  texture.needsUpdate = true;
  const sample = (u: number, v: number) => {
    const x = THREE.MathUtils.clamp(Math.round(u * (W - 1)), 0, W - 1);
    const y = THREE.MathUtils.clamp(Math.round(v * (H - 1)), 0, H - 1);
    return data[y * W + x] / 255;
  };
  _heightField = { texture, sample };
  return _heightField;
}

const TERRAIN_W = 52;
const TERRAIN_D = 30;
// Mesh subdivisions — the grid texture repeats once per segment so its lines sit
// on the quad edges (grid == deformed wireframe). Keep these two in sync.
const SEG_W = mobile ? 64 : 96;
const SEG_D = mobile ? 48 : 72;

// Shared scroll state so the CV overlay rides exactly with the terrain.
const terrainScrollRef = { current: 0 };
const terrainDispRef = { current: 3.0 };

// A metallic "shard" the CV overlay can lock onto.
interface MetalCell {
  u: number;
  v: number;
  x: number; // world x
  cz: number; // plane-local z (world z = cz + scroll)
  strength: number; // metalness 0..1
  height: number; // heightmap value 0..1 at this cell
  id: string;
  conf: number;
}
interface MetalField {
  texture: THREE.DataTexture;
  cells: MetalCell[];
}
let _metalField: MetalField | null = null;
// Metalness across the width: matte in the middle (the road), patchy metallic shards
// toward the side peaks. Also returns the shard cell list (same lattice) so the CV
// overlay tracks the real reflective polys.
function getMetalField(): MetalField {
  if (_metalField) return _metalField;
  const W = 64;
  const H = 64;
  const data = new Uint8Array(W * H * 4);
  const GW = 10;
  const GH = 10;
  const lat = new Float32Array(GW * GH);
  for (let i = 0; i < lat.length; i++) lat[i] = Math.random();
  const sample = (u: number, v: number) => {
    const fx = u * GW;
    const fy = v * GH;
    const x0 = Math.floor(fx);
    const y0 = Math.floor(fy);
    const tx = THREE.MathUtils.smoothstep(fx - x0, 0, 1);
    const ty = THREE.MathUtils.smoothstep(fy - y0, 0, 1);
    const at = (xi: number, yi: number) => lat[(((yi % GH) + GH) % GH) * GW + (((xi % GW) + GW) % GW)];
    const top = at(x0, y0) + (at(x0 + 1, y0) - at(x0, y0)) * tx;
    const bot = at(x0, y0 + 1) + (at(x0 + 1, y0 + 1) - at(x0, y0 + 1)) * tx;
    return top + (bot - top) * ty;
  };
  const metalAt = (u: number, v: number) => {
    const sideMask = THREE.MathUtils.smoothstep(Math.abs(u - 0.5), 0.06, 0.2);
    const patch = THREE.MathUtils.smoothstep(sample(u, v), 0.42, 0.78);
    return sideMask * (0.35 + 0.65 * patch);
  };
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const u = x / (W - 1);
      const v = y / (H - 1);
      const val = Math.floor(Math.min(1, metalAt(u, v)) * 255);
      const idx = (y * W + x) * 4;
      data[idx] = val;
      data[idx + 1] = val;
      data[idx + 2] = val;
      data[idx + 3] = 255;
    }
  }
  const t = new THREE.DataTexture(data, W, H, THREE.RGBAFormat);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.needsUpdate = true;

  // Pick the strongest metallic shards (local maxima on a coarse grid).
  const height = getHeightField();
  const SX = 26;
  const SY = 26;
  const mAt = (i: number, j: number) => metalAt(i / (SX - 1), j / (SY - 1));
  const cand: MetalCell[] = [];
  for (let j = 1; j < SY - 1; j++) {
    for (let i = 1; i < SX - 1; i++) {
      const c = mAt(i, j);
      if (c < 0.62) continue;
      let isMax = true;
      for (let dj = -1; dj <= 1 && isMax; dj++) {
        for (let di = -1; di <= 1; di++) {
          if ((di || dj) && mAt(i + di, j + dj) > c) { isMax = false; break; }
        }
      }
      if (!isMax) continue;
      const u = i / (SX - 1);
      const v = j / (SY - 1);
      cand.push({ u, v, x: (u - 0.5) * TERRAIN_W, cz: (0.5 - v) * TERRAIN_D, strength: c, height: height.sample(u, v), id: '', conf: 0 });
    }
  }
  cand.sort((a, b) => b.strength - a.strength);
  const cells = cand.slice(0, mobile ? 10 : 16).map((c, i) => ({
    ...c,
    id: `0x${(0x2a + i * 7).toString(16).toUpperCase().padStart(2, '0')}`,
    conf: Math.min(0.99, 0.78 + (c.strength - 0.62) * 0.5),
  }));
  _metalField = { texture: t, cells };
  return _metalField;
}

function VaporwaveTerrain({ palette, features }: { palette: string[]; features: TrackFeatures | null }) {
  const height = useMemo(() => getHeightField().texture, []);
  const metalnessMap = useMemo(() => getMetalField().texture, []);
  const geom = useMemo(() => new THREE.PlaneGeometry(TERRAIN_W, TERRAIN_D, SEG_W, SEG_D), []);

  // Layer 1: solid metallic faces. No diffuse (metal), so they're dark except where a
  // facet is angled toward the sun/spotlights → a glint. polygonOffset pushes them back
  // so the wireframe overlay sits cleanly on top.
  const solidMat = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: new THREE.Color('#10101c'),
        metalness: 0.9,
        roughness: 0.45,
        metalnessMap, // matte road in the middle, metallic sides
        displacementMap: height,
        displacementScale: 3.0,
        flatShading: true,
        polygonOffset: true,
        polygonOffsetFactor: 1,
        polygonOffsetUnits: 1,
      }),
    [height, metalnessMap]
  );

  // Layer 2: real GL wireframe overlay (same method as the shapes/palms) — thin neon
  // edges that follow the displacement. No texture → no moiré/blink.
  const wireMat = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: new THREE.Color('#000000'),
        emissive: new THREE.Color('#ff2bd6'),
        emissiveIntensity: 1.0,
        wireframe: true,
        displacementMap: height,
        displacementScale: 3.0,
        flatShading: true,
      }),
    [height]
  );

  const group1 = useRef<THREE.Group>(null);
  const group2 = useRef<THREE.Group>(null);
  const group3 = useRef<THREE.Group>(null);
  const spotA = useRef<THREE.SpotLight>(null);
  const spotB = useRef<THREE.SpotLight>(null);
  const sunLight = useRef<THREE.DirectionalLight>(null);
  const hemi = useRef<THREE.HemisphereLight>(null);
  const zoff = useRef(0);

  const valence = features?.valence ?? 0.4;
  const isSun = valence >= 0.5;

  useEffect(() => {
    wireMat.emissive.copy(hexColor(palette[0], '#ff2bd6'));
    if (spotA.current) spotA.current.color.copy(hexColor(palette[0], isSun ? '#ff5e7a' : '#ff3df5'));
    if (spotB.current) spotB.current.color.copy(hexColor(palette[1], isSun ? '#ffd27f' : '#3c8cff'));
    // The sun/moon casts its colour onto the ground (faces catch the sunset).
    const sunCol = new THREE.Color(isSun ? '#ff8a4d' : '#9fc0ff').lerp(hexColor(palette[0], '#ffffff'), 0.3);
    if (sunLight.current) sunLight.current.color.copy(sunCol);
    if (hemi.current) hemi.current.color.copy(sunCol);
  }, [palette, isSun, wireMat]);

  useEffect(
    () => () => {
      solidMat.dispose();
      wireMat.dispose();
      geom.dispose();
      // height/metalness textures are shared module-level fields — don't dispose.
    },
    [solidMat, wireMat, geom]
  );

  useFrame((_, delta) => {
    const d = Math.min(delta, 0.05);
    const a = getAudioData();
    const bass = a?.bass ?? 0;
    const beat = a?.beat ?? 0;

    // Two-group treadmill — z wraps small, so no float-precision stall.
    const speed = 4 + bass * 7;
    zoff.current = (zoff.current + speed * d) % TERRAIN_D;
    if (group1.current) group1.current.position.z = zoff.current;
    if (group2.current) group2.current.position.z = zoff.current - TERRAIN_D;
    if (group3.current) group3.current.position.z = zoff.current - 2 * TERRAIN_D;

    // Peaks swell with bass + jump on the beat; the road stays flat (heightmap 0).
    const ds = 3.0 + bass * 2.6 + beat * 1.8;
    solidMat.displacementScale = ds;
    wireMat.displacementScale = ds;
    terrainScrollRef.current = zoff.current; // share with the CV overlay
    terrainDispRef.current = ds;
    wireMat.emissiveIntensity = 0.85 + beat * 0.9;
    const si = 45 + beat * 110;
    if (spotA.current) spotA.current.intensity = si;
    if (spotB.current) spotB.current.intensity = si;
  });

  return (
    <>
      {/* Sunset ambient from above + a warm directional from the sun, so the ground catches it. */}
      <hemisphereLight ref={hemi} args={['#ffffff', '#0a0a16', 0.55]} />
      <directionalLight ref={sunLight} position={[0, 6, -40]} intensity={2.4} />
      <spotLight ref={spotA} position={[-10, 9, 8]} angle={0.7} penumbra={0.7} distance={70} decay={1.3} intensity={45} />
      <spotLight ref={spotB} position={[10, 9, 8]} angle={0.7} penumbra={0.7} distance={70} decay={1.3} intensity={45} />
      <group ref={group1} rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.5, 0]}>
        <mesh geometry={geom} material={solidMat} />
        <mesh geometry={geom} material={wireMat} />
      </group>
      <group ref={group2} rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.5, -TERRAIN_D]}>
        <mesh geometry={geom} material={solidMat} />
        <mesh geometry={geom} material={wireMat} />
      </group>
      <group ref={group3} rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.5, -2 * TERRAIN_D]}>
        <mesh geometry={geom} material={solidMat} />
        <mesh geometry={geom} material={wireMat} />
      </group>
    </>
  );
}

// ---------------------------------------------------------------------------
// Sky backdrop: vertical gradient + a sun/moon disc chosen by mood (valence)
// ---------------------------------------------------------------------------

const SKY_VERT = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const SKY_FRAG = /* glsl */ `
  precision highp float;
  uniform vec3 uSkyTop;
  uniform vec3 uSkyHorizon;
  uniform vec3 uDiscColor;
  uniform float uDiscY;
  uniform float uDiscR;
  uniform float uAspect;
  uniform float uIsSun;
  uniform float uGlow;
  varying vec2 vUv;

  void main() {
    vec3 sky = mix(uSkyHorizon, uSkyTop, smoothstep(uDiscY, 1.0, vUv.y));

    vec2 p = vUv - vec2(0.5, uDiscY);
    p.x *= uAspect;
    float d = length(p);

    float disc = smoothstep(uDiscR, uDiscR * 0.92, d);

    // Classic outrun sun: solid at the top, dissolving into horizontal bars whose
    // gaps WIDEN toward the bottom. The gaps cut the disc through to the sky.
    float yy = (vUv.y - (uDiscY - uDiscR)) / (2.0 * uDiscR); // 0 = disc bottom, 1 = top
    float stripes = fract(yy * 6.0);
    float gapAmt = 0.70 * (1.0 - smoothstep(0.0, 0.82, yy)); // bars across most of the disc, solid only at the very top
    float line = smoothstep(gapAmt - 0.05, gapAmt + 0.05, stripes);
    float sunMask = disc * line;

    // Glow only OUTSIDE the disc, so it can't fill the stripe gaps.
    float halo = pow(clamp(1.0 - d / (uDiscR * 2.1), 0.0, 1.0), 2.5) * (1.0 - disc) * uGlow;

    vec3 col = sky;
    col += uDiscColor * halo;
    col = mix(col, uDiscColor, sunMask);
    gl_FragColor = vec4(col, 1.0);
  }
`;

function Backdrop({ palette, features }: { palette: string[]; features: TrackFeatures | null }) {
  const matRef = useRef<THREE.ShaderMaterial>(null);
  const { size } = useThree();

  const valence = features?.valence ?? 0.4;
  const energy = features?.energy ?? 0.5;
  const isSun = valence >= 0.5;

  const uniforms = useMemo(
    () => ({
      uSkyTop: { value: new THREE.Color('#05010a') },
      uSkyHorizon: { value: new THREE.Color('#1a0b2e') },
      uDiscColor: { value: new THREE.Color('#ffd27f') },
      uDiscY: { value: 0.52 },
      uDiscR: { value: 0.16 },
      uAspect: { value: 1 },
      uIsSun: { value: 1 },
      uGlow: { value: 0.12 },
    }),
    []
  );

  useEffect(() => {
    const u = uniforms;
    const accent = hexColor(palette[0], '#ff3df5');
    if (isSun) {
      // Dimmed well below the bloom threshold so the disc doesn't blow out to white.
      u.uDiscColor.value.copy(hexColor('#ffcf73', '#ffcf73')).lerp(accent, 0.35).multiplyScalar(0.5);
      u.uSkyHorizon.value.copy(hexColor(palette[1], '#ff7eb0')).multiplyScalar(0.5);
    } else {
      u.uDiscColor.value.copy(hexColor('#cfe6ff', '#cfe6ff')).lerp(accent, 0.2).multiplyScalar(0.5);
      u.uSkyHorizon.value.copy(hexColor(palette[2] ?? palette[1], '#243b6b')).multiplyScalar(0.45);
    }
    u.uSkyTop.value.copy(hexColor(palette[3] ?? '#05010a', '#05010a')).multiplyScalar(0.3);
    u.uIsSun.value = isSun ? 1 : 0;
    u.uDiscR.value = (isSun ? 0.13 : 0.1) + energy * 0.06;
    u.uGlow.value = (isSun ? 0.14 : 0.1) + energy * 0.07;
  }, [palette, isSun, energy, uniforms]);

  useFrame(() => {
    if (matRef.current) {
      matRef.current.uniforms.uAspect.value = size.width / size.height;
      const bass = getAudioData()?.bass ?? 0;
      matRef.current.uniforms.uGlow.value = (isSun ? 0.14 : 0.1) + energy * 0.07 + bass * 0.12;
    }
  });

  return (
    <mesh position={[0, 6, -45]} renderOrder={-1}>
      <planeGeometry args={[240, 140]} />
      <shaderMaterial
        ref={matRef}
        vertexShader={SKY_VERT}
        fragmentShader={SKY_FRAG}
        uniforms={uniforms}
        depthWrite={false}
        depthTest={false}
        fog={false}
      />
    </mesh>
  );
}

// ---------------------------------------------------------------------------
// Procedural palm trees lining the road. Trunk and fronds are SEPARATE meshes,
// so they scale independently; each palm also gets a random overall size.
// Proportions follow the reference Quaternius palm: the fronds attach about
// halfway up and the crown spreads roughly as wide as the trunk is tall.
// Tune TRUNK_SCALE / FROND_SCALE to change proportions across all palms.
// ---------------------------------------------------------------------------

const Z_NEAR = 9;
const Z_FAR = -36;
const Z_SPAN = Z_NEAR - Z_FAR;

// Proportion knobs applied to every palm (x/z = thickness, y = length).
const TRUNK_SCALE = new THREE.Vector3(1, 1, 1);
const FROND_SCALE = new THREE.Vector3(1, 1, 1);

const PALM = {
  trunkHeight: 3.6, // tall trunk → crown sits high, up out of the foreground
  trunkRadius: 0.14,
  trunkLean: 0.45, // sideways lean of the trunk top
  frondCount: 8,
  frondLength: 2.6,
};

// Segmented trunk: a curved tube whose radius bulges mid-segment and pinches at
// each leaf-scar ring, so the wireframe reads as stacked segments (like a real
// palm trunk), tapering toward the top.
function makeTrunkGeometry(): THREE.BufferGeometry {
  const curve = new THREE.QuadraticBezierCurve3(
    new THREE.Vector3(0, 0, 0),
    new THREE.Vector3(PALM.trunkLean * 0.35, PALM.trunkHeight * 0.6, 0),
    new THREE.Vector3(PALM.trunkLean, PALM.trunkHeight, 0)
  );
  const STN = 56; // stations along the length
  const RAD = 7; // sides
  const N_SEG = 8; // stacked trunk segments
  const frames = curve.computeFrenetFrames(STN, false);
  const positions: number[] = [];
  const indices: number[] = [];
  for (let i = 0; i <= STN; i++) {
    const t = i / STN;
    const p = curve.getPointAt(t);
    const Nrm = frames.normals[i];
    const Bin = frames.binormals[i];
    const taper = 1 - 0.32 * t; // thinner toward the top
    const seg = 0.82 + 0.34 * Math.sin(((t * N_SEG) % 1) * Math.PI); // bulge / pinch
    const r = PALM.trunkRadius * taper * seg;
    for (let j = 0; j <= RAD; j++) {
      const a = (j / RAD) * Math.PI * 2;
      const v = p
        .clone()
        .addScaledVector(Nrm, Math.cos(a) * r)
        .addScaledVector(Bin, Math.sin(a) * r);
      positions.push(v.x, v.y, v.z);
    }
  }
  for (let i = 0; i < STN; i++) {
    for (let j = 0; j < RAD; j++) {
      const a = i * (RAD + 1) + j;
      const b = a + 1;
      const c = a + (RAD + 1);
      const e = c + 1;
      indices.push(a, c, b, b, c, e);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  g.setIndex(indices);
  g.computeVertexNormals();
  return g;
}

// Pinnate fronds (coconut-palm reference): each frond's rachis ARCHES up from the
// crown then droops at the tip, with many forward-swept linear leaflets along both
// sides (longest mid-frond) — a feather, not a fan of grass.
function makeFrondsGeometry(): THREE.BufferGeometry {
  const { frondCount, frondLength: len } = PALM;
  const UP = 1.5; // arch higher
  const DROOP = 1.5; // droop less, so the crown stays up and out of the way
  const verts: number[] = [];
  const Z = new THREE.Vector3(0, 0, 1);
  const DOWN = new THREE.Vector3(0, -1, 0);
  const rachisPt = (t: number) =>
    new THREE.Vector3(t * len, UP * Math.sin(t * Math.PI * 0.55) - DROOP * Math.pow(t, 1.9), 0);

  const pushTri = (a: THREE.Vector3, b: THREE.Vector3, c: THREE.Vector3, M: THREE.Matrix4) => {
    for (const v of [a, b, c]) {
      const p = v.clone().applyMatrix4(M);
      verts.push(p.x, p.y, p.z);
    }
  };

  for (let fi = 0; fi < frondCount; fi++) {
    const M = new THREE.Matrix4().makeRotationY((fi / frondCount) * Math.PI * 2);

    // Rachis (central spine) — a thin tapering strip following the arc.
    const segs = 12;
    for (let s = 0; s < segs; s++) {
      const t0 = s / segs;
      const t1 = (s + 1) / segs;
      const p0 = rachisPt(t0);
      const p1 = rachisPt(t1);
      const w = 0.04 * (1 - t0 * 0.7);
      const o = Z.clone().multiplyScalar(w);
      pushTri(p0.clone().add(o), p0.clone().sub(o), p1.clone().add(o), M);
      pushTri(p0.clone().sub(o), p1.clone().sub(o), p1.clone().add(o), M);
    }

    // Leaflets: dense, forward-swept, linear; longest in the middle of the frond.
    const nLeaf = 13;
    for (let li = 1; li <= nLeaf; li++) {
      const t = li / (nLeaf + 1);
      const base = rachisPt(t);
      const tang = rachisPt(Math.min(1, t + 0.02)).sub(base).normalize();
      const leafLen = 0.85 * Math.sin(t * Math.PI) * (1 - 0.25 * t) + 0.12;
      for (const side of [-1, 1]) {
        const dir = new THREE.Vector3()
          .addScaledVector(tang, 0.75) // swept forward toward the tip (feather)
          .addScaledVector(Z, side * 0.55) // out to the side
          .addScaledVector(DOWN, 0.28) // gentle droop
          .normalize();
        const tip = base.clone().addScaledVector(dir, leafLen);
        const half = tang.clone().multiplyScalar(0.022);
        pushTri(base.clone().sub(half), base.clone().add(half), tip, M);
      }
    }
  }

  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
  g.computeVertexNormals();
  return g;
}

function PalmRows({ palette }: { palette: string[] }) {
  const trunkGeo = useMemo(makeTrunkGeometry, []);
  const frondsGeo = useMemo(makeFrondsGeometry, []);
  const palms = useMemo(() => {
    const baseCol = hexColor(palette[0], '#ff3df5');
    const hsl = { h: 0, s: 0, l: 0 };
    baseCol.getHSL(hsl);
    const perSide = mobile ? 4 : 7;
    const out: { group: THREE.Group; mat: THREE.MeshBasicMaterial; x: number; z: number }[] = [];
    let i = 0;
    // On the flat road (|x| < ~3) so the ground under them doesn't move with the peaks.
    for (const x of [-2.8, 2.8]) {
      for (let j = 0; j < perSide; j++) {
        // Each palm gets a distinct neon hue, spread around the album's base hue.
        const mat = new THREE.MeshBasicMaterial({
          color: new THREE.Color().setHSL((hsl.h + i * 0.16) % 1, 0.85, 0.6),
          wireframe: true,
        });
        const group = new THREE.Group();
        const trunk = new THREE.Mesh(trunkGeo, mat);
        trunk.scale.copy(TRUNK_SCALE);
        const fronds = new THREE.Mesh(frondsGeo, mat);
        fronds.scale.copy(FROND_SCALE);
        fronds.position.set(PALM.trunkLean * TRUNK_SCALE.x, PALM.trunkHeight * TRUNK_SCALE.y, 0);
        group.add(trunk, fronds);
        group.scale.setScalar(1.0 + (((i * 37) % 100) / 100) * 0.6); // size variation ~1.0–1.6
        group.rotation.y = (i * 2.39) % (Math.PI * 2); // vary the lean direction
        out.push({ group, mat, x, z: Z_FAR + (j / perSide) * Z_SPAN });
        i++;
      }
    }
    return out;
  }, [trunkGeo, frondsGeo, palette]);

  useEffect(
    () => () => {
      trunkGeo.dispose();
      frondsGeo.dispose();
      for (const p of palms) p.mat.dispose();
    },
    [trunkGeo, frondsGeo, palms]
  );

  useFrame((state, delta) => {
    const d = Math.min(delta, 0.05);
    const audio = getAudioData();
    const bass = audio?.bass ?? 0;
    const beat = audio?.beat ?? 0;
    const speed = 4 + bass * 7.0;
    const t = state.clock.elapsedTime;

    for (const p of palms) {
      p.z += speed * d;
      if (p.z > Z_NEAR) p.z -= Z_SPAN;
      p.group.position.set(p.x, -1.55, p.z);
      p.group.rotation.z = Math.sin(t * 1.1 + p.x) * 0.03 + beat * 0.04; // sway
    }
  });

  return (
    <>
      {palms.map((p, i) => (
        <primitive key={i} object={p.group} />
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// Abstract objects flying through (wireframe solids, crystals, monoliths)
// ---------------------------------------------------------------------------

type ObjKind = 'wire' | 'crystal' | 'monolith';

interface FlyObject {
  kind: ObjKind;
  geometry: THREE.BufferGeometry;
  material: THREE.MeshBasicMaterial;
  lane: number;
  z: number;
  baseY: number;
  baseScale: number;
  spin: THREE.Vector3;
  bob: number;
}

function FlyingObjects({ palette }: { palette: string[] }) {
  const meshRefs = useRef<(THREE.Mesh | null)[]>([]);

  const objects = useMemo<FlyObject[]>(() => {
    const count = mobile ? 4 : 7;
    const lanes = [-12, -8, 8, 12, -14, 14, -10, 10, -6, 6, -16];
    // Wireframe shapes only — the solid crystals/monoliths are gone.
    const kinds: ObjKind[] = ['wire', 'wire', 'wire', 'wire', 'wire', 'wire', 'wire'];
    const accent = (i: number) => hexColor(palette[i % palette.length], '#a855f7');
    const out: FlyObject[] = [];
    for (let i = 0; i < count; i++) {
      const kind = kinds[i];
      let geometry: THREE.BufferGeometry;
      let material: THREE.MeshBasicMaterial;
      let baseY: number;
      if (kind === 'monolith') {
        geometry = new THREE.BoxGeometry(0.6, 3.6, 0.6);
        material = new THREE.MeshBasicMaterial({ color: accent(i).multiplyScalar(0.6) });
        baseY = 0.2;
      } else if (kind === 'crystal') {
        geometry = new THREE.OctahedronGeometry(0.6);
        material = new THREE.MeshBasicMaterial({ color: accent(i).multiplyScalar(1.4), toneMapped: false });
        baseY = 1.2;
      } else {
        const shapes = [
          () => new THREE.TetrahedronGeometry(0.85),
          () => new THREE.OctahedronGeometry(0.85),
          () => new THREE.BoxGeometry(1.1, 1.1, 1.1),
          () => new THREE.CylinderGeometry(0.7, 0.7, 1.5, 3),
        ];
        geometry = shapes[i % shapes.length]();
        material = new THREE.MeshBasicMaterial({ color: accent(i).multiplyScalar(1.2), wireframe: true });
        baseY = 1.2;
      }
      out.push({
        kind, geometry, material,
        lane: lanes[i % lanes.length],
        z: Z_FAR + (i / count) * Z_SPAN,
        baseY, baseScale: 1,
        spin: new THREE.Vector3(0.2 + (i % 3) * 0.15, 0.3 + (i % 2) * 0.2, 0.1),
        bob: i * 1.7,
      });
    }
    return out;
  }, [palette]);

  useEffect(() => {
    return () => {
      for (const o of objects) {
        o.geometry.dispose();
        o.material.dispose();
      }
    };
  }, [objects]);

  useFrame((state, delta) => {
    const d = Math.min(delta, 0.05);
    const audio = getAudioData();
    const bass = audio?.bass ?? 0;
    const beat = audio?.beat ?? 0;
    const speed = 4 + bass * 7.0;
    const t = state.clock.elapsedTime;

    for (let i = 0; i < objects.length; i++) {
      const mesh = meshRefs.current[i];
      if (!mesh) continue;
      const o = objects[i];
      o.z += speed * d;
      if (o.z > Z_NEAR) o.z -= Z_SPAN;
      const bob = Math.sin(t * 0.8 + o.bob) * 0.3;
      mesh.position.set(o.lane, o.baseY + bob + bass * 0.6, o.z);
      mesh.scale.setScalar(o.baseScale * (1 + beat * 0.25));
      if (o.kind !== 'monolith') {
        mesh.rotation.x += o.spin.x * d;
        mesh.rotation.y += o.spin.y * d;
      } else {
        mesh.rotation.y += o.spin.y * d * 0.3;
      }
    }
  });

  return (
    <>
      {objects.map((o, i) => (
        <mesh
          key={i}
          ref={(el) => (meshRefs.current[i] = el)}
          geometry={o.geometry}
          material={o.material}
          position={[o.lane, o.baseY, o.z]}
        />
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// Scene
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Road elements: chevrons, a driving car, light gates, and a "sound river".
// All scroll toward the camera (recycling Z_FAR → Z_NEAR) down the road centre.
// ---------------------------------------------------------------------------

function makeChevronGeometry(): THREE.BufferGeometry {
  // A flat ">" pointing toward the sun (-Z), lying on the road (XZ plane).
  const v: number[] = [];
  const tri = (a: number[], b: number[], c: number[]) => v.push(...a, ...b, ...c);
  const tip = [0, 0, -0.9], tipIn = [0, 0, -0.35];
  const aL = [-1.0, 0, 0.5], aLin = [-0.55, 0, 0.5];
  const aR = [1.0, 0, 0.5], aRin = [0.55, 0, 0.5];
  tri(tip, aL, aLin); tri(tip, aLin, tipIn);
  tri(tip, aRin, aR); tri(tip, tipIn, aRin);
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(v, 3));
  return g;
}

function RoadChevrons({ palette }: { palette: string[] }) {
  const geo = useMemo(makeChevronGeometry, []);
  const baseCol = useMemo(() => hexColor(palette[0], '#ff3df5'), [palette]);
  const mat = useMemo(
    () => new THREE.MeshBasicMaterial({ color: baseCol.clone(), side: THREE.DoubleSide, toneMapped: false }),
    [baseCol]
  );
  const refs = useRef<(THREE.Mesh | null)[]>([]);
  const count = mobile ? 8 : 14;
  const items = useMemo(() => Array.from({ length: count }, (_, i) => ({ z: Z_FAR + (i / count) * Z_SPAN })), [count]);
  useEffect(() => () => { geo.dispose(); mat.dispose(); }, [geo, mat]);

  useFrame((_, delta) => {
    const d = Math.min(delta, 0.05);
    const audio = getAudioData();
    const bass = audio?.bass ?? 0;
    const beat = audio?.beat ?? 0;
    const speed = 4 + bass * 7;
    mat.color.copy(baseCol).multiplyScalar(0.5 + beat * 1.7); // flash on beat
    for (let i = 0; i < items.length; i++) {
      const m = refs.current[i];
      if (!m) continue;
      items[i].z += speed * d;
      if (items[i].z > Z_NEAR) items[i].z -= Z_SPAN;
      m.position.set(0, -1.48, items[i].z);
    }
  });

  return (
    <>
      {items.map((_, i) => (
        <mesh key={i} ref={(el) => (refs.current[i] = el)} geometry={geo} material={mat} />
      ))}
    </>
  );
}

function SoundRiver({ palette }: { palette: string[] }) {
  const LEN = 64;
  const WIDTH = 1.4;
  const geo = useMemo(() => {
    const positions: number[] = [];
    const indices: number[] = [];
    for (let i = 0; i <= LEN; i++) {
      const z = THREE.MathUtils.lerp(Z_NEAR, Z_FAR, i / LEN);
      positions.push(-WIDTH / 2, 0, z, WIDTH / 2, 0, z);
    }
    for (let i = 0; i < LEN; i++) {
      const a = i * 2;
      indices.push(a, a + 2, a + 1, a + 1, a + 2, a + 3);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    g.setIndex(indices);
    return g;
  }, []);
  const mat = useMemo(
    () => new THREE.MeshBasicMaterial({ color: hexColor(palette[2] ?? palette[0], '#00ffd0'), wireframe: true, toneMapped: false }),
    [palette]
  );
  const scroll = useRef(0);
  useEffect(() => () => { geo.dispose(); mat.dispose(); }, [geo, mat]);

  useFrame((_, delta) => {
    const d = Math.min(delta, 0.05);
    const audio = getAudioData();
    const fd = audio?.frequencyData;
    const bass = audio?.bass ?? 0;
    scroll.current += d * (4 + bass * 7) * 1.5;
    const s = Math.floor(scroll.current);
    const pos = geo.attributes.position as THREE.BufferAttribute;
    for (let i = 0; i <= LEN; i++) {
      let amp = 0;
      if (fd && fd.length) {
        const k = (((i + s) % LEN) + LEN) % LEN;
        const idx = Math.floor((k / LEN) * (fd.length - 1));
        amp = (fd[idx] / 255) * 1.8;
      }
      pos.setY(i * 2, amp);
      pos.setY(i * 2 + 1, amp);
    }
    pos.needsUpdate = true;
  });

  return <mesh geometry={geo} material={mat} position={[0, -1.0, 0]} />;
}

const CAR_URL = new URL('./car.glb', import.meta.url).href;
let carTemplatePromise: Promise<THREE.Group> | null = null;
function loadCarTemplate(): Promise<THREE.Group> {
  if (!carTemplatePromise) {
    carTemplatePromise = new Promise((resolve, reject) => {
      new GLTFLoader().load(CAR_URL, (g) => resolve(g.scene), undefined, reject);
    });
  }
  return carTemplatePromise;
}

function OutrunCar({ palette }: { palette: string[] }) {
  const [template, setTemplate] = useState<THREE.Group | null>(null);
  const groupRef = useRef<THREE.Group>(null);

  useEffect(() => {
    let cancelled = false;
    loadCarTemplate()
      .then((s) => { if (!cancelled) setTemplate(s); })
      // eslint-disable-next-line no-console
      .catch((e) => console.warn('[Visualizer] car model failed to load:', e));
    return () => { cancelled = true; };
  }, []);

  // Neon edge-highlight material (Tron-style panel lines that catch the bloom).
  const edgeMat = useMemo(
    () => new THREE.LineBasicMaterial({ color: hexColor(palette[1] ?? palette[0], '#39ffd0'), toneMapped: false }),
    [palette]
  );
  useEffect(() => () => edgeMat.dispose(), [edgeMat]);

  const car = useMemo(() => {
    if (!template) return null;
    const c = template.clone(true);
    const box = new THREE.Box3().setFromObject(c);
    const size = new THREE.Vector3();
    box.getSize(size);
    const longest = Math.max(size.x, size.z) || 1;
    c.scale.setScalar(6.0 / longest);
    const box2 = new THREE.Box3().setFromObject(c);
    c.position.y -= box2.min.y; // base on the ground
    const edgeGeos: THREE.BufferGeometry[] = [];
    c.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      m.material = new THREE.MeshStandardMaterial({
        color: new THREE.Color('#15151f'),
        metalness: 0.7,
        roughness: 0.35,
        emissive: new THREE.Color('#10101a'),
        emissiveIntensity: 0.6, // lift it off the bright background
      });
      const eg = new THREE.EdgesGeometry(m.geometry, 24); // only prominent panel/silhouette edges
      edgeGeos.push(eg);
      m.add(new THREE.LineSegments(eg, edgeMat));
    });
    return { group: c, edgeGeos };
  }, [template, edgeMat]);
  useEffect(() => () => car?.edgeGeos.forEach((g) => g.dispose()), [car]);

  const underglow = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: hexColor(palette[0], '#ff3df5'),
        transparent: true,
        opacity: 0.55,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        toneMapped: false,
      }),
    [palette]
  );
  useEffect(() => () => underglow.dispose(), [underglow]);

  useFrame((state) => {
    if (!groupRef.current) return;
    const bass = getAudioData()?.bass ?? 0;
    const t = state.clock.elapsedTime;
    groupRef.current.position.y = -1.5 + bass * 0.2 + Math.sin(t * 1.5) * 0.04;
    groupRef.current.rotation.z = Math.sin(t * 0.8) * 0.03; // gentle sway
  });

  if (!car) return null;
  return (
    <group ref={groupRef} position={[0, -1.5, -4.5]} rotation={[0, Math.PI, 0]}>
      <primitive object={car.group} />
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.03, 0]} material={underglow}>
        <planeGeometry args={[3.8, 6.2]} />
      </mesh>
    </group>
  );
}

// ---------------------------------------------------------------------------
// "Computer vision" detection overlay: object-detection brackets that track the
// reflective side terrain. <CVTargets> (in the Canvas) projects moving anchors
// to screen and writes them to a shared ref; <CVOverlay> (DOM) draws the HUD.
// ---------------------------------------------------------------------------

interface CVTarget { x: number; y: number; size: number; vis: number; id: string; conf: number }
const cvTargetsRef: { current: CVTarget[] } = { current: [] };

function CVTargets() {
  const { camera, size } = useThree();
  const v = useMemo(() => new THREE.Vector3(), []);
  const cells = useMemo(() => getMetalField().cells, []);

  useEffect(() => () => { cvTargetsRef.current = []; }, []);

  useFrame(() => {
    const W = size.width;
    const H = size.height;
    const scroll = terrainScrollRef.current;
    const disp = terrainDispRef.current;
    const out: CVTarget[] = [];
    for (const c of cells) {
      // World z of this shard, wrapped to the nearest plane window (Z_NEAR-TD, Z_NEAR].
      let z = c.cz + scroll;
      z = (((z - Z_NEAR) % TERRAIN_D) + TERRAIN_D) % TERRAIN_D + (Z_NEAR - TERRAIN_D);
      const y = -1.5 + c.height * disp; // sits on the actual peak
      v.set(c.x, y, z).project(camera);
      if (v.z > 1 || Math.abs(v.x) > 1.3 || Math.abs(v.y) > 1.3) continue; // behind / off-screen
      const dist = Math.abs(z - 9);
      const edge = THREE.MathUtils.clamp((1.3 - Math.max(Math.abs(v.x), Math.abs(v.y))) / 0.3, 0, 1);
      out.push({
        x: (v.x * 0.5 + 0.5) * W,
        y: (-v.y * 0.5 + 0.5) * H,
        size: THREE.MathUtils.clamp((c.strength * 1500) / (dist + 6), 18, 230), // ∝ shard size × perspective
        vis: edge,
        id: c.id,
        conf: c.conf,
      });
    }
    cvTargetsRef.current = out;
  });

  return null;
}

function CVOverlay() {
  const svgRef = useRef<SVGSVGElement>(null);
  useEffect(() => {
    let raf = 0;
    const ns = 'http://www.w3.org/2000/svg';
    const color = '#5fffd0';
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const svg = svgRef.current;
      if (!svg) return;
      const beat = getAudioData()?.beat ?? 0;
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      for (const t of cvTargetsRef.current) {
        if (t.vis <= 0.01) continue;
        const s = t.size * (1 + beat * 0.12);
        const half = s / 2;
        const x0 = t.x - half, y0 = t.y - half, x1 = t.x + half, y1 = t.y + half;
        const arm = Math.max(6, s * 0.22);
        const g = document.createElementNS(ns, 'g');
        g.setAttribute('opacity', (0.85 * t.vis).toFixed(2));
        const corner = (pts: string) => {
          const p = document.createElementNS(ns, 'polyline');
          p.setAttribute('points', pts);
          p.setAttribute('fill', 'none');
          p.setAttribute('stroke', color);
          p.setAttribute('stroke-width', '1.5');
          g.appendChild(p);
        };
        corner(`${x0},${y0 + arm} ${x0},${y0} ${x0 + arm},${y0}`);
        corner(`${x1 - arm},${y0} ${x1},${y0} ${x1},${y0 + arm}`);
        corner(`${x0},${y1 - arm} ${x0},${y1} ${x0 + arm},${y1}`);
        corner(`${x1 - arm},${y1} ${x1},${y1} ${x1},${y1 - arm}`);
        // crosshair
        const ch = document.createElementNS(ns, 'path');
        ch.setAttribute('d', `M${t.x - 5},${t.y} h10 M${t.x},${t.y - 5} v10`);
        ch.setAttribute('stroke', color);
        ch.setAttribute('stroke-width', '1');
        ch.setAttribute('opacity', '0.7');
        g.appendChild(ch);
        // label
        const text = document.createElementNS(ns, 'text');
        text.setAttribute('x', x0.toFixed(0));
        text.setAttribute('y', (y0 - 4).toFixed(0));
        text.setAttribute('fill', color);
        text.setAttribute('font-family', 'monospace');
        text.setAttribute('font-size', '10');
        text.textContent = `${t.id} ${(t.conf * 100).toFixed(0)}%`;
        g.appendChild(text);
        svg.appendChild(g);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);
  return <svg ref={svgRef} className="absolute inset-0 w-full h-full pointer-events-none" style={{ zIndex: 5 }} />;
}

function TerrainScene({ palette, features }: { palette: string[]; features: TrackFeatures | null }) {
  useAudioAnalyser(true);

  const valence = features?.valence ?? 0.4;
  const isSun = valence >= 0.5;

  // Fog colour = the sunset horizon, so the road dissolves INTO the sky.
  const fogHex = useMemo(() => {
    const base = new THREE.Color(isSun ? '#ff7a52' : '#3a4d8c');
    base.lerp(hexColor(palette[1] ?? '#8899ff', '#8899ff'), 0.35).multiplyScalar(0.72);
    return `#${base.getHexString()}`;
  }, [palette, isSun]);

  return (
    <>
      <color attach="background" args={[fogHex]} />
      <fog attach="fog" args={[fogHex, 5, 24]} />
      <Backdrop palette={palette} features={features} />
      <VaporwaveTerrain palette={palette} features={features} />
      <RoadChevrons palette={palette} />
      <SoundRiver palette={palette} />
      <OutrunCar palette={palette} />
      <PalmRows palette={palette} />
      <FlyingObjects palette={palette} />
      <CVTargets />
      <AudioReactiveEffects
        enableBloom
        enableVignette
        enableRGBShift
        rgbShiftAmount={0.0045}
        bloomIntensity={mobile ? 0.6 : 0.8}
        bloomThreshold={0.6}
        bloomRadius={0.5}
        bloomBassBoost={0.4}
        halfResolution={mobile}
      />
      <FrameScheduler />
    </>
  );
}

export function ReactiveTerrain({ artworkUrl, features }: VisualizerProps) {
  const palette = useArtworkPalette(artworkUrl);
  return (
    <div className="w-full h-full relative">
      <Canvas
        frameloop="always"
        camera={{ position: [0, 2.0, 9], fov: 72 }}
        gl={{ antialias: !mobile, alpha: false }}
      >
        <TerrainScene palette={palette} features={features} />
      </Canvas>
      <CVOverlay />
    </div>
  );
}

export default ReactiveTerrain;
