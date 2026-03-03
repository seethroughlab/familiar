/**
 * Audio-reactive post-processing effects.
 *
 * Uses native Three.js EffectComposer with proper R3F integration.
 * Takes over the render loop to apply effects.
 */
import { useRef, useEffect, useMemo } from 'react';
import { useThree, useFrame } from '@react-three/fiber';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import * as THREE from 'three';
import { getAudioData } from '../../../hooks/useAudioAnalyser';

// Vignette shader
const VignetteShader = {
  uniforms: {
    tDiffuse: { value: null },
    darkness: { value: 0.5 },
    offset: { value: 0.5 },
  },
  vertexShader: `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: `
    uniform sampler2D tDiffuse;
    uniform float darkness;
    uniform float offset;
    varying vec2 vUv;
    void main() {
      vec4 texel = texture2D(tDiffuse, vUv);
      vec2 uv = (vUv - vec2(0.5)) * vec2(offset);
      float vignette = clamp(pow(cos(uv.x * 3.1415926), darkness) * pow(cos(uv.y * 3.1415926), darkness), 0.0, 1.0);
      gl_FragColor = vec4(texel.rgb * vignette, texel.a);
    }
  `,
};

interface AudioReactiveEffectsProps {
  enableBloom?: boolean;
  enableVignette?: boolean;
  bloomIntensity?: number;
  bloomThreshold?: number;
  bloomRadius?: number;
  vignetteIntensity?: number;
}

export function AudioReactiveEffects({
  enableBloom = true,
  enableVignette = true,
  bloomIntensity = 1.0,
  bloomThreshold = 0.85,
  bloomRadius = 0.5,
  vignetteIntensity = 0.5,
}: AudioReactiveEffectsProps) {
  const { gl, scene, camera, size } = useThree();

  const bloomPassRef = useRef<UnrealBloomPass | null>(null);
  const vignettePassRef = useRef<ShaderPass | null>(null);

  // Create composer with useMemo to avoid recreating on every render
  const composer = useMemo(() => {
    const effectComposer = new EffectComposer(gl);

    // Render scene
    const renderPass = new RenderPass(scene, camera);
    effectComposer.addPass(renderPass);

    // Bloom
    if (enableBloom) {
      const bloomPass = new UnrealBloomPass(
        new THREE.Vector2(size.width, size.height),
        bloomIntensity,
        bloomRadius,
        bloomThreshold
      );
      effectComposer.addPass(bloomPass);
      // Store bloom pass for later ref assignment
      (effectComposer as EffectComposer & { _bloomPass?: UnrealBloomPass })._bloomPass = bloomPass;
    }

    // Vignette
    if (enableVignette) {
      const vignettePass = new ShaderPass(VignetteShader);
      vignettePass.uniforms.darkness.value = vignetteIntensity;
      effectComposer.addPass(vignettePass);
      // Store vignette pass for later ref assignment
      (effectComposer as EffectComposer & { _vignettePass?: ShaderPass })._vignettePass = vignettePass;
    }

    // Output pass for proper color space
    const outputPass = new OutputPass();
    effectComposer.addPass(outputPass);

    return effectComposer;
  }, [gl, scene, camera, enableBloom, enableVignette, size.width, size.height, bloomIntensity, bloomRadius, bloomThreshold, vignetteIntensity]);

  // Update refs after composer creation (must be in useEffect, not during render)
  useEffect(() => {
    const comp = composer as EffectComposer & { _bloomPass?: UnrealBloomPass; _vignettePass?: ShaderPass };
    bloomPassRef.current = comp._bloomPass ?? null;
    vignettePassRef.current = comp._vignettePass ?? null;
  }, [composer]);

  // Handle size changes
  useEffect(() => {
    composer.setSize(size.width, size.height);
    composer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    if (bloomPassRef.current) {
      bloomPassRef.current.resolution.set(size.width, size.height);
    }
  }, [composer, size]);

  // Cleanup
  useEffect(() => {
    return () => {
      composer.dispose();
    };
  }, [composer]);

  // Take over rendering with high priority (runs last)
  useFrame((_state, _delta) => {
    // Update effects based on audio
    const audioData = getAudioData();
    const bass = audioData?.bass ?? 0;
    const intensity = (audioData?.averageFrequency ?? 128) / 255;

    if (bloomPassRef.current) {
      bloomPassRef.current.strength = bloomIntensity + bass * 1.5;
      bloomPassRef.current.threshold = Math.max(0.3, bloomThreshold - intensity * 0.2);
    }

    if (vignettePassRef.current) {
      vignettePassRef.current.uniforms.darkness.value = vignetteIntensity + bass * 0.3;
    }

    // Render through composer instead of default renderer
    composer.render();
  }, 1);

  return null;
}
