/**
 * Rain Window Visualizer — Three.js + GLSL rewrite.
 *
 * Two-pass FBO rendering:
 *   Pass 1: Bokeh background + trails → WebGLRenderTarget
 *   Pass 2: Compositor samples FBO with per-droplet refraction, SSS, caustics
 *
 * Droplets act as tiny lenses — refracting, tinting, and concentrating background light.
 */
import { useRef, useMemo, useEffect } from 'react';
import { Canvas, useFrame, useThree, extend } from '@react-three/fiber';
import { shaderMaterial } from '@react-three/drei';
import * as THREE from 'three';
import { useAudioAnalyser, getAudioData } from '../../../hooks/useAudioAnalyser';
import { useArtworkPalette } from '../hooks/useArtworkPalette';
import { isMobile } from '../../../utils/platform';
import { registerVisualizer, type VisualizerProps } from '../types';
import { AudioReactiveEffects } from '../effects/AudioReactiveEffects';
import { FrameScheduler } from '../effects/FrameScheduler';

const mobile = isMobile();

const MAX_DROPLETS = 60;
const MAX_TRAIL = 30;

// ============================================================================
// Droplet Physics
// ============================================================================

interface Droplet {
  x: number;
  y: number;
  radius: number;
  velocityY: number;
  velocityX: number;
  trail: Array<{ x: number; y: number; age: number }>;
  opacity: number;
  stuck: boolean;
  mass: number;
  releaseThreshold: number;
}

interface ResidualDrop {
  x: number;
  y: number;
  radius: number;
  opacity: number;
}

function createDroplet(canvasWidth: number): Droplet {
  const radius = 2 + Math.random() * Math.random() * 6;
  return {
    x: Math.random() * canvasWidth,
    y: -radius * 2,
    radius,
    velocityY: 0.15 + Math.random() * 0.35,
    velocityX: (Math.random() - 0.5) * 0.15,
    trail: [],
    opacity: 0.4 + Math.random() * 0.4,
    stuck: false,
    mass: 0,
    releaseThreshold: 0.3 + Math.random() * 0.7,
  };
}

function updateDroplet(
  droplet: Droplet,
  canvasHeight: number,
  residuals: ResidualDrop[]
): boolean {
  if (droplet.stuck) {
    // Surface tension holds the drop — no gravity
    droplet.velocityY = 0;
    droplet.velocityX = (Math.random() - 0.5) * 0.02;
    droplet.mass += 0.01;

    if (droplet.mass > droplet.releaseThreshold) {
      // Release with burst velocity
      droplet.stuck = false;
      droplet.velocityY = 0.3 + droplet.mass * 0.8;
      droplet.mass = 0;

      // Shed a residual bead at release point (pinch-off)
      residuals.push({
        x: droplet.x,
        y: droplet.y,
        radius: droplet.radius * (0.3 + Math.random() * 0.3),
        opacity: 0.3 + Math.random() * 0.2,
      });
    }
  } else {
    // Moving state — normal physics
    droplet.velocityY += 0.008;
    droplet.velocityY = Math.min(droplet.velocityY, 1.5);
    droplet.velocityX *= 0.995;

    // 2% per-frame chance of micro-friction (glass imperfections)
    if (Math.random() < 0.02) {
      droplet.velocityY *= 0.4 + Math.random() * 0.3;
    }

    // When slow, 5% chance to become stuck
    if (droplet.velocityY < 0.25 && Math.random() < 0.05) {
      droplet.stuck = true;
      droplet.mass = 0;
      droplet.releaseThreshold = 0.3 + Math.random() * 0.7;
    }

    // ~3% chance per frame to shed a residual bead
    if (Math.random() < 0.03) {
      residuals.push({
        x: droplet.x,
        y: droplet.y,
        radius: droplet.radius * (0.3 + Math.random() * 0.3),
        opacity: 0.3 + Math.random() * 0.2,
      });
    }
  }

  droplet.trail.push({ x: droplet.x, y: droplet.y, age: 0 });
  droplet.trail = droplet.trail
    .map((p) => ({ ...p, age: p.age + 1 }))
    .filter((p) => p.age < MAX_TRAIL);

  droplet.x += droplet.velocityX;
  droplet.y += droplet.velocityY;

  return droplet.y < canvasHeight + droplet.radius * 2;
}

