import { useState, useRef, useCallback } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Upload, Trash2, Image, Loader2, CheckCircle, AlertCircle } from 'lucide-react';
import { tracksApi, getApiUrl } from '../../../api';
import { showWarning } from '../../../stores/toastStore';

interface Props {
  trackId: string;
  artist: string | null | undefined;
  album: string | null | undefined;
}

export function ArtworkTab({ trackId, artist, album }: Props) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [embedInFile, setEmbedInFile] = useState(true);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  // Get current artwork URL
  const artworkUrl = getApiUrl(`/tracks/${trackId}/artwork?size=full&t=${Date.now()}`);

  // Upload mutation
  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(
        getApiUrl(`/tracks/${trackId}/artwork?embed_in_file=${embedInFile}`),
        {
          method: 'POST',
          body: formData,
        }
      );

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Upload failed');
      }

      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tracks'] });
      queryClient.invalidateQueries({ queryKey: ['track-metadata'] });
      setPreviewUrl(null);
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: () => tracksApi.deleteArtwork(trackId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tracks'] });
      queryClient.invalidateQueries({ queryKey: ['track-metadata'] });
    },
  });

  const handleFileSelect = useCallback((file: File) => {
    // Validate file type
    const validTypes = ['image/jpeg', 'image/png', 'image/webp'];
    if (!validTypes.includes(file.type)) {
      showWarning('Please select a JPEG, PNG, or WebP image');
      return;
    }

    // Validate file size (10MB max)
    if (file.size > 10 * 1024 * 1024) {
      showWarning('Image must be smaller than 10MB');
      return;
    }

    // Create preview
    const reader = new FileReader();
    reader.onload = (e) => {
      setPreviewUrl(e.target?.result as string);
    };
    reader.readAsDataURL(file);

    // Upload
    uploadMutation.mutate(file);
  }, [uploadMutation]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);

    const file = e.dataTransfer.files[0];
    if (file) {
      handleFileSelect(file);
    }
  }, [handleFileSelect]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOver(false);
  }, []);

  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      handleFileSelect(file);
    }
  }, [handleFileSelect]);

  const handleDelete = useCallback(() => {
    if (confirm('Remove album artwork? This will affect all tracks from this album.')) {
      deleteMutation.mutate();
    }
  }, [deleteMutation]);

  const isLoading = uploadMutation.isPending || deleteMutation.isPending;

  return (
    <div className="space-y-6">
      {/* Album info */}
      <div className="text-sm text-zinc-400">
        <p>
          <span className="text-zinc-500">Album:</span>{' '}
          {album || 'Unknown Album'}
        </p>
        <p>
          <span className="text-zinc-500">Artist:</span>{' '}
          {artist || 'Unknown Artist'}
        </p>
        <p className="mt-2 text-zinc-500 text-xs">
          Artwork is shared across all tracks from the same album.
        </p>
      </div>

      {/* Current artwork / Drop zone */}
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        className={`relative aspect-square max-w-sm mx-auto rounded-lg overflow-hidden border-2 border-dashed transition-colors ${
          dragOver
            ? 'border-purple-500 bg-purple-500/10'
            : 'border-zinc-700 bg-zinc-800/50'
        }`}
      >
        {isLoading ? (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50">
            <Loader2 className="w-8 h-8 animate-spin text-purple-400" />
          </div>
        ) : null}

        {previewUrl ? (
          <img
            src={previewUrl}
            alt="Preview"
            className="w-full h-full object-cover"
          />
        ) : (
          <img
            src={artworkUrl}
            alt="Album artwork"
            className="w-full h-full object-cover"
            onError={(e) => {
              // Show placeholder on error
              e.currentTarget.style.display = 'none';
              e.currentTarget.nextElementSibling?.classList.remove('hidden');
            }}
          />
        )}

        {/* Placeholder */}
        <div className="hidden absolute inset-0 flex flex-col items-center justify-center text-zinc-500">
          <Image className="w-16 h-16 mb-4 opacity-50" />
          <p className="text-sm">No artwork</p>
        </div>

        {/* Drop overlay */}
        {dragOver && (
          <div className="absolute inset-0 flex items-center justify-center bg-purple-500/20">
            <p className="text-purple-400 font-medium">Drop image here</p>
          </div>
        )}
      </div>

      {/* Status messages */}
      {uploadMutation.isSuccess && (
        <div className="flex items-center justify-center gap-2 text-green-400 text-sm">
          <CheckCircle className="w-4 h-4" />
          Artwork uploaded successfully
        </div>
      )}
      {uploadMutation.isError && (
        <div className="flex items-center justify-center gap-2 text-red-400 text-sm">
          <AlertCircle className="w-4 h-4" />
          {uploadMutation.error?.message || 'Upload failed'}
        </div>
      )}
      {deleteMutation.isSuccess && (
        <div className="flex items-center justify-center gap-2 text-green-400 text-sm">
          <CheckCircle className="w-4 h-4" />
          Artwork removed
        </div>
      )}

      {/* Controls */}
      <div className="flex flex-col items-center gap-4">
        {/* Embed checkbox */}
        <label className="flex items-center gap-2 text-sm text-zinc-400">
          <input
            type="checkbox"
            checked={embedInFile}
            onChange={(e) => setEmbedInFile(e.target.checked)}
            className="w-4 h-4 rounded border-zinc-600 bg-zinc-800 text-purple-500 focus:ring-purple-500 focus:ring-offset-0"
          />
          Embed in audio file tags
        </label>

        {/* Buttons */}
        <div className="flex items-center gap-3">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={handleInputChange}
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isLoading}
            className="flex items-center gap-2 px-4 py-2 bg-purple-500 hover:bg-purple-600 disabled:bg-zinc-700 disabled:text-zinc-500 text-white rounded-lg text-sm font-medium transition-colors"
          >
            <Upload className="w-4 h-4" />
            Upload Artwork
          </button>
          <button
            onClick={handleDelete}
            disabled={isLoading}
            className="flex items-center gap-2 px-4 py-2 bg-zinc-700 hover:bg-zinc-600 disabled:bg-zinc-800 disabled:text-zinc-600 text-zinc-300 rounded-lg text-sm font-medium transition-colors"
          >
            <Trash2 className="w-4 h-4" />
            Remove
          </button>
        </div>

        <p className="text-xs text-zinc-500 text-center">
          Accepts JPEG, PNG, or WebP images up to 10MB
        </p>
      </div>
    </div>
  );
}
