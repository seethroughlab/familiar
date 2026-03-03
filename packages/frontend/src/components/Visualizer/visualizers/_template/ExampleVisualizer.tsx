/**
 * Example Visualizer Template
 *
 * A simple Three.js visualizer demonstrating the Visualizer API.
 * Copy this file and modify it to create your own visualizer.
 *
 * Features demonstrated:
 * - Real-time audio reactivity (bass, mid, treble)
 * - BPM synchronization
 * - Color extraction from artwork
 * - Track metadata display
 */
import { useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { type VisualizerProps } from '../../types';
import {
  useAudioAnalyser,
  getAudioData,
  useArtworkPalette,
  useBeatSync,
} from '../../hooks';

/**
 * Inner scene component - runs inside the Canvas.
 * Use getAudioData() in useFrame for performance.
 */
function ExampleScene({
  palette,
  bpm,
  currentTime,
}: {
  palette: string[];
  bpm: number | null;
  currentTime: number;
}) {
  const meshRef = useRef<THREE.Mesh>(null);
  const ringRef = useRef<THREE.Mesh>(null);

  // Enable audio analysis
  useAudioAnalyser(true);

  // Get beat sync data (available for use in animations)
  // const { beatProgress, onBeat } = useBeatSync(bpm, currentTime);
  useBeatSync(bpm, currentTime);

  // Animation loop
  useFrame((_, delta) => {
    if (!meshRef.current) return;

    // Get real-time audio data (doesn't trigger re-renders)
    const audioData = getAudioData();
    const bass = audioData?.bass ?? 0;
    const mid = audioData?.mid ?? 0;
    const treble = audioData?.treble ?? 0;

    // Rotate the mesh
    meshRef.current.rotation.x += delta * 0.5;
    meshRef.current.rotation.y += delta * 0.3;

    // Scale based on bass
    const targetScale = 1 + bass * 0.5;
    meshRef.current.scale.lerp(
      new THREE.Vector3(targetScale, targetScale, targetScale),
      0.1
    );

    // Update ring
    if (ringRef.current) {
      ringRef.current.rotation.z += delta * (0.2 + mid * 0.5);
      const ringScale = 2 + treble * 0.5;
      ringRef.current.scale.setScalar(ringScale);
    }
  });

  // Convert hex color to Three.js color
  const primaryColor = new THREE.Color(palette[0]);
  const secondaryColor = new THREE.Color(palette[1]);

  return (
    <>
      {/* Background */}
      <color attach="background" args={['#0a0015']} />

      {/* Lighting */}
      <ambientLight intensity={0.3} />
      <pointLight position={[5, 5, 5]} intensity={1} color={palette[0]} />
      <pointLight position={[-5, -5, -5]} intensity={0.5} color={palette[1]} />

      {/* Main mesh - reacts to bass */}
      <mesh ref={meshRef}>
        <icosahedronGeometry args={[1, 1]} />
        <meshStandardMaterial
          color={primaryColor}
          emissive={primaryColor}
          emissiveIntensity={0.3}
          wireframe
        />
      </mesh>

      {/* Ring - reacts to treble */}
      <mesh ref={ringRef} position={[0, 0, -0.5]}>
        <torusGeometry args={[1, 0.02, 16, 100]} />
        <meshBasicMaterial
          color={secondaryColor}
          transparent
          opacity={0.8}
        />
      </mesh>
    </>
  );
}

/**
 * Main visualizer component.
 * Receives all available data via VisualizerProps.
 */
export function ExampleVisualizer({
  track,
  artworkUrl,
  features,
  currentTime,
}: VisualizerProps) {
  // Extract colors from artwork
  const palette = useArtworkPalette(artworkUrl);

  return (
    <div className="w-full h-full relative">
      {/* Three.js Canvas */}
      <Canvas
        camera={{ position: [0, 0, 4], fov: 60 }}
        gl={{ antialias: true, alpha: true }}
      >
        <ExampleScene
          palette={palette}
          bpm={features?.bpm ?? null}
          currentTime={currentTime}
        />
      </Canvas>

      {/* Optional: Track info overlay */}
      {track && (
        <div className="absolute bottom-4 left-4 text-white/50 text-sm pointer-events-none">
          <div className="font-medium">{track.title}</div>
          <div className="text-xs">{track.artist}</div>
          {features?.bpm && (
            <div className="text-xs mt-1">{Math.round(features.bpm)} BPM</div>
          )}
        </div>
      )}
    </div>
  );
}

// To register this visualizer, add to your file:
// import { registerVisualizer } from '../../types';
// registerVisualizer(
//   {
//     id: 'example-visualizer',
//     name: 'Example Visualizer',
//     description: 'Template visualizer demonstrating the API',
//     usesMetadata: true,
//     author: 'Familiar',
//   },
//   ExampleVisualizer
// );