// ============================================================================
// Bokeh Background
// ============================================================================

interface BokehCircle {
  x: number;
  y: number;
  radius: number;
  color: string;
  velocityX: number;
  velocityY: number;
  phase: number;
  brightness: number;
}

function createBokeh(
  canvasWidth: number,
  canvasHeight: number,
  colors: string[]
): BokehCircle {
  return {
    x: Math.random() * canvasWidth,
    y: Math.random() * canvasHeight,
    radius: 30 + Math.random() * 80,
    color: colors[Math.floor(Math.random() * colors.length)],
    velocityX: (Math.random() - 0.5) * 0.2,
    velocityY: (Math.random() - 0.5) * 0.2,
    phase: Math.random() * Math.PI * 2,
    brightness: 0.3 + Math.random() * 0.4,
  };
}

function updateBokeh(
  bokeh: BokehCircle,
  canvasWidth: number,
  canvasHeight: number,
  time: number
) {
  bokeh.x += bokeh.velocityX;
  bokeh.y += bokeh.velocityY;
  bokeh.brightness = 0.3 + Math.sin(time * 0.5 + bokeh.phase) * 0.15;

  if (bokeh.x < -bokeh.radius) bokeh.x = canvasWidth + bokeh.radius;
  if (bokeh.x > canvasWidth + bokeh.radius) bokeh.x = -bokeh.radius;
  if (bokeh.y < -bokeh.radius) bokeh.y = canvasHeight + bokeh.radius;
  if (bokeh.y > canvasHeight + bokeh.radius) bokeh.y = -bokeh.radius;
}

// ============================================================================
// GLSL Shaders
// ============================================================================

const BOKEH_VERT = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const BOKEH_FRAG = `
  uniform vec2 uBokehPos[12];
  uniform vec3 uBokehColor[12];
  uniform float uBokehRadius[12];
  uniform float uBokehBrightness[12];
  uniform vec2 uResolution;

  varying vec2 vUv;

  void main() {
    // Dark night gradient
    vec3 color = mix(
      vec3(0.039, 0.063, 0.125),
      vec3(0.031, 0.063, 0.094),
      vUv.y
    );
    // Slightly lighter mid-band
    float midBand = smoothstep(0.0, 0.5, vUv.y) * smoothstep(1.0, 0.5, vUv.y);
    color = mix(color, vec3(0.051, 0.082, 0.145), midBand * 0.5);

    vec2 fragCoord = vUv * uResolution;

    for (int i = 0; i < 12; i++) {
      vec2 diff = fragCoord - uBokehPos[i];
      float dist = length(diff);
      float r = uBokehRadius[i];
      if (dist > r * 2.0) continue;

      // Soft radial falloff
      float falloff = smoothstep(r, r * 0.1, dist);
      color += uBokehColor[i] * falloff * uBokehBrightness[i] * 0.6;

      // Soft outer glow
      float outerGlow = smoothstep(r * 2.0, r, dist);
      color += uBokehColor[i] * outerGlow * uBokehBrightness[i] * 0.15;
    }

    // Dim for out-of-focus glass effect
    color *= 0.85;

    gl_FragColor = vec4(color, 1.0);
  }
`;

