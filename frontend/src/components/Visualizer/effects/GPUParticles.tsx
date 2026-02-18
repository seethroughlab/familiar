/**
 * GPU-accelerated particle system using instanced meshes.
 *
 * Supports thousands of particles with custom behaviors
 * that respond to audio data in real-time.
 */
import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { getAudioData } from '../../../hooks/useAudioAnalyser';

interface AudioData {
  bass: number;
  mid: number;
  treble: number;
  averageFrequency: number;
  frequencyData: Uint8Array;
}

interface GPUParticlesProps {
  count?: number;
  size?: number;
  color?: string;
  secondaryColor?: string;
  spread?: number;
  speed?: number;
  audioData: AudioData | null;
  behavior?: 'orbit' | 'flow' | 'explode' | 'swarm';
  opacity?: number;
}

// Simplex noise implementation for smooth particle movement
function noise3D(x: number, y: number, z: number): number {
  const p = [151,160,137,91,90,15,131,13,201,95,96,53,194,233,7,225,140,36,103,30,69,142,8,99,37,240,21,10,23,190,6,148,247,120,234,75,0,26,197,62,94,252,219,203,117,35,11,32,57,177,33,88,237,149,56,87,174,20,125,136,171,168,68,175,74,165,71,134,139,48,27,166,77,146,158,231,83,111,229,122,60,211,133,230,220,105,92,41,55,46,245,40,244,102,143,54,65,25,63,161,1,216,80,73,209,76,132,187,208,89,18,169,200,196,135,130,116,188,159,86,164,100,109,198,173,186,3,64,52,217,226,250,124,123,5,202,38,147,118,126,255,82,85,212,207,206,59,227,47,16,58,17,182,189,28,42,223,183,170,213,119,248,152,2,44,154,163,70,221,153,101,155,167,43,172,9,129,22,39,253,19,98,108,110,79,113,224,232,178,185,112,104,218,246,97,228,251,34,242,193,238,210,144,12,191,179,162,241,81,51,145,235,249,14,239,107,49,192,214,31,181,199,106,157,184,84,204,176,115,121,50,45,127,4,150,254,138,236,205,93,222,114,67,29,24,72,243,141,128,195,78,66,215,61,156,180];
  const perm = [...p, ...p];

  const X = Math.floor(x) & 255;
  const Y = Math.floor(y) & 255;
  const Z = Math.floor(z) & 255;

  x -= Math.floor(x);
  y -= Math.floor(y);
  z -= Math.floor(z);

  const u = x * x * x * (x * (x * 6 - 15) + 10);
  const v = y * y * y * (y * (y * 6 - 15) + 10);
  const w = z * z * z * (z * (z * 6 - 15) + 10);

  const A = perm[X] + Y;
  const AA = perm[A] + Z;
  const AB = perm[A + 1] + Z;
  const B = perm[X + 1] + Y;
  const BA = perm[B] + Z;
  const BB = perm[B + 1] + Z;

  const lerp = (t: number, a: number, b: number) => a + t * (b - a);
  const grad = (hash: number, x: number, y: number, z: number) => {
    const h = hash & 15;
    const u = h < 8 ? x : y;
    const v = h < 4 ? y : h === 12 || h === 14 ? x : z;
    return ((h & 1) === 0 ? u : -u) + ((h & 2) === 0 ? v : -v);
  };

  return lerp(w,
    lerp(v,
      lerp(u, grad(perm[AA], x, y, z), grad(perm[BA], x - 1, y, z)),
      lerp(u, grad(perm[AB], x, y - 1, z), grad(perm[BB], x - 1, y - 1, z))
    ),
    lerp(v,
      lerp(u, grad(perm[AA + 1], x, y, z - 1), grad(perm[BA + 1], x - 1, y, z - 1)),
      lerp(u, grad(perm[AB + 1], x, y - 1, z - 1), grad(perm[BB + 1], x - 1, y - 1, z - 1))
    )
  );
}

// Curl noise for fluid-like motion (reuses a single Vector3)
const _curlVec = new THREE.Vector3();
function curlNoise(x: number, y: number, z: number, time: number): THREE.Vector3 {
  const eps = 0.0001;
  const n1 = noise3D(x, y + eps, z + time);
  const n2 = noise3D(x, y - eps, z + time);
  const n3 = noise3D(x, y, z + eps + time);
  const n4 = noise3D(x, y, z - eps + time);
  const n5 = noise3D(x + eps, y, z + time);
  const n6 = noise3D(x - eps, y, z + time);

  _curlVec.set(
    (n1 - n2 - n3 + n4) / (2 * eps),
    (n3 - n4 - n5 + n6) / (2 * eps),
    (n5 - n6 - n1 + n2) / (2 * eps)
  );

  return _curlVec.normalize();
}

