/**
 * Quick-edit modal for renaming a playlist + editing description.
 */
import { useState, useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { playlistsApi } from '../../api/client';
import { showSuccess, showError } from '../../stores/toastStore';

interface Props {
  playlistId: string;
  initialName: string;
  initialDescription: string;
  isOpen: boolean;
  onClose: () => void;
}

export function PlaylistEditModal({ playlistId, initialName, initialDescription, isOpen, onClose }: Props) {
  const [name, setName] = useState(initialName);
  const [description, setDescription] = useState(initialDescription);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (isOpen) {
      setName(initialName);
      setDescription(initialDescription);
      setTimeout(() => inputRef.current?.select(), 50);
    }
  }, [isOpen, initialName, initialDescription]);

  if (!isOpen) return null;

  const handleSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await playlistsApi.update(playlistId, { name: name.trim(), description: description.trim() || undefined });
      queryClient.invalidateQueries({ queryKey: ['playlists'] });
      queryClient.invalidateQueries({ queryKey: ['playlist', playlistId] });
      showSuccess('Playlist updated');
      onClose();
    } catch {
      showError('Failed to update playlist');
    } finally {
      setSaving(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSave();
    }
    if (e.key === 'Escape') {
      onClose();
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl w-80 p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-white">Edit Playlist</h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="block text-xs text-zinc-400 mb-1">Name</label>
            <input
              ref={inputRef}
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={handleKeyDown}
              className="w-full px-2 py-1.5 text-sm bg-zinc-900 border border-zinc-600 rounded text-white focus:outline-none focus:border-zinc-500"
            />
          </div>
          <div>
            <label className="block text-xs text-zinc-400 mb-1">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={2}
              className="w-full px-2 py-1.5 text-sm bg-zinc-900 border border-zinc-600 rounded text-white focus:outline-none focus:border-zinc-500 resize-none"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-4">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm text-zinc-400 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !name.trim()}
            className="px-3 py-1.5 text-sm bg-zinc-600 hover:bg-zinc-500 text-white rounded disabled:opacity-50 transition-colors"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