const COMPOSITOR_VERT = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const COMPOSITOR_FRAG = /* glsl */ `
  uniform sampler2D tBackground;
  uniform vec4 uDroplets[${MAX_DROPLETS}];
  uniform vec3 uDropletDir[${MAX_DROPLETS}];
  uniform int uDropletCount;
  uniform vec2 uResolution;
  uniform float uTime;
  uniform float uBass;

  varying vec2 vUv;

  void main() {
    vec3 color = texture2D(tBackground, vUv).rgb;
    vec2 fragCoord = vUv * uResolution;

    for (int i = 0; i < ${MAX_DROPLETS}; i++) {
      if (i >= uDropletCount) break;

      vec2 center = uDroplets[i].xy;
      float radius = uDroplets[i].z;
      float opacity = uDroplets[i].w;

      vec2 dir = uDropletDir[i].xy;
      float stretch = uDropletDir[i].z;
      float halfLen = radius * stretch;

      vec2 diff = fragCoord - center;
      float maxDist = radius * 1.5 + halfLen;

      // Early rejection (squared distance avoids sqrt for far pixels)
      float distSq = dot(diff, diff);
      if (distSq > maxDist * maxDist) continue;

      // Project onto capsule axis
      float along = dot(diff, dir);
      float clampedAlong = clamp(along, -halfLen, halfLen);

      // t: 0 at trailing end, 1 at leading end (epsilon avoids div-by-zero)
      float t = (clampedAlong + halfLen + 0.001) / (2.0 * halfLen + 0.002);

      // Taper radius: full at leading end, 35% at trailing end
      float taperRadius = radius * mix(0.35, 1.0, t);
      // Branchless stationary fallback — pure circle when stretch ≈ 0
      taperRadius = mix(radius, taperRadius, step(0.01, stretch));

      // Nearest point on capsule centerline
      vec2 nearest = center + dir * clampedAlong;
      float capsuleDist = length(fragCoord - nearest);
      float nd = capsuleDist / taperRadius;

      // Edge softness — antialiased boundary
      float edge = smoothstep(1.0, 0.85, nd);
      if (edge < 0.001) continue;

      // --- Refraction: offset UV toward nearest capsule point ---
      vec2 refractDir = capsuleDist > 0.001
        ? (nearest - fragCoord) / capsuleDist
        : vec2(0.0);
      float refractStrength = (1.0 - nd * nd) * 0.03 * radius;
      vec2 refractedUv = vUv + refractDir * refractStrength / uResolution;

      // --- Chromatic aberration: sample RGB at offset UVs ---
      vec2 chromaOffset = refractDir * refractStrength * 0.4 * nd / uResolution;
      float r = texture2D(tBackground, refractedUv + chromaOffset).r;
      float g = texture2D(tBackground, refractedUv).g;
      float b = texture2D(tBackground, refractedUv - chromaOffset).b;
      vec3 refractedColor = vec3(r, g, b);

      // --- Subsurface scattering: brighten center ---
      float sss = smoothstep(1.0, 0.0, nd);
      sss = sss * sss;
      refractedColor *= 1.0 + sss * 0.5;

      // --- Caustic: bright spot near leading edge ---
      vec2 frontPt = center + dir * halfLen;
      vec2 causticCenter = frontPt + vec2(-radius * 0.2, -radius * 0.3);
      float causticDist = length(fragCoord - causticCenter) / radius;
      float caustic = exp(-causticDist * causticDist * 3.0) * 0.4;
      refractedColor += vec3(caustic);

      // --- Fresnel rim: edges reflect more ---
      float fresnel = pow(nd, 3.0) * 0.5;
      refractedColor = mix(refractedColor, vec3(0.7, 0.85, 1.0), fresnel);

      // --- Specular highlight: near leading edge ---
      vec2 specCenter = frontPt + vec2(-radius * 0.3, -radius * 0.3);
      float specDist = length(fragCoord - specCenter) / radius;
      float specular = exp(-specDist * specDist * 8.0) * 0.7;
      refractedColor += vec3(specular);

      // Blend with edge softness and opacity
      color = mix(color, refractedColor, edge * opacity);
    }

    gl_FragColor = vec4(color, 1.0);
  }
`;

// ============================================================================
// Compositor Material (shaderMaterial + extend for R3F JSX)
// ============================================================================

