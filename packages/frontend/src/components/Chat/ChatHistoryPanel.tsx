import { useState, useRef, useEffect } from 'react';
import {
  Search,
  X,
  Trash2,
  Pencil,
  Check,
  MessageSquare,
  Plus,
} from 'lucide-react';
import type { ChatSession } from '../../db';
import * as chatService from '../../services/chatService';

interface Props {
  sessions: ChatSession[];
  currentSessionId: string | null;
  profileId: string;
  onSelectSession: (session: ChatSession) => void;
  onNewSession: () => void;
  onSessionsChanged: () => void;
  onClose: () => void;
}

type DateGroup = 'today' | 'yesterday' | 'thisWeek' | 'thisMonth' | 'older';

function getDateGroup(date: Date): DateGroup {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const weekAgo = new Date(today);
  weekAgo.setDate(weekAgo.getDate() - 7);
  const monthAgo = new Date(today);
  monthAgo.setMonth(monthAgo.getMonth() - 1);

  const sessionDate = new Date(date);

  if (sessionDate >= today) return 'today';
  if (sessionDate >= yesterday) return 'yesterday';
  if (sessionDate >= weekAgo) return 'thisWeek';
  if (sessionDate >= monthAgo) return 'thisMonth';
  return 'older';
}

const groupLabels: Record<DateGroup, string> = {
  today: 'Today',
  yesterday: 'Yesterday',
  thisWeek: 'This Week',
  thisMonth: 'This Month',
  older: 'Older',
};

function groupSessions(
  sessions: ChatSession[]
): Record<DateGroup, ChatSession[]> {
  const groups: Record<DateGroup, ChatSession[]> = {
    today: [],
    yesterday: [],
    thisWeek: [],
    thisMonth: [],
    older: [],
  };

  sessions.forEach((session) => {
    const group = getDateGroup(session.updatedAt);
    groups[group].push(session);
  });

  return groups;
}

