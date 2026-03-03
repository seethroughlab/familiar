/**
 * ArtistPoints - Efficient point cloud rendering for 3D artist visualization.
 *
 * Uses THREE.Points for GPU-efficient rendering of thousands of points.
 * Each point represents an artist, colored by region and sized by track count.
 */
import { useRef, useMemo, useEffect } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';
import type { MapNode3D } from '../../../../api';

interface ArtistPointsProps {
  nodes: MapNode3D[];
  selectedId?: string;
  hoveredArtist: MapNode3D | null;
  onHover: (artist: MapNode3D | null) => void;
  onClick: (artist: MapNode3D) => void;
  onClickEmpty?: () => void;
}

// Size scaling
const MIN_SIZE = 12;
const MAX_SIZE = 40;
const HOVER_SIZE_BOOST = 1.5;

// Position scaling (spread points out more)
export const POSITION_SCALE = 5;

// Color helper - HSL to RGB
function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  let r, g, b;
  if (s === 0) {
    r = g = b = l;
  } else {
    const hue2rgb = (p: number, q: number, t: number) => {
      if (t < 0) t += 1;
      if (t > 1) t -= 1;
      if (t < 1/6) return p + (q - p) * 6 * t;
      if (t < 1/2) return q;
      if (t < 2/3) return p + (q - p) * (2/3 - t) * 6;
      return p;
    };
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    r = hue2rgb(p, q, h + 1/3);
    g = hue2rgb(p, q, h);
    b = hue2rgb(p, q, h - 1/3);
  }
  return [r, g, b];
}

// Get color based on 3D position (creates regional color variation)
function getPositionColor(x: number, y: number, z: number, isSelected: boolean, isHovered: boolean): [number, number, number] {
  if (isSelected) {
    return [0.13, 0.77, 0.37]; // Green for selected
  }
  if (isHovered) {
    return [1, 1, 1]; // White for hovered
  }

  // Use position to determine hue (0-1)
  const hue = (Math.atan2(y, x) / Math.PI + 1) / 2;
  const saturation = 0.7;
  const lightness = 0.55 + z * 0.1;

  return hslToRgb(hue, saturation, lightness);
}