const CompositorMaterial = shaderMaterial(
  {
    tBackground: null as THREE.Texture | null,
    uDroplets: Array.from({ length: MAX_DROPLETS }, () => new THREE.Vector4()),
    uDropletDir: Array.from({ length: MAX_DROPLETS }, () => new THREE.Vector3()),
    uDropletCount: 0,
    uResolution: new THREE.Vector2(),
    uTime: 0,
    uBass: 0,
  },
  COMPOSITOR_VERT,
  COMPOSITOR_FRAG
);

extend({ CompositorMaterial });

// ============================================================================
// Helpers
// ============================================================================

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  return [
    parseInt(h.substring(0, 2), 16) / 255,
    parseInt(h.substring(2, 4), 16) / 255,
    parseInt(h.substring(4, 6), 16) / 255,
  ];
}

// ============================================================================
// Scene
// ============================================================================

function RainWindowScene({ palette }: { palette: string[] }) {
  const { gl, size } = useThree();
  useAudioAnalyser(true);

  const dropletsRef = useRef<Droplet[]>([]);
  const residualsRef = useRef<ResidualDrop[]>([]);
  const bokehRef = useRef<BokehCircle[]>([]);
  const timeRef = useRef(0);
  const smoothedBassRef = useRef(0);
  const compositorRef = useRef<THREE.ShaderMaterial>(null);

  // Pre-allocate droplet uniform arrays (modified in-place each frame)
  const dropletUniforms = useMemo(
    () => Array.from({ length: MAX_DROPLETS }, () => new THREE.Vector4()),
    []
  );
  const dirUniforms = useMemo(
    () => Array.from({ length: MAX_DROPLETS }, () => new THREE.Vector3()),
    []
  );

  // FBO render target (half resolution for performance — bokeh is blurry anyway)
  const renderTarget = useMemo(
    () =>
      new THREE.WebGLRenderTarget(
        Math.max(1, Math.floor(size.width / 2)),
        Math.max(1, Math.floor(size.height / 2)),
        { minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter }
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  // FBO scene: bokeh background quad + trail line segments
  const fbo = useMemo(() => {
    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 100);
    camera.position.z = 1;

    // — Bokeh background quad —
    const bokehMaterial = new THREE.ShaderMaterial({
      uniforms: {
        uBokehPos: {
          value: Array.from({ length: 12 }, () => new THREE.Vector2()),
        },
        uBokehColor: {
          value: Array.from({ length: 12 }, () => new THREE.Vector3(1, 1, 1)),
        },
        uBokehRadius: { value: new Float32Array(12).fill(50) },
        uBokehBrightness: { value: new Float32Array(12).fill(0.3) },
        uResolution: { value: new THREE.Vector2(1, 1) },
      },
      vertexShader: BOKEH_VERT,
      fragmentShader: BOKEH_FRAG,
      depthTest: false,
      depthWrite: false,
    });
    const bokehMesh = new THREE.Mesh(
      new THREE.PlaneGeometry(2, 2),
      bokehMaterial
    );
    scene.add(bokehMesh);

    // — Trail line segments —
    const trailPositions = new Float32Array(MAX_DROPLETS * MAX_TRAIL * 2 * 3);
    const trailGeometry = new THREE.BufferGeometry();
    trailGeometry.setAttribute(
      'position',
      new THREE.BufferAttribute(trailPositions, 3)
    );
    trailGeometry.setDrawRange(0, 0);

    const trailMaterial = new THREE.LineBasicMaterial({
      color: 0xc8dcff,
      transparent: true,
      opacity: 0.15,
      blending: THREE.AdditiveBlending,
      depthTest: false,
      depthWrite: false,
    });
    const trailMesh = new THREE.LineSegments(trailGeometry, trailMaterial);
    scene.add(trailMesh);

    return {
      scene,
      camera,
      bokehMaterial,
      trailPositions,
      trailGeometry,
    };
  }, []);

  // Initialize bokeh circles when palette or size changes
  useEffect(() => {
    bokehRef.current = Array.from({ length: 12 }, () =>
      createBokeh(size.width, size.height, palette)
    );
  }, [palette, size.width, size.height]);

  // Resize render target + update bokeh resolution uniform
  useEffect(() => {
    renderTarget.setSize(
      Math.max(1, Math.floor(size.width / 2)),
      Math.max(1, Math.floor(size.height / 2))
    );
    fbo.bokehMaterial.uniforms.uResolution.value.set(size.width, size.height);
  }, [size.width, size.height, renderTarget, fbo.bokehMaterial]);

  // Cleanup
  useEffect(() => {
    return () => {
      renderTarget.dispose();
      fbo.bokehMaterial.dispose();
      fbo.trailGeometry.dispose();
    };
  }, [renderTarget, fbo]);

  // Main animation loop
  useFrame(() => {
    const width = size.width;
    const height = size.height;
    if (width === 0 || height === 0) return;

    // --- Audio ---
    const audioData = getAudioData();
    const bass = audioData?.bass ?? 0;
    smoothedBassRef.current += (bass - smoothedBassRef.current) * 0.03;
    const smoothedBass = smoothedBassRef.current;

    timeRef.current += 0.016;

    // --- Update bokeh uniforms ---
    const bokehPos = fbo.bokehMaterial.uniforms.uBokehPos
      .value as THREE.Vector2[];
    const bokehColor = fbo.bokehMaterial.uniforms.uBokehColor
      .value as THREE.Vector3[];
    const bokehRadius = fbo.bokehMaterial.uniforms.uBokehRadius
      .value as Float32Array;
    const bokehBrightness = fbo.bokehMaterial.uniforms.uBokehBrightness
      .value as Float32Array;

    bokehRef.current.forEach((bokeh, i) => {
      updateBokeh(bokeh, width, height, timeRef.current);
      bokehPos[i].set(bokeh.x, height - bokeh.y);
      const [r, g, b] = hexToRgb(bokeh.color);
      bokehColor[i].set(r, g, b);
      bokehRadius[i] = bokeh.radius;
      bokehBrightness[i] = bokeh.brightness + smoothedBass * 0.2;
    });

    // --- Update trail vertices (NDC coords for ortho camera) ---
    const tp = fbo.trailPositions;
    let vertexCount = 0;
    const maxVerts = MAX_DROPLETS * MAX_TRAIL * 2;

    for (const droplet of dropletsRef.current) {
      if (droplet.trail.length < 2) continue;
      for (let j = 0; j < droplet.trail.length - 1; j++) {
        if (vertexCount >= maxVerts) break;
        const a = droplet.trail[j];
        const b = droplet.trail[j + 1];
        // Pixel coords → NDC (-1..1)
        const ax = (a.x / width) * 2 - 1;
        const ay = 1 - (a.y / height) * 2;
        const bx = (b.x / width) * 2 - 1;
        const by = 1 - (b.y / height) * 2;

        const idx = vertexCount * 3;
        tp[idx] = ax;
        tp[idx + 1] = ay;
        tp[idx + 2] = 0;
        tp[idx + 3] = bx;
        tp[idx + 4] = by;
        tp[idx + 5] = 0;
        vertexCount += 2;
      }
      if (vertexCount >= maxVerts) break;
    }

    (
      fbo.trailGeometry.attributes.position as THREE.BufferAttribute
    ).needsUpdate = true;
    fbo.trailGeometry.setDrawRange(0, vertexCount);

    // --- Render FBO (bokeh + trails → texture) ---
    gl.setRenderTarget(renderTarget);
    gl.render(fbo.scene, fbo.camera);
    gl.setRenderTarget(null);

    // --- Spawn droplets (rate slightly boosted by bass) ---
    const spawnRate = 0.02 + smoothedBass * 0.02;
    if (Math.random() < spawnRate) {
      dropletsRef.current.push(createDroplet(width));
    }

    // --- Update droplet physics ---
    const residuals = residualsRef.current;
    dropletsRef.current = dropletsRef.current.filter((d) =>
      updateDroplet(d, height, residuals)
    );
    if (dropletsRef.current.length > MAX_DROPLETS) {
      dropletsRef.current = dropletsRef.current.slice(-MAX_DROPLETS);
    }

    // --- Fade and cull residual beads ---
    for (let i = residuals.length - 1; i >= 0; i--) {
      residuals[i].opacity -= 0.001;
      if (residuals[i].opacity < 0.05) {
        residuals.splice(i, 1);
      }
    }
    if (residuals.length > 120) {
      residuals.splice(0, residuals.length - 120);
    }

    // --- Pack active droplets + residuals into uniform arrays ---
    const activeCount = Math.min(dropletsRef.current.length, MAX_DROPLETS);
    for (let i = 0; i < activeCount; i++) {
      const d = dropletsRef.current[i];
      dropletUniforms[i].set(d.x, height - d.y, d.radius, d.opacity);

      // Direction + stretch for capsule SDF
      const speed = Math.sqrt(d.velocityX * d.velocityX + d.velocityY * d.velocityY);
      if (speed > 0.001) {
        dirUniforms[i].set(
          d.velocityX / speed,        // normalized X
          -d.velocityY / speed,       // flip Y for shader coords
          Math.min(speed * 3, 4)      // stretch
        );
      } else {
        dirUniforms[i].set(0, -1, 0); // stationary — circle
      }
    }
    // Fill remaining slots with most recent residuals
    const residualSlots = MAX_DROPLETS - activeCount;
    const residualStart = Math.max(0, residuals.length - residualSlots);
    const residualCount = Math.min(residuals.length, residualSlots);
    for (let i = 0; i < residualCount; i++) {
      const r = residuals[residualStart + i];
      dropletUniforms[activeCount + i].set(r.x, height - r.y, r.radius, r.opacity);
      dirUniforms[activeCount + i].set(0, -1, 0); // residuals are stationary circles
    }
    const count = activeCount + residualCount;
    for (let i = count; i < MAX_DROPLETS; i++) {
      dropletUniforms[i].set(0, 0, 0, 0);
      dirUniforms[i].set(0, 0, 0);
    }

    // --- Update compositor uniforms ---
    const mat = compositorRef.current;
    if (mat) {
      mat.uniforms.tBackground.value = renderTarget.texture;
      mat.uniforms.uDroplets.value = dropletUniforms;
      mat.uniforms.uDropletDir.value = dirUniforms;
      mat.uniforms.uDropletCount.value = count;
      mat.uniforms.uResolution.value.set(width, height);
      mat.uniforms.uTime.value = timeRef.current;
      mat.uniforms.uBass.value = smoothedBass;
    }
  });

  return (
    <>
      <mesh>
        <planeGeometry args={[5, 5]} />
        {/* @ts-expect-error - Custom R3F element registered via extend() */}
        <compositorMaterial ref={compositorRef} />
      </mesh>

      {!mobile && (
        <AudioReactiveEffects
          enableBloom
          enableVignette
          bloomIntensity={0.8}
          bloomThreshold={0.6}
          vignetteIntensity={0.4}
        />
      )}

      <FrameScheduler />
    </>
  );
}

// ============================================================================
// Root Component
// ============================================================================

export function RainWindow({ artworkUrl }: VisualizerProps) {
  const palette = useArtworkPalette(artworkUrl);

  return (
    <div className="w-full h-full bg-[#0a1020]">
      <Canvas
        camera={{ position: [0, 0, 1], fov: 90 }}
        dpr={mobile ? [1, 1] : [1, 2]}
        gl={{ antialias: false, powerPreference: 'high-performance' }}
        frameloop={mobile ? 'demand' : 'always'}
      >
        <RainWindowScene palette={palette} />
      </Canvas>
    </div>
  );
}

// Register the visualizer
registerVisualizer(
  {
    id: 'rain-window',
    name: 'Rain Window',
    description: 'Peaceful rain on glass with soft bokeh lights',
    usesMetadata: true,
  },
  RainWindow
);
