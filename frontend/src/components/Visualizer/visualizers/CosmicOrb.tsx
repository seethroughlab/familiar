/**
 * Cosmic Orb Visualizer - Enhanced with GPU particles and post-processing.
 *
 * Features:
 * - 5000 GPU-instanced particles with curl noise motion
 * - Custom orb shader with Fresnel rim glow and vertex displacement
 * - Post-processing: bloom, chromatic aberration, noise, vignette
 * - 256-segment circular waveform with glow
 */
import { useRef, useMemo } from 'react';
import { Canvas, useFrame, extend } from '@react-three/fiber';
import { OrbitControls, shaderMaterial } from '@react-three/drei';
import * as THREE from 'three';
import { useAudioAnalyser, getAudioData } from '../../../hooks/useAudioAnalyser';
import { registerVisualizer, type VisualizerProps } from '../types';
import { AudioReactiveEffects } from '../effects/AudioReactiveEffects';
import { GPUParticles } from '../effects/GPUParticles';

// Custom orb shader with Fresnel glow and vertex displacement
const OrbMaterial = shaderMaterial(
  {
    uTime: 0,
    uBass: 0,
    uMid: 0,
    uTreble: 0,
    uIntensity: 0,
    uColor: new THREE.Color('#4a00e0'),
    uEmissive: new THREE.Color('#8e2de2'),
  },
  // Vertex shader
  `
    uniform float uTime;
    uniform float uBass;
    uniform float uMid;

    varying vec3 vNormal;
    varying vec3 vPosition;
    varying float vDisplacement;

    // Simplex noise
    vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
    vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
    vec4 permute(vec4 x) { return mod289(((x*34.0)+1.0)*x); }
    vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

    float snoise(vec3 v) {
      const vec2 C = vec2(1.0/6.0, 1.0/3.0);
      const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);

      vec3 i = floor(v + dot(v, C.yyy));
      vec3 x0 = v - i + dot(i, C.xxx);

      vec3 g = step(x0.yzx, x0.xyz);
      vec3 l = 1.0 - g;
      vec3 i1 = min(g.xyz, l.zxy);
      vec3 i2 = max(g.xyz, l.zxy);

      vec3 x1 = x0 - i1 + C.xxx;
      vec3 x2 = x0 - i2 + C.yyy;
      vec3 x3 = x0 - D.yyy;

      i = mod289(i);
      vec4 p = permute(permute(permute(
        i.z + vec4(0.0, i1.z, i2.z, 1.0))
        + i.y + vec4(0.0, i1.y, i2.y, 1.0))
        + i.x + vec4(0.0, i1.x, i2.x, 1.0));

      float n_ = 0.142857142857;
      vec3 ns = n_ * D.wyz - D.xzx;

      vec4 j = p - 49.0 * floor(p * ns.z * ns.z);

      vec4 x_ = floor(j * ns.z);
      vec4 y_ = floor(j - 7.0 * x_);

      vec4 x = x_ *ns.x + ns.yyyy;
      vec4 y = y_ *ns.x + ns.yyyy;
      vec4 h = 1.0 - abs(x) - abs(y);

      vec4 b0 = vec4(x.xy, y.xy);
      vec4 b1 = vec4(x.zw, y.zw);

      vec4 s0 = floor(b0)*2.0 + 1.0;
      vec4 s1 = floor(b1)*2.0 + 1.0;
      vec4 sh = -step(h, vec4(0.0));

      vec4 a0 = b0.xzyw + s0.xzyw*sh.xxyy;
      vec4 a1 = b1.xzyw + s1.xzyw*sh.zzww;

      vec3 p0 = vec3(a0.xy, h.x);
      vec3 p1 = vec3(a0.zw, h.y);
      vec3 p2 = vec3(a1.xy, h.z);
      vec3 p3 = vec3(a1.zw, h.w);

      vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2,p2), dot(p3,p3)));
      p0 *= norm.x;
      p1 *= norm.y;
      p2 *= norm.z;
      p3 *= norm.w;

      vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
      m = m * m;
      return 42.0 * dot(m*m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));
    }

    void main() {
      vNormal = normalize(normalMatrix * normal);
      vPosition = position;

      // Multi-octave noise displacement
      float noise1 = snoise(position * 2.0 + uTime * 0.5);
      float noise2 = snoise(position * 4.0 - uTime * 0.3) * 0.5;
      float noise3 = snoise(position * 8.0 + uTime * 0.7) * 0.25;

      float displacement = (noise1 + noise2 + noise3) * (0.1 + uBass * 0.3);
      vDisplacement = displacement;

      vec3 newPosition = position + normal * displacement;

      gl_Position = projectionMatrix * modelViewMatrix * vec4(newPosition, 1.0);
    }
  `,
  // Fragment shader
  `
    uniform float uTime;
    uniform float uBass;
    uniform float uMid;
    uniform float uTreble;
    uniform float uIntensity;
    uniform vec3 uColor;
    uniform vec3 uEmissive;

    varying vec3 vNormal;
    varying vec3 vPosition;
    varying float vDisplacement;

    void main() {
      // Fresnel rim lighting
      vec3 viewDirection = normalize(cameraPosition - vPosition);
      float fresnel = pow(1.0 - dot(viewDirection, vNormal), 3.0);
      fresnel = fresnel * (0.5 + uTreble * 0.5);

      // Base color with displacement influence
      vec3 baseColor = mix(uColor, uEmissive, vDisplacement * 2.0 + 0.5);

      // Emissive glow based on audio
      float emissiveStrength = 0.3 + uIntensity * 0.7 + uBass * 0.5;
      vec3 emissiveColor = uEmissive * emissiveStrength;

      // Rim glow color (cyan)
      vec3 rimColor = vec3(0.0, 1.0, 1.0) * fresnel * (1.0 + uBass);

      // Combine
      vec3 finalColor = baseColor * 0.3 + emissiveColor + rimColor;

      // Add pulsing based on mid frequencies
      finalColor += uEmissive * uMid * 0.3 * sin(uTime * 10.0 + vPosition.y * 5.0);

      gl_FragColor = vec4(finalColor, 1.0);
    }
  `
);