export function ChatHistoryPanel({
  sessions,
  currentSessionId,
  profileId,
  onSelectSession,
  onNewSession,
  onSessionsChanged,
  onClose,
}: Props) {
  const [searchQuery, setSearchQuery] = useState('');
  const [filteredSessions, setFilteredSessions] =
    useState<ChatSession[]>(sessions);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  const editInputRef = useRef<HTMLInputElement>(null);

  // Update filtered sessions when search query or sessions change
  useEffect(() => {
    const search = async () => {
      if (!searchQuery.trim()) {
        setFilteredSessions(sessions);
      } else {
        const results = await chatService.searchSessions(profileId, searchQuery);
        setFilteredSessions(results);
      }
    };
    search();
  }, [searchQuery, sessions, profileId]);

  // Focus edit input when editing starts
  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingId]);

  const handleDelete = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Delete this conversation?')) return;

    await chatService.deleteSession(sessionId);
    onSessionsChanged();
  };

  const startEditing = (session: ChatSession, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(session.id);
    setEditingTitle(session.title);
  };

  const saveEdit = async () => {
    if (editingId && editingTitle.trim()) {
      await chatService.renameSession(editingId, editingTitle);
      onSessionsChanged();
    }
    setEditingId(null);
    setEditingTitle('');
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditingTitle('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      saveEdit();
    } else if (e.key === 'Escape') {
      cancelEdit();
    }
  };

  const groupedSessions = groupSessions(filteredSessions);
  const groupOrder: DateGroup[] = [
    'today',
    'yesterday',
    'thisWeek',
    'thisMonth',
    'older',
  ];

  return (
    <div className="flex flex-col h-full bg-zinc-900 border-r border-zinc-800">
      {/* Header */}
      <div className="p-3 border-b border-zinc-800 flex items-center justify-between">
        <h3 className="font-medium text-sm">Chat History</h3>
        <button
          onClick={onClose}
          className="p-1 hover:bg-zinc-800 rounded transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Search */}
      <div className="p-3 border-b border-zinc-800">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search conversations..."
            className="w-full pl-8 pr-3 py-1.5 text-base bg-zinc-800 border border-zinc-700 rounded-md focus:outline-none focus:border-purple-500"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 hover:bg-zinc-700 rounded"
            >
              <X className="w-3 h-3 text-zinc-500" />
            </button>
          )}
        </div>
      </div>

      {/* New Chat Button */}
      <div className="p-3 border-b border-zinc-800">
        <button
          onClick={() => {
            onNewSession();
            onClose();
          }}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-green-600 hover:bg-green-500 rounded-md text-sm font-medium transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Conversation
        </button>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto">
        {filteredSessions.length === 0 ? (
          <div className="p-4 text-center text-zinc-500 text-sm">
            {searchQuery ? (
              <>No conversations match "{searchQuery}"</>
            ) : (
              <>No conversations yet</>
            )}
          </div>
        ) : (
          groupOrder.map((group) => {
            const groupSessions = groupedSessions[group];
            if (groupSessions.length === 0) return null;

            return (
              <div key={group}>
                <div className="px-3 py-2 text-xs font-medium text-zinc-500 uppercase tracking-wider bg-zinc-950/50 sticky top-0">
                  {groupLabels[group]}
                </div>
                {groupSessions.map((session) => (
                  <div
                    key={session.id}
                    onClick={() => {
                      if (editingId !== session.id) {
                        onSelectSession(session);
                        onClose();
                      }
                    }}
                    className={`group px-3 py-2.5 cursor-pointer border-b border-zinc-800/50 transition-colors ${
                      currentSessionId === session.id
                        ? 'bg-zinc-800'
                        : 'hover:bg-zinc-800/50'
                    }`}
                  >
                    <div className="flex items-start gap-2">
                      <MessageSquare className="w-4 h-4 text-zinc-500 mt-0.5 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        {editingId === session.id ? (
                          <div className="flex items-center gap-1">
                            <input
                              ref={editInputRef}
                              type="text"
                              value={editingTitle}
                              onChange={(e) => setEditingTitle(e.target.value)}
                              onKeyDown={handleKeyDown}
                              onBlur={saveEdit}
                              onClick={(e) => e.stopPropagation()}
                              className="flex-1 px-1.5 py-0.5 text-base bg-zinc-700 border border-zinc-600 rounded focus:outline-none focus:border-purple-500"
                            />
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                saveEdit();
                              }}
                              className="p-1 text-green-500 hover:bg-zinc-700 rounded"
                            >
                              <Check className="w-3 h-3" />
                            </button>
                          </div>
                        ) : (
                          <p className="text-sm font-medium truncate">
                            {session.title}
                          </p>
                        )}
                        <p className="text-xs text-zinc-500 mt-0.5">
                          {session.messages.length} message
                          {session.messages.length !== 1 ? 's' : ''}
                          {' · '}
                          {formatRelativeTime(session.updatedAt)}
                        </p>
                      </div>
                      {editingId !== session.id && (
                        <div className="flex items-center gap-1 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={(e) => startEditing(session, e)}
                            className="p-1 text-zinc-500 hover:text-white hover:bg-zinc-700 rounded transition-colors"
                            title="Rename"
                          >
                            <Pencil className="w-3 h-3" />
                          </button>
                          <button
                            onClick={(e) => handleDelete(session.id, e)}
                            className="p-1 text-zinc-500 hover:text-red-400 hover:bg-zinc-700 rounded transition-colors"
                            title="Delete"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            );
          })
        )}
      </div>

      {/* Footer with count */}
      {filteredSessions.length > 0 && (
        <div className="p-2 border-t border-zinc-800 text-center text-xs text-zinc-500">
          {filteredSessions.length} conversation
          {filteredSessions.length !== 1 ? 's' : ''}
          {searchQuery && ` matching "${searchQuery}"`}
        </div>
      )}
    </div>
  );
}

function formatRelativeTime(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - new Date(date).getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return 'yesterday';
  if (diffDays < 7) return `${diffDays}d ago`;
  return new Date(date).toLocaleDateString();
}
