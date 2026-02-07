/**
 * Lyrics Visualizer - Karaoke-style lyrics with 3D particle effects.
 *
 * Features:
 * - Current line with exploding word particles from center
 * - Next line preview (smaller, dimmer) below current line
 * - Faded/blurred ambient floating words in background
 * - 3D particle swarm background
 * - Bloom and vignette post-processing
 */
import { useRef, useEffect, useMemo, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Text } from '@react-three/drei';
import * as THREE from 'three';
import { useAudioAnalyser, getAudioData } from '../../../hooks/useAudioAnalyser';
import { registerVisualizer, type VisualizerProps } from '../types';
import { AudioReactiveEffects } from '../effects/AudioReactiveEffects';

interface Word3D {
  id: number;
  text: string;
  position: THREE.Vector3;
  velocity: THREE.Vector3;
  rotation: THREE.Euler;
  rotationSpeed: THREE.Vector3;
  scale: number;
  opacity: number;
  hue: number;
  life: number;
  maxLife: number;
  isCurrentLine: boolean;
  shimmerPhase: number;  // Random phase offset for shimmer timing
}

let wordIdCounter = 0;

// Swarm particle system (inspired by the Swarm example)
function SwarmParticles() {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const lightRef = useRef<THREE.PointLight>(null);
  useAudioAnalyser(true);
  const count = 3000;

  const particles = useMemo(() => {
    const temp = [];
    for (let i = 0; i < count; i++) {
      const t = Math.random() * 100;
      const factor = 20 + Math.random() * 100;
      const speed = 0.01 + Math.random() / 200;
      const xFactor = -30 + Math.random() * 60;
      const yFactor = -30 + Math.random() * 60;
      const zFactor = -30 + Math.random() * 60;
      temp.push({ t, factor, speed, xFactor, yFactor, zFactor, mx: 0, my: 0 });
    }
    return temp;
  }, []);

  const dummy = useMemo(() => new THREE.Object3D(), []);

  useFrame((state) => {
    if (!meshRef.current) return;

    const audioData = getAudioData();
    const bass = audioData?.bass ?? 0;
    const mid = audioData?.mid ?? 0;
    const treble = audioData?.treble ?? 0;

    // Move light with audio
    if (lightRef.current) {
      lightRef.current.position.set(
        Math.sin(state.clock.elapsedTime) * 5 * (1 + bass),
        Math.cos(state.clock.elapsedTime * 0.7) * 5 * (1 + mid),
        Math.sin(state.clock.elapsedTime * 0.5) * 3
      );
      lightRef.current.intensity = 3 + bass * 5;
    }

    particles.forEach((particle, i) => {
      const { factor, speed, xFactor, yFactor, zFactor } = particle;
      const t = (particle.t += speed * (0.5 + bass * 2));

      const a = Math.cos(t) + Math.sin(t * 1) / 10;
      const b = Math.sin(t) + Math.cos(t * 2) / 10;
      const s = Math.cos(t) * 0.5 + 0.5;

      // Audio-reactive movement
      const audioOffset = bass * 2;

      dummy.position.set(
        xFactor + Math.cos((t / 10) * factor) + (Math.sin(t * 1) * factor) / 10 + a * audioOffset,
        yFactor + Math.sin((t / 10) * factor) + (Math.cos(t * 2) * factor) / 10 + b * audioOffset,
        zFactor + Math.cos((t / 10) * factor) + (Math.sin(t * 3) * factor) / 10
      );
      const zDistFromCamera = 15 - dummy.position.z; // camera at z=15
      const fadeFactor = zDistFromCamera < 8 ? zDistFromCamera / 8 : 1;
      dummy.scale.setScalar(s * 0.3 * (1 + treble * 0.5) * fadeFactor);
      dummy.rotation.set(s * 5, s * 5, s * 5);
      dummy.updateMatrix();
      meshRef.current!.setMatrixAt(i, dummy.matrix);

      // Color based on position and audio
      const hue = (0.7 + s * 0.2 + mid * 0.1) % 1;
      const color = new THREE.Color().setHSL(hue, 0.8, 0.3 + bass * 0.2);
      meshRef.current!.setColorAt(i, color);
    });

    meshRef.current.instanceMatrix.needsUpdate = true;
    if (meshRef.current.instanceColor) {
      meshRef.current.instanceColor.needsUpdate = true;
    }
  });

  return (
    <>
      <pointLight
        ref={lightRef}
        distance={60}
        intensity={5}
        color="#8b5cf6"
      />
      <instancedMesh ref={meshRef} args={[undefined, undefined, count]}>
        <dodecahedronGeometry args={[1, 0]} />
        <meshStandardMaterial
          color="#1a0030"
          emissive="#1a0030"
          emissiveIntensity={0.3}
          roughness={0.5}
          toneMapped={false}
        />
      </instancedMesh>
    </>
  );
}