extend({ OrbMaterial });

// Enhanced circular waveform with glow
function CircularWaveform() {
  const meshRef = useRef<THREE.Line<THREE.BufferGeometry, THREE.LineBasicMaterial>>(null);
  useAudioAnalyser(true);
  const timeRef = useRef(0);

  const geometry = useMemo(() => {
    const segments = 256;
    const geo = new THREE.BufferGeometry();
    const positions = new Float32Array(segments * 3);

    for (let i = 0; i < segments; i++) {
      const angle = (i / segments) * Math.PI * 2;
      positions[i * 3] = Math.cos(angle) * 2;
      positions[i * 3 + 1] = Math.sin(angle) * 2;
      positions[i * 3 + 2] = 0;
    }

    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    return geo;
  }, []);

  useFrame((_, delta) => {
    if (!meshRef.current) return;
    timeRef.current += delta;

    const audioData = getAudioData();
    const positions = meshRef.current.geometry.attributes.position;
    const frequencyData = audioData?.frequencyData;
    const bass = audioData?.bass ?? 0;
    const segments = positions.count;

    for (let i = 0; i < segments; i++) {
      const dataIndex = frequencyData
        ? Math.floor((i / segments) * frequencyData.length)
        : 0;
      const value = frequencyData ? frequencyData[dataIndex] / 255 : 0;
      const angle = (i / segments) * Math.PI * 2;

      // Add secondary wave oscillation
      const wave = Math.sin(timeRef.current * 3 + i * 0.1) * 0.15 * (1 + bass);
      const radius = 2.0 + value * 1.8 + bass * 0.6 + wave;

      positions.setXYZ(i, Math.cos(angle) * radius, Math.sin(angle) * radius, 0);
    }
    positions.needsUpdate = true;

    // Rotate
    meshRef.current.rotation.z += 0.002 + bass * 0.01;
  });

  return (
    <primitive object={new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: '#00ffff', transparent: true, opacity: 0.9 }))} ref={meshRef} />
  );
}

