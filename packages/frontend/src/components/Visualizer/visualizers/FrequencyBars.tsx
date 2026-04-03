/**
 * Frequency Bars Visualizer - Circular starburst spectrum.
 *
 * Features:
 * - 128 radial bars arranged in a seamless ring
 * - Interleaved low/high frequency mapping to avoid a visible seam
 * - Strong center glow and portrait-friendly framing
 * - Shared FFT mapping across mobile and desktop with lighter mobile rendering
 */
import { useMemo, useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { useAudioAnalyser, getAudioData } from '../../../hooks/useAudioAnalyser';
import { isMobile } from '../../../utils/platform';
import type { VisualizerProps } from '../types';
import { AudioReactiveEffects } from '../effects/AudioReactiveEffects';
import { FrameScheduler } from '../effects/FrameScheduler';
import {
  getInterleavedSpectrumIndex,
  getRadialBarLayout,
  getRadialBarLength,
  sampleVisualizerBinValue,
} from '../../../player/audio/analysisMetrics';

const mobile = isMobile();
const BAR_COUNT = 128;

function softLimit(value: number, threshold: number, max: number): number {
  if (value <= threshold) return value;
  const excess = value - threshold;
  const range = max - threshold;
  return threshold + range * (1 - Math.exp(-excess / Math.max(0.0001, range)));
}

function getStarburstMagnitude(
  frequencyData: Uint8Array | undefined,
  index: number,
  totalBars: number,
  time: number,
): number {
  if (!frequencyData) {
    return (Math.sin(time * 2.4 + index * 0.32) + 1) / 2;
  }

  const mappedIndex = getInterleavedSpectrumIndex(index, totalBars);
  const sampled = sampleVisualizerBinValue(frequencyData, mappedIndex, totalBars, {
    usableBinsRatio: 0.84,
    lowFrequencyEmphasis: 0.24,
    minWindowSize: 2,
  });

  return Math.min(1, Math.max(0, sampled - 0.015) * 1.28);
}

function getRingColor(index: number, intensity: number): THREE.Color {
  const t = index / BAR_COUNT;
  const hue = 0.53 + Math.sin(t * Math.PI * 2) * 0.09;
  const saturation = 0.78 + Math.cos(t * Math.PI * 2) * 0.04;
  const lightness = Math.min(0.46 + intensity * 0.18, 0.7);
  return new THREE.Color().setHSL(hue, saturation, lightness);
}

function CenterHalo({ mobileMode }: { mobileMode: boolean }) {
  const coreRef = useRef<THREE.Mesh>(null);

  useFrame(() => {
    const audioData = getAudioData();
    const bass = audioData?.bass ?? 0;
    const mid = audioData?.mid ?? 0;
    const average = (audioData?.averageFrequency ?? 0) / 255;
    const pulse = softLimit(0.16 + bass * 0.8 + mid * 0.18, 0.48, 1.1);

    if (coreRef.current) {
      const scale = mobileMode
        ? 1.14 + pulse * 0.5
        : 0.96 + pulse * 0.34;
      coreRef.current.scale.setScalar(THREE.MathUtils.lerp(coreRef.current.scale.x, scale, 0.12));
      const material = coreRef.current.material as THREE.MeshBasicMaterial;
      material.opacity = THREE.MathUtils.lerp(
        material.opacity,
        mobileMode
          ? 0.19 + average * 0.18 + bass * 0.12
          : 0.14 + average * 0.12 + bass * 0.08,
        0.12,
      );
    }
  });

  return (
    <mesh ref={coreRef}>
      <sphereGeometry args={[mobileMode ? 0.92 : 0.7, 32, 32]} />
      <meshBasicMaterial color="#97d8ff" transparent opacity={mobileMode ? 0.2 : 0.16} toneMapped={false} />
    </mesh>
  );
}

function FrequencyBarsMobileScene() {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const timeRef = useRef(0);
  const currentLengths = useRef(new Float32Array(BAR_COUNT).fill(0.8));

  useAudioAnalyser(true);

  const dummy = useMemo(() => new THREE.Object3D(), []);
  const tempColor = useMemo(() => new THREE.Color(), []);
  const rotationAxis = useMemo(() => new THREE.Vector3(0, 0, 1), []);
  const geometry = useMemo(() => {
    const box = new THREE.BoxGeometry(1, 1, 1);
    box.translate(0, 0.5, 0);
    return box;
  }, []);

  useFrame((_, delta) => {
    if (!meshRef.current) return;
    timeRef.current += delta;

    const audioData = getAudioData();
    const frequencyData = audioData?.frequencyData;
    const bass = audioData?.bass ?? 0;

    for (let i = 0; i < BAR_COUNT; i++) {
      const magnitude = getStarburstMagnitude(frequencyData, i, BAR_COUNT, timeRef.current);
      const layout = getRadialBarLayout(i, BAR_COUNT, {
        baseThickness: 0.11,
        thicknessTaper: 0.28,
      });
      const targetLength = getRadialBarLength(magnitude, {
        minLength: 0.62,
        maxExtraLength: 4.25,
        responseCurve: 1.15,
      });
      currentLengths.current[i] = THREE.MathUtils.lerp(currentLengths.current[i], targetLength, 0.22);

      dummy.position.set(layout.directionX * 1.5, layout.directionY * 1.5, 0);
      dummy.quaternion.setFromAxisAngle(rotationAxis, layout.angle - Math.PI / 2);
      dummy.scale.set(layout.thickness, currentLengths.current[i], 0.18);
      dummy.updateMatrix();
      meshRef.current.setMatrixAt(i, dummy.matrix);

      const intensity = 0.35 + magnitude * 0.85 + bass * 0.3;
      tempColor.copy(getRingColor(i, intensity));
      meshRef.current.setColorAt(i, tempColor);
    }

    meshRef.current.instanceMatrix.needsUpdate = true;
    if (meshRef.current.instanceColor) {
      meshRef.current.instanceColor.needsUpdate = true;
    }
  });

  return (
    <>
      <color attach="background" args={['#050510']} />
      <ambientLight intensity={0.85} />
      <pointLight position={[0, 0, 4]} intensity={1.15} color="#7dd3fc" distance={12} />
      <pointLight position={[0, 0, -3]} intensity={0.7} color="#c084fc" distance={14} />

      <CenterHalo mobileMode />

      <instancedMesh ref={meshRef} args={[geometry, undefined, BAR_COUNT]}>
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>

      <FrameScheduler />
    </>
  );
}

function FrequencyBarsScene() {
  const meshesRef = useRef<THREE.Mesh[]>([]);
  const timeRef = useRef(0);

  useAudioAnalyser(true);

  const geometry = useMemo(() => {
    const box = new THREE.BoxGeometry(1, 1, 1);
    box.translate(0, 0.5, 0);
    return box;
  }, []);

  const materials = useMemo(() => {
    return Array.from({ length: BAR_COUNT }, (_, index) => {
      const color = getRingColor(index, 0.45);
      return new THREE.MeshStandardMaterial({
        color,
        emissive: color.clone(),
        emissiveIntensity: 0.68,
        metalness: 0.18,
        roughness: 0.3,
      });
    });
  }, []);

  useFrame((_, delta) => {
    timeRef.current += delta;

    const audioData = getAudioData();
    const frequencyData = audioData?.frequencyData;
    const bass = audioData?.bass ?? 0;
    const mid = audioData?.mid ?? 0;
    const treble = audioData?.treble ?? 0;

    meshesRef.current.forEach((mesh, index) => {
      if (!mesh) return;

      const magnitude = getStarburstMagnitude(frequencyData, index, BAR_COUNT, timeRef.current);
      const layout = getRadialBarLayout(index, BAR_COUNT, {
        baseThickness: 0.1,
        thicknessTaper: 0.2,
      });
      const length = getRadialBarLength(magnitude, {
        minLength: 0.56,
        maxExtraLength: 3.85,
        responseCurve: 1.18,
      });

      mesh.position.set(layout.directionX * 1.4, layout.directionY * 1.4, 0);
      mesh.rotation.z = layout.angle - Math.PI / 2;
      mesh.scale.x = layout.thickness;
      mesh.scale.y = THREE.MathUtils.lerp(mesh.scale.y, length, 0.2);
      mesh.scale.z = 0.16 + magnitude * 0.05;

      const material = mesh.material as THREE.MeshStandardMaterial;
      const rawIntensity = 0.54 + magnitude * 0.72 + bass * 0.22 + mid * 0.05;
      material.emissiveIntensity = softLimit(rawIntensity, 0.82, 1.2);
      material.metalness = 0.14 + treble * 0.18;
      material.roughness = 0.34 - treble * 0.12;
    });
  });

  return (
    <>
      <color attach="background" args={['#050510']} />
      <fog attach="fog" args={['#050510', 7, 18]} />

      <ambientLight intensity={0.24} />
      <pointLight position={[0, 0, 6]} intensity={1.3} color="#8bdcff" distance={18} />
      <pointLight position={[0, 0, -6]} intensity={0.95} color="#c18cff" distance={16} />

      <CenterHalo mobileMode={false} />

      <group>
        {Array.from({ length: BAR_COUNT }, (_, index) => (
          <mesh
            key={index}
            ref={(element) => {
              if (element) meshesRef.current[index] = element;
            }}
            geometry={geometry}
            material={materials[index]}
          />
        ))}
      </group>

      <AudioReactiveEffects
        enableBloom
        enableVignette
        bloomIntensity={1.1}
        bloomThreshold={0.52}
        bloomRadius={0.7}
        vignetteIntensity={0.32}
        halfResolution={false}
      />
    </>
  );
}

export function FrequencyBars(_props: VisualizerProps) {
  return (
    <div className="w-full h-full">
      <Canvas
        camera={{ position: [0, 0, mobile ? 10.5 : 9.25], fov: mobile ? 40 : 44 }}
        gl={{ antialias: !mobile, alpha: true }}
        dpr={mobile ? [1, 1.5] : [1, 2]}
        frameloop={mobile ? 'demand' : 'always'}
      >
        {mobile ? <FrequencyBarsMobileScene /> : <FrequencyBarsScene />}
      </Canvas>
    </div>
  );
}

export default FrequencyBars;