// Floating word particles
function WordParticles({
  words,
  currentLineWords,
}: {
  words: string[];
  currentLineWords: string[];
}) {
  const groupRef = useRef<THREE.Group>(null);
  useAudioAnalyser(true);
  const [wordList, setWordList] = useState<Word3D[]>([]);
  const wordsRef = useRef<Word3D[]>([]);
  const spawnedLineRef = useRef<string[]>([]);
  const { viewport } = useThree();
  const timeRef = useRef(0);
  const updateCounterRef = useRef(0);

  useFrame((_, delta) => {
    if (!groupRef.current) return;

    timeRef.current += delta;

    const audioData = getAudioData();
    const bass = audioData?.bass ?? 0;
    const mid = audioData?.mid ?? 0;
    const treble = audioData?.treble ?? 0;

    // Check if we need to spawn new current line words
    const currentKey = currentLineWords.join(' ');
    const spawnedKey = spawnedLineRef.current.join(' ');

    if (currentKey !== spawnedKey && currentLineWords.length > 0) {
      spawnedLineRef.current = [...currentLineWords];

      // Spawn words from center with explosion pattern
      currentLineWords.forEach((word, i) => {
        const angle = (i / currentLineWords.length) * Math.PI * 2;
        const speed = 1 + Math.random() * 2;

        wordsRef.current.push({
          id: ++wordIdCounter,
          text: word,
          position: new THREE.Vector3(0, 0, 0),
          velocity: new THREE.Vector3(
            Math.cos(angle) * speed,
            Math.sin(angle) * speed,
            (Math.random() - 0.5) * 0.5
          ),
          rotation: new THREE.Euler(
            Math.random() * Math.PI,
            Math.random() * Math.PI,
            Math.random() * Math.PI
          ),
          rotationSpeed: new THREE.Vector3(
            (Math.random() - 0.5) * 0.5,
            (Math.random() - 0.5) * 0.5,
            (Math.random() - 0.5) * 0.5
          ),
          scale: 0.3 + Math.random() * 0.2,
          opacity: 1,
          hue: 0.75 + Math.random() * 0.1,
          life: 0,
          maxLife: 4 + Math.random() * 2,
          isCurrentLine: true,
          shimmerPhase: 0,  // Not used for current line words
        });
      });
    }

    // Spawn ambient words more frequently (faded/out of focus style)
    if (Math.random() < 0.12 + bass * 0.2 && words.length > 0) {
      const word = words[Math.floor(Math.random() * words.length)];
      const edge = Math.floor(Math.random() * 4);
      const hw = viewport.width / 2 + 2;
      const hh = viewport.height / 2 + 2;
      let x, y, vx, vy;

      switch (edge) {
        case 0: x = (Math.random() - 0.5) * hw * 2; y = -hh - 1; vx = (Math.random() - 0.5) * 0.3; vy = 0.3 + Math.random() * 0.5; break;
        case 1: x = hw + 1; y = (Math.random() - 0.5) * hh * 2; vx = -(0.3 + Math.random() * 0.5); vy = (Math.random() - 0.5) * 0.3; break;
        case 2: x = (Math.random() - 0.5) * hw * 2; y = hh + 1; vx = (Math.random() - 0.5) * 0.3; vy = -(0.3 + Math.random() * 0.5); break;
        default: x = -hw - 1; y = (Math.random() - 0.5) * hh * 2; vx = 0.3 + Math.random() * 0.5; vy = (Math.random() - 0.5) * 0.3;
      }

      wordsRef.current.push({
        id: ++wordIdCounter,
        text: word,
        position: new THREE.Vector3(x, y, -8 + Math.random() * 2), // Further back in z to avoid swarm particle overlap
        velocity: new THREE.Vector3(vx * 0.7, vy * 0.7, 0), // Slower movement
        rotation: new THREE.Euler(Math.random() * 0.3, Math.random() * 0.3, 0),
        rotationSpeed: new THREE.Vector3(
          (Math.random() - 0.5) * 0.05,
          (Math.random() - 0.5) * 0.05,
          (Math.random() - 0.5) * 0.05
        ),
        scale: 0.15 + Math.random() * 0.1, // Smaller scale for out-of-focus effect
        opacity: 0.35, // Much more faded
        hue: 0.55 + Math.random() * 0.2,
        life: 0,
        maxLife: 10 + Math.random() * 5, // Longer life but faded
        isCurrentLine: false,
        shimmerPhase: Math.random() * Math.PI * 2,  // Random starting phase for staggered shimmer
      });
    }

    // Update words
    wordsRef.current = wordsRef.current.filter((word) => {
      word.life += delta;

      // Update physics
      word.position.add(
        word.velocity.clone().multiplyScalar(delta * (1 + bass * 2))
      );
      word.rotation.x += word.rotationSpeed.x * delta * (1 + mid);
      word.rotation.y += word.rotationSpeed.y * delta * (1 + mid);
      word.rotation.z += word.rotationSpeed.z * delta * (1 + treble);

      // Fade out - keep words visible longer before fading
      const lifeRatio = word.life / word.maxLife;
      const fadeStart = 0.6; // Start fading at 60% of life
      const fadeAmount = lifeRatio > fadeStart ? (lifeRatio - fadeStart) / (1 - fadeStart) : 0;
      word.opacity = word.isCurrentLine
        ? Math.max(0, 1 - fadeAmount)
        : Math.max(0, 0.35 - fadeAmount * 0.35); // Ambient words stay faded

      return word.life < word.maxLife;
    });

    // Sync to React state less frequently to avoid flickering
    updateCounterRef.current++;
    if (updateCounterRef.current % 10 === 0) {
      setWordList(wordsRef.current.map(w => ({ ...w })));
    }
  });

  // Calculate shimmer for ambient words - creates periodic brightness boost
  const getShimmerBoost = (word: Word3D) => {
    if (word.isCurrentLine) return 0;
    const shimmer = Math.sin(timeRef.current * 2 + word.shimmerPhase) * 0.5 + 0.5;
    // Only boost when shimmer is high (top ~15% of the wave)
    return shimmer > 0.85 ? (shimmer - 0.85) * 4 : 0;
  };

  return (
    <group ref={groupRef}>
      {wordList.map((word) => {
        const shimmerBoost = getShimmerBoost(word);
        return (
          <Text
            key={word.id}
            position={[word.position.x, word.position.y, word.position.z]}
            rotation={[word.rotation.x, word.rotation.y, word.rotation.z]}
            fontSize={word.scale * (word.isCurrentLine ? 1.5 : 0.8)}
            color={new THREE.Color().setHSL(
              word.hue,
              word.isCurrentLine ? 0.85 : 0.5 + shimmerBoost * 0.3,
              word.isCurrentLine ? 0.7 : 0.4 + shimmerBoost * 0.4
            )}
            anchorX="center"
            anchorY="middle"
            font="https://cdn.jsdelivr.net/fontsource/fonts/inter@latest/latin-700-normal.woff"
            fillOpacity={word.opacity + (word.isCurrentLine ? 0 : shimmerBoost * 0.3)}
          >
            {word.text}
          </Text>
        );
      })}
    </group>
  );
}

