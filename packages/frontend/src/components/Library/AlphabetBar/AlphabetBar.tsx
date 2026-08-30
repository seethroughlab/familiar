/**
 * AlphabetBar - Vertical A-Z navigation bar for quick list jumping.
 *
 * Features:
 * - Hover to reveal on desktop (doesn't overlap scrollbar)
 * - Always visible on mobile (iOS Contacts-style)
 * - Click to jump to a letter
 * - Touch-drag with haptic feedback (mobile)
 * - Floating letter bubble on drag
 * - Visual states: available, empty, active
 */
import { useState, useCallback, useRef, useEffect } from 'react';

const ALPHABET = ['#', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z'];

interface AlphabetBarProps {
  letterIndex: Record<string, number> | undefined;
  activeLetter?: string;
  onLetterSelect: (letter: string) => void;
  visible: boolean;
  isJumping?: boolean;
}

export function AlphabetBar({
  letterIndex,
  activeLetter,
  onLetterSelect,
  visible,
  isJumping,
}: AlphabetBarProps) {
  const [isHovering, setIsHovering] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [dragLetter, setDragLetter] = useState<string | null>(null);
  const [bubblePosition, setBubblePosition] = useState<{ y: number } | null>(null);
  const [isMobile, setIsMobile] = useState(() => !window.matchMedia('(min-width: 768px)').matches);
  const barRef = useRef<HTMLDivElement>(null);
  const lastVibratedLetter = useRef<string | null>(null);
  // Refs for touch handling — ensures handleTouchEnd reads latest values
  // regardless of whether React has re-rendered between touchstart and touchend
  const isDraggingRef = useRef(false);
  const dragLetterRef = useRef<string | null>(null);

  // Track isMobile via matchMedia listener
  useEffect(() => {
    const mql = window.matchMedia('(min-width: 768px)');
    const handler = (e: MediaQueryListEvent) => setIsMobile(!e.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, []);

  // Get letter from Y coordinate relative to the bar
  const getLetterFromY = useCallback((clientY: number) => {
    if (!barRef.current) return null;

    const rect = barRef.current.getBoundingClientRect();
    const relativeY = clientY - rect.top;
    const letterHeight = rect.height / ALPHABET.length;
    const index = Math.floor(relativeY / letterHeight);

    if (index >= 0 && index < ALPHABET.length) {
      return ALPHABET[index];
    }
    return null;
  }, []);

  // Handle touch start
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    e.preventDefault(); // Prevent page scroll
    setIsDragging(true);
    isDraggingRef.current = true;

    const touch = e.touches[0];
    const letter = getLetterFromY(touch.clientY);
    if (letter) {
      setDragLetter(letter);
      dragLetterRef.current = letter;
      setBubblePosition({ y: touch.clientY });
      lastVibratedLetter.current = letter;

      // Light haptic feedback
      if (navigator.vibrate) {
        navigator.vibrate(5);
      }
    }
  }, [getLetterFromY]);

  // Handle touch move
  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (!isDraggingRef.current) return;
    e.preventDefault();

    const touch = e.touches[0];
    const letter = getLetterFromY(touch.clientY);

    if (letter && letter !== dragLetterRef.current) {
      setDragLetter(letter);
      dragLetterRef.current = letter;
      setBubblePosition({ y: touch.clientY });

      // Haptic feedback when changing letters
      if (letter !== lastVibratedLetter.current && navigator.vibrate) {
        navigator.vibrate(5);
        lastVibratedLetter.current = letter;
      }
    }
  }, [getLetterFromY]);

  // Handle touch end — reads refs to get latest values regardless of React render timing
  const handleTouchEnd = useCallback(() => {
    if (isDraggingRef.current && dragLetterRef.current) {
      onLetterSelect(dragLetterRef.current);
    }

    setIsDragging(false);
    isDraggingRef.current = false;
    setDragLetter(null);
    dragLetterRef.current = null;
    setBubblePosition(null);
    lastVibratedLetter.current = null;
  }, [onLetterSelect]);

  // Handle click on a letter
  const handleLetterClick = useCallback((letter: string) => {
    onLetterSelect(letter);
  }, [onLetterSelect]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      lastVibratedLetter.current = null;
    };
  }, []);

  if (!visible || !letterIndex) {
    return null;
  }

  const currentLetter = isDragging ? dragLetter : activeLetter;
  const showBar = isHovering || isDragging;

  return (
    <>
      {/* Floating letter bubble during drag */}
      {isDragging && dragLetter && bubblePosition && (
        <div
          className="fixed z-50 pointer-events-none"
          style={{
            right: '60px',
            top: bubblePosition.y - 24,
          }}
        >
          <div className="bg-green-600 text-white text-3xl font-bold rounded-lg px-4 py-2 shadow-lg">
            {dragLetter}
          </div>
        </div>
      )}

      {/* Hover zone - invisible area on right edge that triggers bar visibility (desktop only).
         Use right-[15px] to avoid covering the native scrollbar (~15px wide at right-0). */}
      {!isMobile && (
        <div
          className="fixed right-[15px] top-0 bottom-0 w-4 z-30"
          onMouseEnter={() => setIsHovering(true)}
          onMouseLeave={() => !isDragging && setIsHovering(false)}
        />
      )}

      {/* Alphabet bar
          Mobile: always visible at right edge, condensed sizing
          Desktop: hover-to-reveal with slide animation */}
      <div
        ref={barRef}
        className="fixed top-1/2 -translate-y-1/2 z-40 flex flex-col items-center justify-center py-2 select-none touch-none transition-all duration-150 ease-out"
        style={{
          right: isMobile ? '2px' : (showBar ? '16px' : '-32px'),
          opacity: isMobile ? 0.8 : (showBar ? 1 : 0),
          pointerEvents: isMobile ? 'auto' : (showBar ? 'auto' : 'none'),
        }}
        onMouseEnter={() => setIsHovering(true)}
        onMouseLeave={() => !isDragging && setIsHovering(false)}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onTouchCancel={handleTouchEnd}
      >
        {/* Background pill */}
        <div className="absolute inset-0 bg-zinc-900/90 backdrop-blur-sm rounded-lg shadow-lg" />

        {/* Letters */}
        <div className={`relative flex flex-col items-center ${isMobile ? 'px-1' : 'px-2'}`}>
          {ALPHABET.map((letter) => {
            const hasItems = letter in letterIndex;
            const isActive = currentLetter === letter;

            return (
              <button
                key={letter}
                onClick={() => hasItems && handleLetterClick(letter)}
                disabled={!hasItems}
                className={`
                  leading-tight transition-colors
                  ${isMobile ? 'text-[10px] py-0 px-1' : 'text-xs py-0.5 px-1.5'}
                  ${isActive
                    ? `text-success font-bold scale-110${isJumping ? ' animate-pulse' : ''}`
                    : hasItems
                      ? 'text-zinc-300 hover:text-white'
                      : 'text-zinc-600 cursor-default'
                  }
                `}
              >
                {letter}
              </button>
            );
          })}
        </div>
      </div>
    </>
  );
}
