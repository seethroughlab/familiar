import { useState, useCallback, useEffect, type ReactNode } from 'react';
import { Upload } from 'lucide-react';

interface GlobalDropZoneProps {
  children: ReactNode;
  onFilesDropped: (files: File[]) => void;
  disabled?: boolean;
}

// Accepted file extensions
const ACCEPTED_EXTENSIONS = [
  '.mp3', '.flac', '.m4a', '.aac', '.ogg', '.wav', '.aiff', '.aif', '.zip'
];

function isValidFile(file: File): boolean {
  const ext = '.' + file.name.split('.').pop()?.toLowerCase();
  return ACCEPTED_EXTENSIONS.includes(ext);
}

export function GlobalDropZone({ children, onFilesDropped, disabled }: GlobalDropZoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  // Counter tracks nested drag enter/leave events - we only read via setter callback
  const [, setDragCounter] = useState(0);

  // Track drag enter/leave with counter to handle nested elements
  const handleDragEnter = useCallback((e: DragEvent) => {
    // Only intercept file drags, not internal track-to-queue drags
    if (!e.dataTransfer?.types.includes('Files')) return;
    e.preventDefault();
    e.stopPropagation();

    if (disabled) return;

    setDragCounter(prev => prev + 1);
    setIsDragging(true);
  }, [disabled]);

  const handleDragLeave = useCallback((e: DragEvent) => {
    // Only intercept file drags, not internal track-to-queue drags
    if (!e.dataTransfer?.types.includes('Files')) return;
    e.preventDefault();
    e.stopPropagation();

    setDragCounter(prev => {
      const newCount = prev - 1;
      if (newCount <= 0) {
        setIsDragging(false);
        return 0;
      }
      return newCount;
    });
  }, []);

  const handleDragOver = useCallback((e: DragEvent) => {
    // Only intercept file drags, not internal track-to-queue drags
    if (!e.dataTransfer?.types.includes('Files')) return;
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback((e: DragEvent) => {
    // Only intercept file drags, not internal track-to-queue drags
    if (!e.dataTransfer?.types.includes('Files')) return;
    e.preventDefault();
    e.stopPropagation();

    setIsDragging(false);
    setDragCounter(0);

    if (disabled) return;

    const files = Array.from(e.dataTransfer?.files || []);
    const validFiles = files.filter(isValidFile);

    if (validFiles.length > 0) {
      onFilesDropped(validFiles);
    }
  }, [disabled, onFilesDropped]);

  // Attach listeners to document for global drop zone
  useEffect(() => {
    document.addEventListener('dragenter', handleDragEnter);
    document.addEventListener('dragleave', handleDragLeave);
    document.addEventListener('dragover', handleDragOver);
    document.addEventListener('drop', handleDrop);

    return () => {
      document.removeEventListener('dragenter', handleDragEnter);
      document.removeEventListener('dragleave', handleDragLeave);
      document.removeEventListener('dragover', handleDragOver);
      document.removeEventListener('drop', handleDrop);
    };
  }, [handleDragEnter, handleDragLeave, handleDragOver, handleDrop]);

  return (
    <>
      {children}

      {/* Drop overlay */}
      {isDragging && (
        <div className="fixed inset-0 z-[100] pointer-events-none">
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/80 backdrop-blur-sm" />

          {/* Drop zone indicator */}
          <div className="absolute inset-4 border-4 border-dashed border-green-500 rounded-2xl flex items-center justify-center">
            <div className="text-center">
              <div className="w-20 h-20 mx-auto mb-4 rounded-full bg-green-500/20 flex items-center justify-center">
                <Upload className="w-10 h-10 text-green-400" />
              </div>
              <h2 className="text-2xl font-bold text-white mb-2">
                Drop to Import
              </h2>
              <p className="text-zinc-400">
                Audio files or ZIP archives
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