// Background plane
function BackgroundPlane() {
  const meshRef = useRef<THREE.Mesh>(null);
  useAudioAnalyser(true);

  useFrame(() => {
    if (!meshRef.current) return;
    const audioData = getAudioData();
    const bass = audioData?.bass ?? 0;
    const material = meshRef.current.material as THREE.MeshBasicMaterial;
    material.opacity = 0.95 + bass * 0.05;
  });

  return (
    <mesh ref={meshRef} position={[0, 0, -20]}>
      <planeGeometry args={[200, 200]} />
      <meshBasicMaterial color="#050010" transparent opacity={0.95} />
    </mesh>
  );
}

// Main 3D scene
function LyricStormScene({
  allWords,
  currentLineWords,
}: {
  allWords: string[];
  currentLineWords: string[];
}) {
  useAudioAnalyser(true);

  return (
    <>
      <color attach="background" args={['#030008']} />
      <fog attach="fog" args={['#050010', 20, 80]} />

      <ambientLight intensity={0.1} />
      <pointLight position={[10, 10, 10]} intensity={1} color="#8b5cf6" />
      <pointLight position={[-10, -10, 5]} intensity={0.5} color="#06b6d4" />
      <pointLight position={[0, 0, 10]} intensity={0.4} color="#c4b5fd" distance={25} />

      <BackgroundPlane />
      <SwarmParticles />
      <WordParticles
        words={allWords}
        currentLineWords={currentLineWords}
      />

      <AudioReactiveEffects
        enableBloom
        enableVignette
        bloomIntensity={1.5}
        bloomThreshold={0.3}
        vignetteIntensity={0.4}
      />
    </>
  );
}

