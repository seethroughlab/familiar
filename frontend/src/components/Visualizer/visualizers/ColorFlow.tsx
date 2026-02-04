/**
 * Color Flow Visualizer - Enhanced with GPU particles, reflections, and post-processing.
 *
 * Features:
 * - 10,000 GPU-instanced particles with curl noise flow
 * - Reflective ground plane
 * - Glowing ring structures that pulse with audio
 * - Heavy bloom and chromatic aberration
 * - Colors extracted from album artwork
 */
import { useRef, useMemo, useEffect, useState, memo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { MeshReflectorMaterial } from '@react-three/drei';
import * as THREE from 'three';
import { useAudioAnalyser, getAudioData } from '../../../hooks/useAudioAnalyser';
import { extractPalette } from '../../../utils/colorExtraction';
import { registerVisualizer, type VisualizerProps } from '../types';
import { AudioReactiveEffects } from '../effects/AudioReactiveEffects';

const DEFAULT_PALETTE = ['#a855f7', '#06b6d4', '#22c55e', '#f59e0b', '#ec4899'];


// GPU Flow Particles using instanced mesh - vertical stream of light
function FlowParticles({ palette }: { palette: string[] }) {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  useAudioAnalyser(true);
  const timeRef = useRef(0);
  const count = 10000;

  const { positions, velocities, phases, colorIndices } = useMemo(() => {
    const positions = new Float32Array(count * 3);
    const velocities = new Float32Array(count * 3);
    const phases = new Float32Array(count);
    const colorIndices = new Float32Array(count);

    for (let i = 0; i < count; i++) {
      // Distribute in a narrower column for vertical flow emphasis
      const angle = Math.random() * Math.PI * 2;
      const radius = Math.random() * 2.5 + 0.3; // Narrower spread
      const height = (Math.random() - 0.5) * 10; // Taller range

      positions[i * 3] = Math.cos(angle) * radius;
      positions[i * 3 + 1] = height;
      positions[i * 3 + 2] = Math.sin(angle) * radius;

      // Stronger upward velocity, reduced horizontal drift
      velocities[i * 3] = (Math.random() - 0.5) * 0.01;
      velocities[i * 3 + 1] = Math.random() * 0.04 + 0.03; // Increased from 0.01-0.03 to 0.03-0.07
      velocities[i * 3 + 2] = (Math.random() - 0.5) * 0.01;

      phases[i] = Math.random() * Math.PI * 2;
      colorIndices[i] = Math.floor(Math.random() * palette.length);
    }

    return { positions, velocities, phases, colorIndices };
  }, [count, palette.length]);

  const paletteColors = useMemo(
    () => palette.map((c) => new THREE.Color(c)),
    [palette]
  );

  const dummy = useMemo(() => new THREE.Object3D(), []);

  // Simplex-like noise function
  const noise = (x: number, y: number, z: number, t: number) => {
    return (
      Math.sin(x * 1.5 + t) * Math.cos(y * 1.2 + t * 0.7) +
      Math.sin(z * 1.8 + t * 0.5) * 0.5
    );
  };

  useFrame((_, delta) => {
    if (!meshRef.current) return;

    timeRef.current += delta;
    const time = timeRef.current;

    const audioData = getAudioData();
    const bass = audioData?.bass ?? 0;
    const mid = audioData?.mid ?? 0;
    const treble = audioData?.treble ?? 0;
    const intensity = (audioData?.averageFrequency ?? 0) / 255;

    for (let i = 0; i < count; i++) {
      const i3 = i * 3;
      let x = positions[i3];
      let y = positions[i3 + 1];
      let z = positions[i3 + 2];

      const phase = phases[i];

      // Simplified flow - emphasize vertical motion
      const flowX = noise(y * 0.2, z * 0.2, x * 0.2, time * 0.2);
      const flowZ = noise(x * 0.2, y * 0.2, z * 0.2, time * 0.2 + 200);

      const speed = 0.015 * (1 + bass * 1.5 + intensity);

      // Horizontal drift is subtle
      x += flowX * speed * 0.3 + velocities[i3] * (1 + mid * 0.5);
      z += flowZ * speed * 0.3 + velocities[i3 + 2] * (1 + mid * 0.5);

      // Strong upward flow
      y += velocities[i3 + 1] * (1 + bass * 2 + treble);

      // Gentle spiral - reduced speed
      const angle = Math.atan2(z, x);
      const radius = Math.sqrt(x * x + z * z);
      const spiralSpeed = 0.002 + bass * 0.008;
      const newAngle = angle + spiralSpeed;

      x = Math.cos(newAngle) * radius;
      z = Math.sin(newAngle) * radius;

      // Vertical bounds with wrap-around - taller range
      if (y > 5) {
        y = -5;
        // Respawn in narrow column
        const respawnAngle = Math.random() * Math.PI * 2;
        const respawnRadius = Math.random() * 2.5 + 0.3;
        x = Math.cos(respawnAngle) * respawnRadius;
        z = Math.sin(respawnAngle) * respawnRadius;
      }
      if (y < -5) y = 5;

      // Radial bounds - keep column narrow
      const dist = Math.sqrt(x * x + z * z);
      if (dist > 3.5) {
        const scale = 3.5 / dist;
        x *= scale * 0.9;
        z *= scale * 0.9;
      }

      positions[i3] = x;
      positions[i3 + 1] = y;
      positions[i3 + 2] = z;

      // Update instance
      const size = 0.018 * (1 + intensity * 0.5 + Math.sin(time + phase) * 0.2);
      dummy.position.set(x, y, z);
      dummy.scale.setScalar(size);
      dummy.updateMatrix();
      meshRef.current.setMatrixAt(i, dummy.matrix);

      // Update color with audio reactivity - add height-based color variation
      const heightRatio = (y + 5) / 10; // 0 at bottom, 1 at top
      const colorIdx = Math.floor(colorIndices[i] + heightRatio * 2) % paletteColors.length;
      const baseColor = paletteColors[colorIdx];
      const dynamicColor = baseColor.clone();

      // Brighten based on audio and height
      dynamicColor.offsetHSL(0, 0, intensity * 0.3 + heightRatio * 0.1);
      meshRef.current.setColorAt(i, dynamicColor);
    }

    meshRef.current.instanceMatrix.needsUpdate = true;
    if (meshRef.current.instanceColor) {
      meshRef.current.instanceColor.needsUpdate = true;
    }
  });

  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, count]}>
      <sphereGeometry args={[1, 6, 6]} />
      <meshBasicMaterial
        transparent
        opacity={0.9}
        toneMapped={false}
        blending={THREE.AdditiveBlending}
      />
    </instancedMesh>
  );
}