// Second waveform ring with phase offset
function SecondaryWaveform() {
  const meshRef = useRef<THREE.Line<THREE.BufferGeometry, THREE.LineBasicMaterial>>(null);
  useAudioAnalyser(true);
  const timeRef = useRef(0);

  const geometry = useMemo(() => {
    const segments = 256;
    const geo = new THREE.BufferGeometry();
    const positions = new Float32Array(segments * 3);

    for (let i = 0; i < segments; i++) {
      const angle = (i / segments) * Math.PI * 2;
      positions[i * 3] = Math.cos(angle) * 2.5;
      positions[i * 3 + 1] = Math.sin(angle) * 2.5;
      positions[i * 3 + 2] = 0;
    }

    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    return geo;
  }, []);

  useFrame((_, delta) => {
    if (!meshRef.current) return;
    timeRef.current += delta;

    const audioData = getAudioData();
    const positions = meshRef.current.geometry.attributes.position;
    const frequencyData = audioData?.frequencyData;
    const mid = audioData?.mid ?? 0;
    const segments = positions.count;

    for (let i = 0; i < segments; i++) {
      const dataIndex = frequencyData
        ? Math.floor(((i + segments / 2) % segments / segments) * frequencyData.length)
        : 0;
      const value = frequencyData ? frequencyData[dataIndex] / 255 : 0;
      const angle = (i / segments) * Math.PI * 2;

      const wave = Math.cos(timeRef.current * 2 + i * 0.15) * 0.2 * (1 + mid);
      const radius = 2.8 + value * 1.5 + mid * 0.4 + wave;

      positions.setXYZ(i, Math.cos(angle) * radius, Math.sin(angle) * radius, 0);
    }
    positions.needsUpdate = true;

    // Counter-rotate
    meshRef.current.rotation.z -= 0.001 + mid * 0.005;
  });

  return (
    <primitive object={new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: '#a855f7', transparent: true, opacity: 0.6 }))} ref={meshRef} />
  );
}