// Canvas 2D overlay for crisp current and next line text (karaoke style)
function TextOverlay({
  currentLine,
  nextLine,
  audioData,
}: {
  currentLine: string;
  nextLine: string;
  audioData: ReturnType<typeof useAudioAnalyser>;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationId: number;

    const resize = () => {
      canvas.width = canvas.clientWidth * window.devicePixelRatio;
      canvas.height = canvas.clientHeight * window.devicePixelRatio;
    };
    resize();
    window.addEventListener('resize', resize);

    const animate = () => {
      const width = canvas.width;
      const height = canvas.height;
      const dpr = window.devicePixelRatio;

      // Clear
      ctx.clearRect(0, 0, width, height);

      const bass = audioData?.bass ?? 0;
      const intensity = (audioData?.averageFrequency ?? 0) / 255;

      ctx.save();
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';

      // Draw current line (main, bright, at ~40% height)
      if (currentLine) {
        const fontSize = (48 + bass * 16) * dpr;
        ctx.font = `bold ${fontSize}px system-ui, -apple-system, sans-serif`;

        // Strong purple glow
        ctx.shadowColor = `hsla(280, 100%, 60%, 0.9)`;
        ctx.shadowBlur = (30 + intensity * 40) * dpr;
        ctx.fillStyle = `hsla(280, 80%, ${70 + intensity * 20}%, 0.95)`;

        ctx.fillText(currentLine, width / 2, height * 0.4);

        // Second pass for extra glow
        ctx.shadowBlur = (50 + bass * 30) * dpr;
        ctx.fillText(currentLine, width / 2, height * 0.4);
      }

      // Draw next line (smaller, dimmer, cyan, at ~60% height)
      if (nextLine) {
        const nextFontSize = (28 + bass * 8) * dpr;
        ctx.font = `${nextFontSize}px system-ui, -apple-system, sans-serif`;

        // Subtle cyan glow
        ctx.shadowColor = `hsla(185, 100%, 50%, 0.6)`;
        ctx.shadowBlur = (15 + intensity * 15) * dpr;
        ctx.fillStyle = `hsla(185, 70%, 55%, 0.7)`;

        ctx.fillText(nextLine, width / 2, height * 0.58);
      }

      ctx.restore();

      animationId = requestAnimationFrame(animate);
    };

    animate();

    return () => {
      cancelAnimationFrame(animationId);
      window.removeEventListener('resize', resize);
    };
  }, [currentLine, nextLine, audioData]);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 w-full h-full pointer-events-none"
      style={{ zIndex: 10 }}
    />
  );
}

export function LyricStorm({ lyrics, currentTime, track }: VisualizerProps) {
  const audioData = useAudioAnalyser(true);

  // Extract all unique words from lyrics
  const allWords = useMemo(() => {
    if (!lyrics || lyrics.length === 0) {
      const fallbackText = `${track?.title || ''} ${track?.artist || ''}`;
      return fallbackText.split(/\s+/).filter(w => w.length > 0);
    }
    const words: string[] = [];
    lyrics.forEach(line => {
      line.text.split(/\s+/).forEach(word => {
        const clean = word.replace(/[^\w']/g, '');
        if (clean.length > 1) words.push(clean);
      });
    });
    return [...new Set(words)];
  }, [lyrics, track]);

  // Find current line and next line for karaoke preview
  const { currentLine, currentLineWords, nextLine } = useMemo(() => {
    if (!lyrics || lyrics.length === 0) return { currentLine: '', currentLineWords: [], nextLine: '' };

    let idx = -1;
    for (let i = lyrics.length - 1; i >= 0; i--) {
      if (lyrics[i].time <= currentTime) {
        idx = i;
        break;
      }
    }

    if (idx < 0) return { currentLine: '', currentLineWords: [], nextLine: '' };

    const line = lyrics[idx].text;
    const words = line.split(/\s+/).map(w => w.replace(/[^\w']/g, '')).filter(w => w.length > 0);
    const next = idx < lyrics.length - 1 ? lyrics[idx + 1].text : '';
    return { currentLine: line, currentLineWords: words, nextLine: next };
  }, [lyrics, currentTime]);

  return (
    <div className="relative w-full h-full">
      <Canvas
        camera={{ position: [0, 0, 15], fov: 50 }}
        gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
        dpr={[1, 2]}
      >
        <LyricStormScene
          allWords={allWords}
          currentLineWords={currentLineWords}
        />
      </Canvas>

      <TextOverlay currentLine={currentLine} nextLine={nextLine} audioData={audioData} />
    </div>
  );
}

// Register the visualizer
registerVisualizer(
  {
    id: 'lyrics',
    name: 'Lyrics',
    description: 'Karaoke-style lyrics with next-line preview',
    usesMetadata: true,
  },
  LyricStorm
);