// Reflective ground - wrapped in memo to prevent HMR serialization issues
const ReflectiveGround = memo(function ReflectiveGround({ palette }: { palette: string[] }) {
  const groundColor = useMemo(() => {
    const color = new THREE.Color(palette[0]);
    color.multiplyScalar(0.1);
    return color;
  }, [palette]);

  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -2.5, 0]}>
      <planeGeometry args={[20, 20]} />
      <MeshReflectorMaterial
        blur={[400, 100]}
        resolution={1024}
        mixBlur={1}
        mixStrength={0.5}
        depthScale={1}
        minDepthThreshold={0.85}
        color={groundColor}
        metalness={0.6}
        roughness={0.4}
        mirror={0.5}
      />
    </mesh>
  );
});

// Scene with fog and lighting - focused on vertical particle flow
function ColorFlowScene({ palette }: { palette: string[] }) {
  useAudioAnalyser(true);

  const bgColor = useMemo(() => {
    const color = new THREE.Color(palette[0]);
    color.multiplyScalar(0.03);
    return color;
  }, [palette]);

  const fogColor = useMemo(() => {
    const color = new THREE.Color(palette[0]);
    color.multiplyScalar(0.08);
    return color;
  }, [palette]);

  return (
    <>
      <color attach="background" args={[bgColor]} />
      <fog attach="fog" args={[fogColor, 4, 18]} />

      <ambientLight intensity={0.2} />
      {/* Lights positioned to illuminate the vertical column */}
      <pointLight position={[3, 3, 3]} intensity={1} color={palette[0]} />
      <pointLight position={[-3, 0, -3]} intensity={0.8} color={palette[1] || palette[0]} />
      <pointLight position={[0, -3, 2]} intensity={0.6} color={palette[2] || palette[0]} />
      <pointLight position={[0, 4, 0]} intensity={0.5} color={palette[3] || palette[0]} />

      {/* Only particles and ground - no central object */}
      <FlowParticles palette={palette} />
      <ReflectiveGround palette={palette} />

      {/* Post-processing */}
      <AudioReactiveEffects
        enableBloom
        enableVignette
        bloomIntensity={1.8}
        bloomThreshold={0.3}
        vignetteIntensity={0.5}
      />
    </>
  );
}

export function ColorFlow({ artworkUrl }: VisualizerProps) {
  const [palette, setPalette] = useState<string[]>(DEFAULT_PALETTE);

  useEffect(() => {
    if (artworkUrl) {
      extractPalette(artworkUrl, 5).then(setPalette);
    } else {
      setPalette(DEFAULT_PALETTE);
    }
  }, [artworkUrl]);

  return (
    <div className="w-full h-full">
      <Canvas
        camera={{ position: [0, 0.5, 6], fov: 55 }}
        gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
        dpr={[1, 2]}
      >
        <ColorFlowScene palette={palette} />
      </Canvas>
    </div>
  );
}

// Register the visualizer
registerVisualizer(
  {
    id: 'color-flow',
    name: 'Color Flow',
    description: 'Vertical stream of light with reflective floor',
    usesMetadata: true,
  },
  ColorFlow
);