// Central orb with custom shader
function ReactiveOrb() {
  const meshRef = useRef<THREE.Mesh>(null);
  const materialRef = useRef<THREE.ShaderMaterial>(null);
  useAudioAnalyser(true);

  useFrame((_, delta) => {
    if (!materialRef.current) return;

    const audioData = getAudioData();
    const bass = audioData?.bass ?? 0;
    const mid = audioData?.mid ?? 0;
    const treble = audioData?.treble ?? 0;
    const intensity = (audioData?.averageFrequency ?? 0) / 255;

    // Update shader uniforms
    materialRef.current.uniforms.uTime.value += delta;
    materialRef.current.uniforms.uBass.value = bass;
    materialRef.current.uniforms.uMid.value = mid;
    materialRef.current.uniforms.uTreble.value = treble;
    materialRef.current.uniforms.uIntensity.value = intensity;

    // Scale based on bass
    if (meshRef.current) {
      const targetScale = 1 + bass * 0.3;
      meshRef.current.scale.setScalar(
        THREE.MathUtils.lerp(meshRef.current.scale.x, targetScale, 0.1)
      );
      meshRef.current.rotation.x += 0.005 + mid * 0.01;
      meshRef.current.rotation.y += 0.008 + treble * 0.01;
    }
  });

  return (
    <mesh ref={meshRef}>
      <icosahedronGeometry args={[1.2, 4]} />
      {/* @ts-expect-error - Custom R3F element registered via extend() */}
      <orbMaterial
        ref={materialRef}
        transparent
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

// Inner glowing core
function GlowingCore() {
  const meshRef = useRef<THREE.Mesh>(null);
  useAudioAnalyser(true);

  useFrame(() => {
    if (!meshRef.current) return;

    const audioData = getAudioData();
    const bass = audioData?.bass ?? 0;
    const scale = 0.4 + bass * 0.3; // Increased base size
    meshRef.current.scale.setScalar(scale);

    const material = meshRef.current.material as THREE.MeshBasicMaterial;
    material.opacity = 0.6 + bass * 0.4;
  });

  return (
    <mesh ref={meshRef}>
      <sphereGeometry args={[1, 32, 32]} />
      <meshBasicMaterial
        color="#ffffff"
        transparent
        opacity={0.6}
      />
    </mesh>
  );
}

// Starfield background for cosmic depth
function Starfield() {
  const starsRef = useRef<THREE.Points>(null);
  const timeRef = useRef(0);

  const { positions, sizes, twinklePhases } = useMemo(() => {
    const count = 500;
    const positions = new Float32Array(count * 3);
    const sizes = new Float32Array(count);
    const twinklePhases = new Float32Array(count);

    for (let i = 0; i < count; i++) {
      // Distribute stars on a large sphere
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      const radius = 25 + Math.random() * 15; // Between 25-40 units away

      positions[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = radius * Math.cos(phi);

      sizes[i] = Math.random() * 0.5 + 0.2;
      twinklePhases[i] = Math.random() * Math.PI * 2;
    }

    return { positions, sizes, twinklePhases };
  }, []);

  const geometry = useMemo(() => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geo.setAttribute('size', new THREE.BufferAttribute(sizes, 1));
    return geo;
  }, [positions, sizes]);

  useFrame((_, delta) => {
    if (!starsRef.current) return;
    timeRef.current += delta;

    // Subtle twinkle effect by modulating opacity
    const sizeAttr = starsRef.current.geometry.attributes.size;
    for (let i = 0; i < sizes.length; i++) {
      const twinkle = Math.sin(timeRef.current * 2 + twinklePhases[i]) * 0.3 + 0.7;
      sizeAttr.setX(i, sizes[i] * twinkle);
    }
    sizeAttr.needsUpdate = true;

    // Very slow rotation
    starsRef.current.rotation.y += delta * 0.01;
  });

  return (
    <points ref={starsRef} geometry={geometry}>
      <pointsMaterial
        size={0.3}
        sizeAttenuation
        color="#ffffff"
        transparent
        opacity={0.8}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}

// Main visualizer scene with all effects
function CosmicOrbScene() {
  useAudioAnalyser(true);

  return (
    <>
      <color attach="background" args={['#020208']} />
      <ambientLight intensity={0.2} />
      <pointLight position={[10, 10, 10]} intensity={1} color="#a855f7" />
      <pointLight position={[-10, -10, 5]} intensity={0.8} color="#06b6d4" />

      {/* Starfield for cosmic depth */}
      <Starfield />

      <GlowingCore />
      <ReactiveOrb />
      <CircularWaveform />
      <SecondaryWaveform />

      {/* GPU Particles - reduced count, pushed outward for more empty space around orb */}
      <GPUParticles
        count={3000}
        size={0.012}
        color="#a855f7"
        secondaryColor="#06b6d4"
        spread={8}
        speed={0.6}
        audioData={null}
        behavior="orbit"
        opacity={0.6}
      />

      <OrbitControls
        enableZoom={false}
        enablePan={false}
        autoRotate
        autoRotateSpeed={0.3}
        maxPolarAngle={Math.PI / 1.5}
        minPolarAngle={Math.PI / 3}
      />

      {/* Post-processing effects */}
      <AudioReactiveEffects
        enableBloom
        enableVignette
        bloomIntensity={1.2}
        bloomThreshold={0.6}
        vignetteIntensity={0.4}
      />
    </>
  );
}

export function CosmicOrb(_props: VisualizerProps) {
  return (
    <div className="w-full h-full">
      <Canvas
        camera={{ position: [0, 0, 6], fov: 60 }}
        gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
        dpr={[1, 2]}
      >
        <CosmicOrbScene />
      </Canvas>
    </div>
  );
}

// Register the visualizer
registerVisualizer(
  {
    id: 'cosmic-orb',
    name: 'Cosmic Orb',
    description: 'Enhanced orb with GPU particles and effects',
    usesMetadata: false,
  },
  CosmicOrb
);
