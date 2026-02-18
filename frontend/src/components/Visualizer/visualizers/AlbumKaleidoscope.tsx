/**
 * Album Art Kaleidoscope Visualizer - Enhanced with shader effects.
 *
 * Features:
 * - Shader-based kaleidoscope with configurable segments
 * - RGB chromatic aberration on treble peaks
 * - Radial zoom blur on bass
 * - Sparkle particles along segment edges
 * - Bloom and vignette post-processing
 */
import { useRef, useMemo, useEffect, useState } from 'react';
import { Canvas, useFrame, useLoader, extend } from '@react-three/fiber';
import { shaderMaterial } from '@react-three/drei';
import * as THREE from 'three';
import { useAudioAnalyser, getAudioData } from '../../../hooks/useAudioAnalyser';
import { registerVisualizer, type VisualizerProps } from '../types';
import { AudioReactiveEffects } from '../effects/AudioReactiveEffects';

// Shader-based kaleidoscope material with realistic shard movement
const KaleidoscopeMaterial = shaderMaterial(
  {
    uTexture: null as THREE.Texture | null,
    uTime: 0,
    uSegments: 12,
    uRotation: 0,
    uInnerRotation: 0,
    uTwist: 0,
    uScale: 1,
    uBass: 0,
    uMid: 0,
    uTreble: 0,
    uIntensity: 0,
    uChromaticAberration: 0,
    uRadialBlur: 0,
  },
  // Vertex shader
  `
    varying vec2 vUv;

    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  // Fragment shader
  `
    uniform sampler2D uTexture;
    uniform float uTime;
    uniform float uSegments;
    uniform float uRotation;
    uniform float uInnerRotation;
    uniform float uTwist;
    uniform float uScale;
    uniform float uBass;
    uniform float uMid;
    uniform float uTreble;
    uniform float uIntensity;
    uniform float uChromaticAberration;
    uniform float uRadialBlur;

    varying vec2 vUv;

    #define PI 3.14159265359

    vec2 kaleidoscope(vec2 uv, float segments, float outerRot, float innerRot, float twist, float time) {
      // Convert to polar coordinates
      vec2 centered = uv - 0.5;
      float radius = length(centered);
      float angle = atan(centered.y, centered.x);

      // Apply outer rotation (whole kaleidoscope rotates)
      angle += outerRot;

      // Apply twist - inner parts rotate differently than outer parts
      // This creates the "tumbling gems" effect of a real kaleidoscope
      float twistAmount = twist * (1.0 - radius * 0.8);
      angle += twistAmount;

      // Apply inner rotation that varies by radius
      angle += innerRot * (1.0 + sin(radius * 5.0 + time) * 0.3);

      // Create kaleidoscope segments
      float segmentAngle = PI * 2.0 / segments;
      float segmentIndex = floor(angle / segmentAngle);
      angle = mod(angle, segmentAngle);

      // Mirror every other segment for kaleidoscope symmetry
      if (mod(segmentIndex, 2.0) >= 1.0) {
        angle = segmentAngle - angle;
      }

      // Add subtle wobble to each segment
      float wobble = sin(time * 2.0 + segmentIndex * 1.5) * 0.02 * (1.0 + uBass);
      angle += wobble;

      // Convert back to cartesian with slight radius distortion
      float distortedRadius = radius * (1.0 + sin(angle * 3.0 + time) * 0.05 * uMid);

      return vec2(
        cos(angle) * distortedRadius + 0.5,
        sin(angle) * distortedRadius + 0.5
      );
    }

    vec4 radialBlur(sampler2D tex, vec2 uv, float strength) {
      vec4 color = vec4(0.0);
      vec2 center = vec2(0.5);
      vec2 dir = (uv - center) * strength;

      const int samples = 8;
      float total = 0.0;

      for (int i = 0; i < samples; i++) {
        float t = float(i) / float(samples - 1);
        float weight = 1.0 - t;
        color += texture2D(tex, uv - dir * t) * weight;
        total += weight;
      }

      return color / total;
    }

    void main() {
      // Dynamic scale based on audio
      float dynamicScale = uScale * (1.0 + uBass * 0.2);

      // Apply scale from center with breathing effect
      float breathe = 1.0 + sin(uTime * 0.5) * 0.03;
      vec2 scaledUv = (vUv - 0.5) / (dynamicScale * breathe) + 0.5;

      // Apply kaleidoscope transformation with all rotations
      vec2 kUv = kaleidoscope(scaledUv, uSegments, uRotation, uInnerRotation, uTwist, uTime);

      // Chromatic aberration that shifts with audio
      float chromaOffset = uChromaticAberration * (1.0 + uTreble * 2.0);
      vec2 chromaDir = normalize(kUv - 0.5) * chromaOffset;

      vec4 color;

      if (uRadialBlur > 0.001) {
        float blurStrength = uRadialBlur * uBass * 0.08;

        vec4 rChannel = radialBlur(uTexture, kUv + chromaDir, blurStrength);
        vec4 gChannel = radialBlur(uTexture, kUv, blurStrength);
        vec4 bChannel = radialBlur(uTexture, kUv - chromaDir, blurStrength);

        color = vec4(rChannel.r, gChannel.g, bChannel.b, 1.0);
      } else {
        float r = texture2D(uTexture, kUv + chromaDir).r;
        float g = texture2D(uTexture, kUv).g;
        float b = texture2D(uTexture, kUv - chromaDir).b;

        color = vec4(r, g, b, 1.0);
      }

      // Enhance colors based on audio (reduced to prevent blowout)
      color.rgb *= 0.85 + uIntensity * 0.15;

      // Add subtle shimmer effect
      float shimmer = sin(kUv.x * 20.0 + uTime * 3.0) * sin(kUv.y * 20.0 - uTime * 2.0);
      color.rgb += shimmer * 0.015 * uTreble;

      // Radial rainbow tint (subtle)
      float dist = length(vUv - 0.5) * 2.0;
      vec3 rainbow = vec3(
        sin(dist * 3.0 + uTime) * 0.5 + 0.5,
        sin(dist * 3.0 + uTime + 2.094) * 0.5 + 0.5,
        sin(dist * 3.0 + uTime + 4.189) * 0.5 + 0.5
      );
      color.rgb = mix(color.rgb, color.rgb * rainbow, 0.08 * uMid);

      // Edge glow (subtle, only at edges)
      float edgeGlow = smoothstep(0.7, 1.0, dist) * (0.1 + uBass * 0.15);
      color.rgb += vec3(0.4, 0.2, 0.6) * edgeGlow;

      gl_FragColor = color;
    }
  `
);

extend({ KaleidoscopeMaterial });

// Sparkle particles along kaleidoscope edges
function SparkleParticles({ segments }: { segments: number }) {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  useAudioAnalyser(true);
  const timeRef = useRef(0);
  const particleCount = 300;

  const { positions, velocities, phases, lifetimes, segmentIndices } = useMemo(() => {
    const positions = new Float32Array(particleCount * 3);
    const velocities = new Float32Array(particleCount * 3);
    const phases = new Float32Array(particleCount);
    const lifetimes = new Float32Array(particleCount);
    const segmentIndices = new Float32Array(particleCount);

    for (let i = 0; i < particleCount; i++) {
      phases[i] = Math.random() * Math.PI * 2;
      segmentIndices[i] = Math.floor(Math.random() * segments);
      lifetimes[i] = 0;
    }

    return { positions, velocities, phases, lifetimes, segmentIndices };
  }, [segments]);

  const dummy = useMemo(() => new THREE.Object3D(), []);
  const tempColor = useMemo(() => new THREE.Color(), []);
  const particleIndex = useRef(0);

  useFrame((_, delta) => {
    if (!meshRef.current) return;

    timeRef.current += delta;
    const time = timeRef.current;

    const audio = getAudioData();
    const bass = audio?.bass ?? 0;

    // Spawn new particles on beat
    if (bass > 0.3 && Math.random() < bass * 0.5) {
      const count = Math.floor(bass * 5) + 1;
      for (let j = 0; j < count; j++) {
        const pIdx = particleIndex.current % particleCount;
        const segIdx = segmentIndices[pIdx];
        const segmentAngle = (segIdx / segments) * Math.PI * 2;

        // Position along segment edge
        const radius = Math.random() * 2.5 + 0.5;
        const x = Math.cos(segmentAngle) * radius;
        const y = Math.sin(segmentAngle) * radius;

        positions[pIdx * 3] = x;
        positions[pIdx * 3 + 1] = y;
        positions[pIdx * 3 + 2] = 0.1;

        // Velocity outward from center
        const speed = 0.5 + Math.random() * 1.5;
        velocities[pIdx * 3] = x * speed * 0.3 + (Math.random() - 0.5) * 0.5;
        velocities[pIdx * 3 + 1] = y * speed * 0.3 + (Math.random() - 0.5) * 0.5;
        velocities[pIdx * 3 + 2] = (Math.random() - 0.5) * 0.2;

        lifetimes[pIdx] = 1.0;
        particleIndex.current++;
      }
    }

    // Update all particles
    for (let i = 0; i < particleCount; i++) {
      if (lifetimes[i] <= 0) {
        dummy.position.set(0, 0, -10);
        dummy.scale.setScalar(0.001);
        dummy.updateMatrix();
        meshRef.current.setMatrixAt(i, dummy.matrix);
        continue;
      }

      const i3 = i * 3;

      // Move particle
      positions[i3] += velocities[i3] * delta;
      positions[i3 + 1] += velocities[i3 + 1] * delta;
      positions[i3 + 2] += velocities[i3 + 2] * delta;

      // Fade out
      lifetimes[i] -= delta * 2;

      // Twinkle effect
      const twinkle = Math.sin(time * 10 + phases[i]) * 0.5 + 0.5;
      const scale = lifetimes[i] * 0.04 * (0.5 + twinkle * 0.5);

      dummy.position.set(positions[i3], positions[i3 + 1], positions[i3 + 2]);
      dummy.scale.setScalar(Math.max(0.001, scale));
      dummy.updateMatrix();
      meshRef.current.setMatrixAt(i, dummy.matrix);

      // Color based on segment - create rainbow effect (reduced brightness)
      const hue = (segmentIndices[i] / segments + time * 0.1) % 1;
      tempColor.setHSL(hue, 0.8, 0.4 + lifetimes[i] * 0.2);
      meshRef.current.setColorAt(i, tempColor);
    }

    meshRef.current.instanceMatrix.needsUpdate = true;
    if (meshRef.current.instanceColor) {
      meshRef.current.instanceColor.needsUpdate = true;
    }
  });

  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, particleCount]}>
      <circleGeometry args={[1, 8]} />
      <meshBasicMaterial
        transparent
        opacity={0.9}
        toneMapped={false}
        blending={THREE.AdditiveBlending}
        depthWrite={false}
      />
    </instancedMesh>
  );
}

// Outer ring decoration
function OuterRing() {
  const meshRef = useRef<THREE.Mesh>(null);
  useAudioAnalyser(true);
  const timeRef = useRef(0);

  useFrame((_, delta) => {
    if (!meshRef.current) return;

    timeRef.current += delta;
    const audioData = getAudioData();
    const bass = audioData?.bass ?? 0;

    // Rotate and pulse
    meshRef.current.rotation.z = timeRef.current * 0.1;
    const scale = 2.8 + bass * 0.2;
    meshRef.current.scale.setScalar(scale);

    // Update material (reduced opacity)
    const material = meshRef.current.material as THREE.MeshBasicMaterial;
    material.opacity = 0.15 + bass * 0.15;
  });

  return (
    <mesh ref={meshRef} position={[0, 0, -0.1]}>
      <ringGeometry args={[0.95, 1, 64]} />
      <meshBasicMaterial
        color="#8b5cf6"
        transparent
        opacity={0.4}
        toneMapped={false}
        blending={THREE.AdditiveBlending}
      />
    </mesh>
  );
}

// Main kaleidoscope component using shader
function KaleidoscopeShader({ texture }: { texture: THREE.Texture }) {
  const materialRef = useRef<THREE.ShaderMaterial>(null);
  useAudioAnalyser(true);
  const timeRef = useRef(0);
  const rotationRef = useRef(0);
  const innerRotationRef = useRef(0);
  const twistRef = useRef(0);

  useFrame((_, delta) => {
    if (!materialRef.current) return;

    timeRef.current += delta;

    const audioData = getAudioData();
    const bass = audioData?.bass ?? 0;
    const mid = audioData?.mid ?? 0;
    const treble = audioData?.treble ?? 0;
    const intensity = (audioData?.averageFrequency ?? 0) / 255;

    // Outer rotation - slow and steady
    rotationRef.current += 0.002 + bass * 0.008;

    // Inner rotation - gentler, opposite direction
    innerRotationRef.current -= 0.004 + mid * 0.01;

    // Twist - reduced for better album recognition
    const targetTwist = Math.sin(timeRef.current * 0.3) * 0.2 + treble * 0.3;
    twistRef.current += (targetTwist - twistRef.current) * 0.03;

    // Update uniforms
    materialRef.current.uniforms.uTime.value = timeRef.current;
    materialRef.current.uniforms.uRotation.value = rotationRef.current;
    materialRef.current.uniforms.uInnerRotation.value = innerRotationRef.current;
    materialRef.current.uniforms.uTwist.value = twistRef.current;
    materialRef.current.uniforms.uScale.value = 1 + treble * 0.1;
    materialRef.current.uniforms.uBass.value = bass;
    materialRef.current.uniforms.uMid.value = mid;
    materialRef.current.uniforms.uTreble.value = treble;
    materialRef.current.uniforms.uIntensity.value = intensity;
    materialRef.current.uniforms.uChromaticAberration.value = 0.003;
    materialRef.current.uniforms.uRadialBlur.value = 1;
  });

  return (
    <mesh position={[0, 0, 0]}>
      <planeGeometry args={[6, 6]} />
      {/* @ts-expect-error - Custom R3F element registered via extend() */}
      <kaleidoscopeMaterial
        ref={materialRef}
        uTexture={texture}
        uSegments={8}
        uChromaticAberration={0.003}
        uRadialBlur={1}
      />
    </mesh>
  );
}

function KaleidoscopeScene({ artworkUrl }: { artworkUrl: string }) {
  useAudioAnalyser(true);
  const texture = useLoader(THREE.TextureLoader, artworkUrl);

  // Configure texture
  useMemo(() => {
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    texture.minFilter = THREE.LinearFilter;
    texture.magFilter = THREE.LinearFilter;
  }, [texture]);

  return (
    <>
      <color attach="background" args={['#050010']} />

      {/* Main kaleidoscope */}
      <KaleidoscopeShader texture={texture} />

      {/* Decorative elements */}
      <OuterRing />
      <SparkleParticles segments={12} />

      {/* Post-processing - reduced bloom to prevent white-out */}
      <AudioReactiveEffects
        enableBloom
        enableVignette
        bloomIntensity={0.6}
        bloomThreshold={0.7}
        vignetteIntensity={0.4}
      />
    </>
  );
}

// Fallback visualizer when no artwork
function FallbackScene() {
  const meshRef = useRef<THREE.Mesh>(null);
  const ringRef = useRef<THREE.Mesh>(null);
  useAudioAnalyser(true);
  const timeRef = useRef(0);

  useFrame((_, delta) => {
    if (!meshRef.current) return;

    timeRef.current += delta;
    const audioData = getAudioData();
    const bass = audioData?.bass ?? 0;
    const mid = audioData?.mid ?? 0;

    // Rotate and pulse
    meshRef.current.rotation.z += 0.01 + bass * 0.02;
    meshRef.current.rotation.x = Math.sin(timeRef.current * 0.5) * 0.2;
    meshRef.current.rotation.y = Math.cos(timeRef.current * 0.3) * 0.2;

    const scale = 1 + bass * 0.3;
    meshRef.current.scale.setScalar(scale);

    if (ringRef.current) {
      ringRef.current.rotation.z = -timeRef.current * 0.2;
      ringRef.current.scale.setScalar(2.5 + mid * 0.3);
    }
  });

  return (
    <>
      <color attach="background" args={['#050010']} />

      <mesh ref={meshRef}>
        <icosahedronGeometry args={[1.5, 2]} />
        <meshBasicMaterial color="#8b5cf6" wireframe toneMapped={false} />
      </mesh>

      <mesh ref={ringRef} position={[0, 0, -0.5]}>
        <torusGeometry args={[1, 0.02, 16, 100]} />
        <meshBasicMaterial
          color="#06b6d4"
          toneMapped={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>

      <SparkleParticles segments={12} />

      <AudioReactiveEffects
        enableBloom
        enableVignette
        bloomIntensity={1.2}
        bloomThreshold={0.5}
        vignetteIntensity={0.5}
      />
    </>
  );
}

export function AlbumKaleidoscope({ artworkUrl }: VisualizerProps) {
  const [hasArtwork, setHasArtwork] = useState(false);

  useEffect(() => {
    if (artworkUrl) {
      // Verify the image loads
      const img = new Image();
      img.onload = () => setHasArtwork(true);
      img.onerror = () => setHasArtwork(false);
      img.src = artworkUrl;
    } else {
      setHasArtwork(false);
    }
  }, [artworkUrl]);

  return (
    <div className="w-full h-full">
      <Canvas
        camera={{ position: [0, 0, 5], fov: 50 }}
        gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
        dpr={[1, 2]}
      >
        {hasArtwork && artworkUrl ? (
          <KaleidoscopeScene artworkUrl={artworkUrl} />
        ) : (
          <FallbackScene />
        )}
      </Canvas>
    </div>
  );
}

// Register the visualizer
registerVisualizer(
  {
    id: 'album-kaleidoscope',
    name: 'Album Kaleidoscope',
    description: 'Shader-based kaleidoscope with RGB split',
    usesMetadata: true,
  },
  AlbumKaleidoscope
);
