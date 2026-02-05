/**
 * AlphabetBar - Vertical A-Z navigation bar for quick list jumping.
 *
 * Features:
 * - Hover to reveal on desktop (doesn't overlap scrollbar)
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
}

export function AlphabetBar({
  letterIndex,
  activeLetter,
  onLetterSelect,
  visible,
}: AlphabetBarProps) {
  const [isHovering, setIsHovering] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [dragLetter, setDragLetter] = useState<string | null>(null);
  const [bubblePosition, setBubblePosition] = useState<{ y: number } | null>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const lastVibratedLetter = useRef<string | null>(null);

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

    const touch = e.touches[0];
    const letter = getLetterFromY(touch.clientY);
    if (letter) {
      setDragLetter(letter);
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
    if (!isDragging) return;
    e.preventDefault();

    const touch = e.touches[0];
    const letter = getLetterFromY(touch.clientY);

    if (letter && letter !== dragLetter) {
      setDragLetter(letter);
      setBubblePosition({ y: touch.clientY });

      // Haptic feedback when changing letters
      if (letter !== lastVibratedLetter.current && navigator.vibrate) {
        navigator.vibrate(5);
        lastVibratedLetter.current = letter;
      }
    }
  }, [isDragging, dragLetter, getLetterFromY]);

  // Handle touch end
  const handleTouchEnd = useCallback(() => {
    if (isDragging && dragLetter) {
      onLetterSelect(dragLetter);
    }

    setIsDragging(false);
    setDragLetter(null);
    setBubblePosition(null);
    lastVibratedLetter.current = null;
  }, [isDragging, dragLetter, onLetterSelect]);

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

      {/* Hover zone - invisible area on right edge that triggers bar visibility.
         Use right-[15px] to avoid covering the native scrollbar (~15px wide at right-0). */}
      <div
        className="fixed right-[15px] top-0 bottom-0 w-4 z-30 hidden md:block"
        onMouseEnter={() => setIsHovering(true)}
        onMouseLeave={() => !isDragging && setIsHovering(false)}
      />

      {/* Alphabet bar - desktop: shows on hover, mobile: always visible */}
      <div
        ref={barRef}
        className={`
          fixed top-1/2 -translate-y-1/2 z-40 flex flex-col items-center justify-center py-2 select-none touch-none
          transition-all duration-150 ease-out
          ${showBar ? 'right-4 opacity-100' : 'right-0 opacity-0 pointer-events-none md:pointer-events-auto'}
          md:${showBar ? 'right-4' : '-right-8'}
        `}
        style={{
          // On desktop: position based on hover state
          right: showBar ? '16px' : '-32px',
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
        <div className="relative flex flex-col items-center px-2">
          {ALPHABET.map((letter) => {
            const hasItems = letter in letterIndex;
            const isActive = currentLetter === letter;

            return (
              <button
                key={letter}
                onClick={() => hasItems && handleLetterClick(letter)}
                disabled={!hasItems}
                className={`
                  text-xs leading-tight py-0.5 px-1.5 transition-colors
                  ${isActive
                    ? 'text-green-500 font-bold scale-110'
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

      {/* Mobile: Always show a small indicator on right edge */}
      <div
        className="fixed right-0 top-1/2 -translate-y-1/2 w-1 h-32 bg-zinc-600/50 rounded-l md:hidden z-30"
        onTouchStart={(e) => {
          setIsHovering(true);
          handleTouchStart(e);
        }}
      />
    </>
  );
}