export function ArtistPoints({
  nodes,
  selectedId,
  hoveredArtist,
  onHover,
  onClick,
  onClickEmpty,
}: ArtistPointsProps) {
  const pointsRef = useRef<THREE.Points>(null);
  const { camera, gl } = useThree();
  const hoveredIndexRef = useRef<number | null>(null);
  const mouseRef = useRef(new THREE.Vector2());
  const raycasterRef = useRef(new THREE.Raycaster());

  // Track mouse position manually for reliable raycasting
  useEffect(() => {
    const canvas = gl.domElement;
    const handleMouseMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      // Convert to normalized device coordinates (-1 to 1)
      mouseRef.current.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouseRef.current.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    };
    canvas.addEventListener('mousemove', handleMouseMove);
    return () => canvas.removeEventListener('mousemove', handleMouseMove);
  }, [gl]);

  // Compute size range for normalization
  const sizeRange = useMemo(() => {
    if (nodes.length === 0) return { min: 1, max: 1 };
    const counts = nodes.map((n) => n.track_count);
    return {
      min: Math.min(...counts),
      max: Math.max(...counts),
    };
  }, [nodes]);

  // Create index map
  const nodeIndexMap = useMemo(() => {
    const indexMap = new Map<number, MapNode3D>();
    nodes.forEach((node, i) => indexMap.set(i, node));
    return indexMap;
  }, [nodes]);

  // Create base geometry with positions (stable - only changes when nodes change)
  const geometry = useMemo(() => {
    const positions = new Float32Array(nodes.length * 3);
    const colors = new Float32Array(nodes.length * 3);
    const sizes = new Float32Array(nodes.length);

    nodes.forEach((node, i) => {
      // Scale positions
      positions[i * 3] = node.x * POSITION_SCALE;
      positions[i * 3 + 1] = node.y * POSITION_SCALE;
      positions[i * 3 + 2] = node.z * POSITION_SCALE;

      // Initial colors based on position
      const [r, g, b] = getPositionColor(node.x, node.y, node.z, false, false);
      colors[i * 3] = r;
      colors[i * 3 + 1] = g;
      colors[i * 3 + 2] = b;

      // Size based on track count (log scale)
      const normalizedCount =
        sizeRange.max === sizeRange.min
          ? 0.5
          : Math.log(node.track_count - sizeRange.min + 1) / Math.log(sizeRange.max - sizeRange.min + 1);
      sizes[i] = MIN_SIZE + normalizedCount * (MAX_SIZE - MIN_SIZE);
    });

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    geo.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

    // Critical for raycasting to work!
    geo.computeBoundingSphere();

    return geo;
  }, [nodes, sizeRange]);

  // Update colors and sizes when hover/selection changes (without recreating geometry)
  useEffect(() => {
    if (!geometry || nodes.length === 0) return;

    const colors = geometry.getAttribute('color') as THREE.BufferAttribute;
    const sizes = geometry.getAttribute('size') as THREE.BufferAttribute;

    nodes.forEach((node, i) => {
      const isHovered = hoveredArtist?.id === node.id;
      const isSelected = node.id === selectedId;

      // Update color
      const [r, g, b] = getPositionColor(node.x, node.y, node.z, isSelected, isHovered);
      colors.setXYZ(i, r, g, b);

      // Update size
      const normalizedCount =
        sizeRange.max === sizeRange.min
          ? 0.5
          : Math.log(node.track_count - sizeRange.min + 1) / Math.log(sizeRange.max - sizeRange.min + 1);
      let size = MIN_SIZE + normalizedCount * (MAX_SIZE - MIN_SIZE);
      if (isHovered) size *= HOVER_SIZE_BOOST;
      sizes.setX(i, size);
    });

    colors.needsUpdate = true;
    sizes.needsUpdate = true;
  }, [geometry, nodes, sizeRange, selectedId, hoveredArtist]);

  // Set raycaster threshold once
  useEffect(() => {
    raycasterRef.current.params.Points = { threshold: 0.5 };
  }, []);

  // Raycasting for hover detection - run every frame
  useFrame(() => {
    if (!pointsRef.current || nodes.length === 0) return;

    const raycaster = raycasterRef.current;
    raycaster.setFromCamera(mouseRef.current, camera);

    const intersects = raycaster.intersectObject(pointsRef.current);

    let hoveredIndex: number | null = null;
    if (intersects.length > 0) {
      // Sort by distance to ray and take the closest
      intersects.sort((a, b) => a.distanceToRay! - b.distanceToRay!);
      const closest = intersects[0];
      // Only accept if actually close to the ray (explicit check)
      const maxDistance = 0.25;
      if (closest.index !== undefined && closest.distanceToRay !== undefined && closest.distanceToRay < maxDistance) {
        hoveredIndex = closest.index;
      }
    }

    if (hoveredIndex !== hoveredIndexRef.current) {
      hoveredIndexRef.current = hoveredIndex;
      if (hoveredIndex !== null) {
        const node = nodeIndexMap.get(hoveredIndex);
        onHover(node || null);
      } else {
        onHover(null);
      }
    }
  });

  // Handle click through pointer events (avoids OrbitControls interference)
  const pointerDownPos = useRef<{ x: number; y: number } | null>(null);
  useEffect(() => {
    const canvas = gl.domElement;

    const handlePointerDown = (e: PointerEvent) => {
      pointerDownPos.current = { x: e.clientX, y: e.clientY };
    };

    const handlePointerUp = (e: PointerEvent) => {
      if (!pointerDownPos.current) return;

      // Check if this was a click (minimal movement) vs a drag
      const dx = e.clientX - pointerDownPos.current.x;
      const dy = e.clientY - pointerDownPos.current.y;
      const distance = Math.sqrt(dx * dx + dy * dy);

      // If moved less than 5 pixels, treat as click
      if (distance < 5) {
        if (hoveredIndexRef.current !== null) {
          const node = nodeIndexMap.get(hoveredIndexRef.current);
          if (node) {
            onClick(node);
          }
        } else {
          // Clicked in empty space
          onClickEmpty?.();
        }
      }

      pointerDownPos.current = null;
    };

    canvas.addEventListener('pointerdown', handlePointerDown);
    canvas.addEventListener('pointerup', handlePointerUp);
    return () => {
      canvas.removeEventListener('pointerdown', handlePointerDown);
      canvas.removeEventListener('pointerup', handlePointerUp);
    };
  }, [gl, nodeIndexMap, onClick, onClickEmpty]);

  if (nodes.length === 0) return null;

  return (
    <group>
      <points ref={pointsRef} geometry={geometry}>
        <shaderMaterial
          vertexColors
          transparent
          depthWrite={false}
          blending={THREE.NormalBlending}
          vertexShader={`
            attribute float size;
            varying vec3 vColor;
            varying float vDepth;

            void main() {
              vColor = color;
              vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
              vDepth = -mvPosition.z;

              gl_PointSize = size * (400.0 / -mvPosition.z);
              gl_PointSize = clamp(gl_PointSize, 2.0, 80.0);

              gl_Position = projectionMatrix * mvPosition;
            }
          `}
          fragmentShader={`
            varying vec3 vColor;
            varying float vDepth;

            void main() {
              vec2 center = gl_PointCoord - vec2(0.5);
              float dist = length(center);

              if (dist > 0.5) discard;

              // Soft edge falloff
              float alpha = 1.0 - smoothstep(0.0, 0.5, dist);
              alpha = pow(alpha, 1.5);

              // Depth fade: close = 1.0 (bright), far = 0.0 (dim)
              // Fade from depth 1 to depth 4
              float depthFade = 1.0 - clamp((vDepth - 1.0) / 3.0, 0.0, 1.0);

              // Desaturate and darken distant points
              float gray = dot(vColor, vec3(0.299, 0.587, 0.114));
              vec3 desaturated = vec3(gray * 0.25);

              // Mix: close = full color, far = dark gray
              vec3 finalColor = mix(desaturated, vColor, depthFade);

              // Alpha: close = solid, far = faded
              float finalAlpha = mix(0.2, 0.95, depthFade) * alpha;

              gl_FragColor = vec4(finalColor, finalAlpha);
            }
          `}
        />
      </points>

      {/* HTML label for hovered artist - always visible in screen space */}
      {hoveredArtist && (
        <Html
          position={[
            hoveredArtist.x * POSITION_SCALE,
            hoveredArtist.y * POSITION_SCALE,
            hoveredArtist.z * POSITION_SCALE,
          ]}
          center
          style={{
            transform: 'translateY(-30px)',
            pointerEvents: 'none',
          }}
        >
          <div className="px-2 py-1 bg-black/80 rounded text-white text-sm font-medium whitespace-nowrap">
            {hoveredArtist.name}
          </div>
        </Html>
      )}
    </group>
  );
}
