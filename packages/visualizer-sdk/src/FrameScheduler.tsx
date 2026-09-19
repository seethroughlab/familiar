/**
 * FrameScheduler — drives demand rendering at ~30fps on mobile.
 *
 * Place inside a <Canvas frameloop="demand"> on mobile. On desktop this
 * component is a no-op (Canvas uses frameloop="always" and renders every
 * browser frame automatically).
 */
import { useEffect } from 'react';
import { useThree } from '@react-three/fiber';
const isMobile = () => window.matchMedia('(max-width: 768px)').matches;

const mobile = isMobile();

export function FrameScheduler() {
  const { invalidate } = useThree();

  useEffect(() => {
    if (!mobile) return;
    const id = setInterval(() => invalidate(), 33);
    return () => clearInterval(id);
  }, [invalidate]);

  return null;
}
