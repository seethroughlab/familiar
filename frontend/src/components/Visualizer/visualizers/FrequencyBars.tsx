/**
 * Frequency Bars Visualizer - Enhanced spectrum analyzer.
 *
 * Features:
 * - 128 frequency bars with gradient colors
 * - Reflective floor effect
 * - Atmospheric fog
 * - Smooth animations
 */
import { useRef, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { useAudioAnalyser, getAudioData } from '../../../hooks/useAudioAnalyser';
import { registerVisualizer, type VisualizerProps } from '../types';
import { AudioReactiveEffects } from '../effects/AudioReactiveEffects';

function FrequencyBarsScene() {
  const meshesRef = useRef<THREE.Mesh[]>([]);
  const spotlightsRef = useRef<THREE.SpotLight[]>([]);
  const spotlightTargetsRef = useRef<THREE.Object3D[]>([]);
  const timeRef = useRef(0);

  useAudioAnalyser(true);

  const barCount = 128;
  const barWidth = 0.06;
  const spacing = 0.015;
  const totalWidth = barCount * (barWidth + spacing);

  // Create geometry once
  const geometry = useMemo(() => new THREE.BoxGeometry(barWidth, 1, barWidth), []);

  // Create materials with gradient colors - highly emissive for glow effect
  const materials = useMemo(() => {
    return Array.from({ length: barCount }, (_, i) => {
      const t = i / barCount;
      // Gradient from cyan through purple to pink
      const hue = 0.5 + t * 0.4;
      return new THREE.MeshStandardMaterial({
        color: new THREE.Color().setHSL(hue, 0.8, 0.5),
        emissive: new THREE.Color().setHSL(hue, 1.0, 0.4),
        emissiveIntensity: 0.6,
        metalness: 0.3,
        roughness: 0.4,
      });
    });
  }, []);

  useFrame((_, delta) => {
    timeRef.current += delta;

    if (!meshesRef.current.length) return;

    const audioData = getAudioData();
    const frequencyData = audioData?.frequencyData;
    const bass = audioData?.bass ?? 0;
    const mid = audioData?.mid ?? 0;
    const treble = audioData?.treble ?? 0;
    const step = frequencyData ? Math.floor(frequencyData.length / barCount) : 1;

    meshesRef.current.forEach((mesh, i) => {
      if (!mesh) return;

      let value: number;
      if (frequencyData) {
        const dataIndex = Math.min(i * step, frequencyData.length - 1);
        value = frequencyData[dataIndex] / 255;
      } else {
        // Fallback wave animation
        value = (Math.sin(timeRef.current * 3 + i * 0.15) + 1) / 2;
      }

      const targetHeight = 0.1 + value * 4;
      mesh.scale.y = THREE.MathUtils.lerp(mesh.scale.y, targetHeight, 0.25);
      mesh.position.y = mesh.scale.y / 2 - 1;

      // Update emissive intensity based on value - higher values for stronger glow
      const material = mesh.material as THREE.MeshStandardMaterial;
      material.emissiveIntensity = 0.5 + value * 1.2 + bass * 0.5;
    });

    // Animate spotlights - sweep across bars with audio reactivity
    spotlightsRef.current.forEach((spotlight, i) => {
      if (!spotlight) return;

      const target = spotlightTargetsRef.current[i];
      const phase = (i / 3) * Math.PI * 2; // Offset each spotlight
      const speed = 0.5 + bass * 0.5; // Speed up with bass
      const sweepWidth = totalWidth * 0.6;

      // Sweep pattern - each spotlight moves differently
      const xOffset = Math.sin(timeRef.current * speed + phase) * sweepWidth;
      const zOffset = Math.cos(timeRef.current * speed * 0.7 + phase) * 1.5;

      // Update spotlight position (sweeping from above and slightly behind bars)
      spotlight.position.x = xOffset;
      spotlight.position.z = -3 + zOffset; // Behind bars, pointing toward camera
      spotlight.position.y = 8 + Math.sin(timeRef.current * 0.3 + phase) * 2;

      // Link target if available and update its position
      if (target) {
        spotlight.target = target;
        target.position.x = xOffset;
        target.position.z = 0;
        target.position.y = 1; // Aim at middle of bars, not the floor
      }

      // Intensity pulses with different frequencies
      const pulseFactors = [bass, mid, treble];
      spotlight.intensity = 40 + pulseFactors[i] * 60;

      // Slight color shift based on audio
      const hueShift = pulseFactors[i] * 0.1;
      const baseHues = [0.85, 0.5, 0.75]; // Pink, Cyan, Purple
      spotlight.color.setHSL(baseHues[i] + hueShift, 0.9, 0.6);
    });
  });

  // Spotlight colors: pink, cyan, purple
  const spotlightColors = ['#ff66b2', '#06b6d4', '#a855f7'];

  return (
    <>
      <color attach="background" args={['#050510']} />
      <fog attach="fog" args={['#050510', 8, 20]} />

      {/* Ambient fill light - slightly brighter */}
      <ambientLight intensity={0.15} />

      {/* Subtle rim lights for depth */}
      <pointLight position={[8, 4, -3]} intensity={0.5} color="#a855f7" distance={15} />
      <pointLight position={[-8, 4, -3]} intensity={0.5} color="#06b6d4" distance={15} />

      {/* Moving spotlights with targets */}
      {spotlightColors.map((color, i) => (
        <group key={i}>
          <object3D
            ref={(el) => { if (el) spotlightTargetsRef.current[i] = el; }}
            position={[0, 1, 0]}
          />
          <spotLight
            ref={(el) => { if (el) spotlightsRef.current[i] = el; }}
            position={[(i - 1) * 3, 8, -3]}
            angle={0.4}
            penumbra={0.6}
            intensity={50}
            color={color}
            distance={20}
            decay={1.5}
            castShadow={false}
          />
        </group>
      ))}

      {/* Floor - matte to minimize spotlight reflections */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.5, 0]}>
        <planeGeometry args={[25, 25]} />
        <meshStandardMaterial
          color="#030308"
          metalness={0.05}
          roughness={0.95}
        />
      </mesh>

      {/* Frequency bars */}
      <group>
        {Array.from({ length: barCount }, (_, i) => (
          <mesh
            key={i}
            ref={(el) => { if (el) meshesRef.current[i] = el; }}
            geometry={geometry}
            material={materials[i]}
            position={[i * (barWidth + spacing) - totalWidth / 2, 0, 0]}
          />
        ))}
      </group>

      {/* Post-processing effects - lower threshold for bar glow */}
      <AudioReactiveEffects
        enableBloom
        enableVignette
        bloomIntensity={1.5}
        bloomThreshold={0.4}
        bloomRadius={0.6}
        vignetteIntensity={0.4}
      />
    </>
  );
}

export function FrequencyBars(_props: VisualizerProps) {
  return (
    <div className="w-full h-full">
      <Canvas
        camera={{ position: [0, 2, 6], fov: 50 }}
        gl={{ antialias: true, alpha: true }}
        dpr={[1, 2]}
      >
        <FrequencyBarsScene />
      </Canvas>
    </div>
  );
}

// Register the visualizer
registerVisualizer(
  {
    id: 'frequency-bars',
    name: 'Frequency Bars',
    description: 'Enhanced spectrum analyzer with 128 bars',
    usesMetadata: false,
  },
  FrequencyBars
);