export function GPUParticles({
  count = 5000,
  size = 0.02,
  color = '#a855f7',
  secondaryColor = '#06b6d4',
  spread = 5,
  speed = 1,
  audioData,
  behavior = 'orbit',
  opacity = 0.8,
}: GPUParticlesProps) {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const timeRef = useRef(0);

  // Initialize particle data
  const { positions, velocities, phases, colors } = useMemo(() => {
    const positions = new Float32Array(count * 3);
    const velocities = new Float32Array(count * 3);
    const phases = new Float32Array(count);
    const colors = new Float32Array(count * 3);

    const color1 = new THREE.Color(color);
    const color2 = new THREE.Color(secondaryColor);

    for (let i = 0; i < count; i++) {
      // Random spherical distribution
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      const radius = Math.random() * spread;

      positions[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = radius * Math.cos(phi);

      velocities[i * 3] = (Math.random() - 0.5) * 0.02;
      velocities[i * 3 + 1] = (Math.random() - 0.5) * 0.02;
      velocities[i * 3 + 2] = (Math.random() - 0.5) * 0.02;

      phases[i] = Math.random() * Math.PI * 2;

      // Gradient between colors
      const t = Math.random();
      const c = color1.clone().lerp(color2, t);
      colors[i * 3] = c.r;
      colors[i * 3 + 1] = c.g;
      colors[i * 3 + 2] = c.b;
    }

    return { positions, velocities, phases, colors };
  }, [count, spread, color, secondaryColor]);

  const dummy = useMemo(() => new THREE.Object3D(), []);
  const tempColor = useMemo(() => new THREE.Color(), []);

  useFrame((_, delta) => {
    if (!meshRef.current) return;

    timeRef.current += delta * speed;
    const time = timeRef.current;

    // Get fresh audio data inside useFrame
    const liveAudioData = getAudioData() ?? audioData;
    const bass = liveAudioData?.bass ?? 0;
    const mid = liveAudioData?.mid ?? 0;
    const treble = liveAudioData?.treble ?? 0;
    const intensity = (liveAudioData?.averageFrequency ?? 0) / 255;

    for (let i = 0; i < count; i++) {
      const i3 = i * 3;
      let x = positions[i3];
      let y = positions[i3 + 1];
      let z = positions[i3 + 2];

      const phase = phases[i];

      switch (behavior) {
        case 'orbit': {
          // Particles orbit around center with audio-reactive radius
          const orbitRadius = 2 + bass * 2 + Math.sin(time + phase) * 0.5;
          const orbitSpeed = 0.3 + mid * 0.5;
          const angle = time * orbitSpeed + phase;
          const heightOsc = Math.sin(time * 0.5 + phase * 2) * (1 + treble);

          x = Math.cos(angle) * orbitRadius * (1 + Math.sin(phase) * 0.3);
          y = heightOsc;
          z = Math.sin(angle) * orbitRadius * (1 + Math.cos(phase) * 0.3);
          break;
        }

        case 'flow': {
          // Curl noise flow field
          const curl = curlNoise(x * 0.3, y * 0.3, z * 0.3, time * 0.2);
          const flowSpeed = 0.02 * (1 + bass * 2);

          x += curl.x * flowSpeed;
          y += curl.y * flowSpeed;
          z += curl.z * flowSpeed;

          // Contain within bounds
          const dist = Math.sqrt(x * x + y * y + z * z);
          if (dist > spread) {
            const scale = spread / dist;
            x *= scale * 0.9;
            y *= scale * 0.9;
            z *= scale * 0.9;
          }
          break;
        }

        case 'explode': {
          // Explode outward on bass, return to center
          const toCenter = new THREE.Vector3(-x, -y, -z).normalize();
          const explodeForce = bass * 0.1;
          const returnForce = 0.02;

          velocities[i3] += toCenter.x * returnForce - toCenter.x * explodeForce;
          velocities[i3 + 1] += toCenter.y * returnForce - toCenter.y * explodeForce;
          velocities[i3 + 2] += toCenter.z * returnForce - toCenter.z * explodeForce;

          // Damping
          velocities[i3] *= 0.98;
          velocities[i3 + 1] *= 0.98;
          velocities[i3 + 2] *= 0.98;

          x += velocities[i3];
          y += velocities[i3 + 1];
          z += velocities[i3 + 2];
          break;
        }

        case 'swarm': {
          // Swarm behavior - particles attracted to audio-reactive point
          const targetX = Math.sin(time * 0.5) * 2 * (1 + mid);
          const targetY = Math.cos(time * 0.3) * 2 * (1 + treble);
          const targetZ = Math.sin(time * 0.7) * 2 * (1 + bass);

          const dx = targetX - x;
          const dy = targetY - y;
          const dz = targetZ - z;

          const attractSpeed = 0.02 + intensity * 0.03;
          x += dx * attractSpeed + (Math.random() - 0.5) * 0.05 * (1 + bass);
          y += dy * attractSpeed + (Math.random() - 0.5) * 0.05 * (1 + mid);
          z += dz * attractSpeed + (Math.random() - 0.5) * 0.05 * (1 + treble);
          break;
        }
      }

      positions[i3] = x;
      positions[i3 + 1] = y;
      positions[i3 + 2] = z;

      // Update instance matrix
      const particleSize = size * (1 + intensity * 0.5);
      dummy.position.set(x, y, z);
      dummy.scale.setScalar(particleSize);
      dummy.updateMatrix();
      meshRef.current.setMatrixAt(i, dummy.matrix);

      // Update color based on audio
      const hueShift = intensity * 0.1;
      tempColor.setRGB(
        colors[i3] + hueShift,
        colors[i3 + 1],
        colors[i3 + 2] + hueShift * 0.5
      );
      meshRef.current.setColorAt(i, tempColor);
    }

    meshRef.current.instanceMatrix.needsUpdate = true;
    if (meshRef.current.instanceColor) {
      meshRef.current.instanceColor.needsUpdate = true;
    }
  });

  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, count]}>
      <sphereGeometry args={[1, 8, 8]} />
      <meshBasicMaterial
        transparent
        opacity={opacity}
        toneMapped={false}
        blending={THREE.AdditiveBlending}
      />
    </instancedMesh>
  );
}
