import { useState, useCallback, useEffect, type ReactNode } from 'react';
import { Upload, Package } from 'lucide-react';
import { zipSync } from 'fflate';

interface GlobalDropZoneProps {
  children: ReactNode;
  onFilesDropped: (files: File[]) => void;
  disabled?: boolean;
}

const ACCEPTED_AUDIO_EXTENSIONS = [
  '.mp3', '.flac', '.m4a', '.aac', '.ogg', '.wav', '.aiff', '.aif'
];
const ACCEPTED_EXTENSIONS = [...ACCEPTED_AUDIO_EXTENSIONS, '.zip'];

function isValidFile(file: File): boolean {
  const ext = '.' + file.name.split('.').pop()?.toLowerCase();
  return ACCEPTED_EXTENSIONS.includes(ext);
}

function isAudioFile(name: string): boolean {
  const ext = '.' + name.split('.').pop()?.toLowerCase();
  return ACCEPTED_AUDIO_EXTENSIONS.includes(ext);
}

/** Recursively collect all files from a FileSystemDirectoryEntry */
async function readDirectoryFiles(
  entry: FileSystemDirectoryEntry,
  basePath = ''
): Promise<{ path: string; file: File }[]> {
  const reader = entry.createReader();
  const results: { path: string; file: File }[] = [];

  // readEntries may return partial results, so we must call until empty
  let batch: FileSystemEntry[];
  do {
    batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
      reader.readEntries(resolve, reject)
    );
    for (const child of batch) {
      const childPath = basePath ? `${basePath}/${child.name}` : child.name;
      if (child.isFile) {
        const file = await new Promise<File>((resolve, reject) =>
          (child as FileSystemFileEntry).file(resolve, reject)
        );
        results.push({ path: childPath, file });
      } else if (child.isDirectory) {
        const nested = await readDirectoryFiles(
          child as FileSystemDirectoryEntry,
          childPath
        );
        results.push(...nested);
      }
    }
  } while (batch.length > 0);

  return results;
}

/** Zip an array of files into a single File object */
async function zipFiles(
  files: { path: string; file: File }[],
  zipName: string
): Promise<File> {
  const data: Record<string, Uint8Array> = {};

  for (const { path, file } of files) {
    const buf = await file.arrayBuffer();
    data[path] = new Uint8Array(buf);
  }

  // Use zipSync with no compression for speed (audio files don't compress well)
  const zipped = zipSync(data, { level: 0 });
  return new File([zipped.buffer as ArrayBuffer], zipName, { type: 'application/zip' });
}

export function GlobalDropZone({ children, onFilesDropped, disabled }: GlobalDropZoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [isPackaging, setIsPackaging] = useState(false);
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

    setDragCounter(0);

    if (disabled) {
      setIsDragging(false);
      return;
    }

    // Check for directory entries via webkitGetAsEntry
    const items = e.dataTransfer?.items;
    let hasDirectory = false;
    const entries: FileSystemEntry[] = [];

    if (items) {
      for (let i = 0; i < items.length; i++) {
        const entry = items[i].webkitGetAsEntry?.();
        if (entry) {
          entries.push(entry);
          if (entry.isDirectory) hasDirectory = true;
        }
      }
    }

    if (hasDirectory) {
      // Handle folder drop asynchronously
      setIsPackaging(true);
      (async () => {
        try {
          const allFiles: { path: string; file: File }[] = [];

          for (const entry of entries) {
            if (entry.isDirectory) {
              const dirFiles = await readDirectoryFiles(
                entry as FileSystemDirectoryEntry
              );
              allFiles.push(...dirFiles);
            } else if (entry.isFile) {
              const file = await new Promise<File>((resolve, reject) =>
                (entry as FileSystemFileEntry).file(resolve, reject)
              );
              allFiles.push({ path: file.name, file });
            }
          }

          // Filter to audio files only
          const audioFiles = allFiles.filter(f => isAudioFile(f.path));

          if (audioFiles.length === 0) {
            return;
          }

          // Find the top-level folder name for the zip
          const folderEntry = entries.find(e => e.isDirectory);
          const zipName = (folderEntry?.name || 'import') + '.zip';

          const zipFile = await zipFiles(audioFiles, zipName);
          onFilesDropped([zipFile]);
        } finally {
          setIsPackaging(false);
          setIsDragging(false);
        }
      })();
    } else {
      // Plain file drop — existing logic
      setIsDragging(false);
      const files = Array.from(e.dataTransfer?.files || []);
      const validFiles = files.filter(isValidFile);

      if (validFiles.length > 0) {
        onFilesDropped(validFiles);
      }
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

  const showOverlay = isDragging || isPackaging;

  return (
    <>
      {children}

      {/* Drop overlay */}
      {showOverlay && (
        <div className="fixed inset-0 z-[100] pointer-events-none">
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/80 backdrop-blur-sm" />

          {/* Drop zone indicator */}
          <div className="absolute inset-4 border-4 border-dashed border-green-500 rounded-2xl flex items-center justify-center">
            <div className="text-center">
              <div className="w-20 h-20 mx-auto mb-4 rounded-full bg-green-500/20 flex items-center justify-center">
                {isPackaging ? (
                  <Package className="w-10 h-10 text-green-400 animate-pulse" />
                ) : (
                  <Upload className="w-10 h-10 text-green-400" />
                )}
              </div>
              <h2 className="text-2xl font-bold text-white mb-2">
                {isPackaging ? 'Packaging folder for import...' : 'Drop to Import'}
              </h2>
              <p className="text-zinc-400">
                {isPackaging
                  ? 'Collecting audio files and creating archive'
                  : 'Audio files, ZIP archives, or folders'}
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
