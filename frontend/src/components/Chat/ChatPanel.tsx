import { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Loader2, Music, Wrench, Plus, History, AlertTriangle, WifiOff } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { usePlayerStore } from '../../stores/playerStore';
import { useLibraryViewStore } from '../../stores/libraryViewStore';
import { useVisibleTracksStore } from '../../stores/visibleTracksStore';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';
import { getOrCreateDeviceProfile } from '../../services/profileService';
import * as chatService from '../../services/chatService';
import { ChatHistoryPanel } from './ChatHistoryPanel';
import type { ChatSession, ChatToolCall } from '../../db';

interface Track {
  id: string;
  title: string;
  artist: string;
  album: string;
}

interface ChatPanelProps {
  /** Pre-filled message to auto-submit (from context menu actions) */
  pendingMessage?: string | null;
  /** Called after pending message is consumed */
  onPendingMessageConsumed?: () => void;
}

export function ChatPanel({ pendingMessage, onPendingMessageConsumed }: ChatPanelProps = {}) {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentSession, setCurrentSession] = useState<ChatSession | null>(null);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [profileId, setProfileId] = useState<string | null>(null);
  const [showSessions, setShowSessions] = useState(false);
  const [llmStatus, setLlmStatus] = useState<{ configured: boolean; provider: string } | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const queryClient = useQueryClient();
  const { setQueue } = usePlayerStore();
  const { isOffline } = useOfflineStatus();

  // Load profile and sessions on mount
  useEffect(() => {
    const init = async () => {
      const profile = await getOrCreateDeviceProfile();
      setProfileId(profile);

      if (profile) {
        const allSessions = await chatService.listSessions(profile);
        setSessions(allSessions);

        // Load most recent session or create new one
        if (allSessions.length > 0) {
          setCurrentSession(allSessions[0]);
        }
      }
    };
    init();
  }, []);

  // Check LLM configuration status on mount
  useEffect(() => {
    fetch('/api/v1/chat/status')
      .then((r) => r.json())
      .then(setLlmStatus)
      .catch(() => setLlmStatus({ configured: false, provider: 'unknown' }));
  }, []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [currentSession?.messages]);

  // Handle pending message from context menu (auto-submit)
  const pendingMessageRef = useRef<string | null>(null);
  useEffect(() => {
    if (pendingMessage && pendingMessage !== pendingMessageRef.current && !isLoading && profileId) {
      pendingMessageRef.current = pendingMessage;
      setInput(pendingMessage);
      onPendingMessageConsumed?.();
      // Auto-submit after a brief delay to allow state to settle
      setTimeout(() => {
        const form = document.querySelector('form[data-chat-form]') as HTMLFormElement;
        if (form) {
          form.requestSubmit();
        }
      }, 100);
    }
  }, [pendingMessage, isLoading, profileId, onPendingMessageConsumed]);

  const refreshSessions = useCallback(async () => {
    if (!profileId) return;
    const allSessions = await chatService.listSessions(profileId);
    setSessions(allSessions);
  }, [profileId]);

  const createNewSession = async () => {
    if (!profileId) return;

    const session = await chatService.createSession(profileId);
    setSessions((prev) => [session, ...prev]);
    setCurrentSession(session);
    setShowSessions(false);
    inputRef.current?.focus();
  };

  const selectSession = async (session: ChatSession) => {
    setCurrentSession(session);
    setShowSessions(false);
    inputRef.current?.focus();
  };

  const handleSessionsChanged = useCallback(async () => {
    await refreshSessions();
    // If current session was deleted, select the next one
    if (currentSession) {
      const stillExists = await chatService.getSession(currentSession.id);
      if (!stillExists) {
        const allSessions = await chatService.listSessions(profileId!);
        setCurrentSession(allSessions[0] || null);
      } else {
        // Refresh current session to get updated title
        setCurrentSession(stillExists);
      }
    }
  }, [refreshSessions, currentSession, profileId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading || !profileId) return;

    // Create session if needed
    let session = currentSession;
    if (!session) {
      session = await chatService.createSession(profileId);
      setSessions((prev) => [session!, ...prev]);
      setCurrentSession(session);
    }

    const userMessageContent = input.trim();
    setInput('');
    setIsLoading(true);

    // Add user message
    const userMessage = await chatService.addMessage(session.id, {
      role: 'user',
      content: userMessageContent,
    });

    // Update local state
    setCurrentSession((prev) =>
      prev ? { ...prev, messages: [...prev.messages, userMessage] } : null
    );

    // Add assistant placeholder
    const assistantMessage = await chatService.addMessage(session.id, {
      role: 'assistant',
      content: '',
      toolCalls: [],
    });

    setCurrentSession((prev) =>
      prev ? { ...prev, messages: [...prev.messages, assistantMessage] } : null
    );

    try {
      // Build history for API (exclude empty messages)
      const history = session.messages
        .filter((m) => m.content && m.content.trim() !== '')
        .map((m) => ({
          role: m.role,
          content: m.content,
        }));

      // Get visible tracks context for LLM
      const visibleTracksState = useVisibleTracksStore.getState();
      const visibleTrackIds = visibleTracksState.trackIds.slice(0, 100); // Limit to 100

      const response = await fetch('/api/v1/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(profileId && { 'X-Profile-ID': profileId }),
        },
        body: JSON.stringify({
          message: userMessageContent,
          history,
          visible_track_ids: visibleTrackIds,
        }),
      });

      if (!response.ok) {
        // Try to get error detail from response
        const errorData = await response.json().catch(() => null);
        const errorMessage = errorData?.detail || 'Chat request failed';
        throw new Error(errorMessage);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error('No response body');

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (data === '[DONE]') continue;

            try {
              const event = JSON.parse(data);
              await handleStreamEvent(event, session!.id);
            } catch {
              // Ignore parse errors
            }
          }
        }
      }
    } catch (error) {
      console.error('Chat error:', error);
      const errorMessage =
        error instanceof Error
          ? error.message
          : 'Sorry, something went wrong. Please try again.';
      await chatService.updateLastMessage(session.id, {
        content: errorMessage,
      });
      // Update local state to show the error immediately
      setCurrentSession((prev) => {
        if (!prev) return null;
        const messages = [...prev.messages];
        const lastIdx = messages.length - 1;
        messages[lastIdx] = { ...messages[lastIdx], content: errorMessage };
        return { ...prev, messages };
      });
    } finally {
      setIsLoading(false);
      // Refresh session from DB to get final state
      const updatedSession = await chatService.getSession(session.id);
      if (updatedSession) {
        setCurrentSession(updatedSession);
      }
      await refreshSessions();
    }
  };

  const handleStreamEvent = async (
    event: Record<string, unknown>,
    sessionId: string
  ) => {
    switch (event.type) {
      case 'text':
        await chatService.appendToLastMessage(sessionId, event.content as string);
        // Update local state for immediate feedback
        setCurrentSession((prev) => {
          if (!prev) return null;
          const messages = [...prev.messages];
          const lastIdx = messages.length - 1;
          messages[lastIdx] = {
            ...messages[lastIdx],
            content: messages[lastIdx].content + (event.content as string),
          };
          return { ...prev, messages };
        });
        break;

      case 'tool_call': {
        const toolCall: ChatToolCall = {
          name: event.name as string,
          input: event.input as Record<string, unknown>,
          status: 'running',
        };
        await chatService.addToolCallToLastMessage(sessionId, toolCall);
        setCurrentSession((prev) => {
          if (!prev) return null;
          const messages = [...prev.messages];
          const lastIdx = messages.length - 1;
          messages[lastIdx] = {
            ...messages[lastIdx],
            toolCalls: [...(messages[lastIdx].toolCalls || []), toolCall],
          };
          return { ...prev, messages };
        });
        break;
      }

      case 'tool_result': {
        const result = event.result as Record<string, unknown>;
        await chatService.updateToolCallInLastMessage(sessionId, event.name as string, {
          result,
          status: 'complete',
        });
        setCurrentSession((prev) => {
          if (!prev) return null;
          const messages = [...prev.messages];
          const lastIdx = messages.length - 1;
          messages[lastIdx] = {
            ...messages[lastIdx],
            toolCalls: messages[lastIdx].toolCalls?.map((tc) =>
              tc.name === event.name
                ? { ...tc, result, status: 'complete' as const }
                : tc
            ),
          };
          return { ...prev, messages };
        });
        break;
      }

      case 'queue': {
        const tracks = (event.tracks as Track[]).map((t) => ({
          id: t.id,
          title: t.title,
          artist: t.artist,
          album: t.album,
          file_path: '',
          album_artist: null,
          album_type: 'album' as const,
          track_number: null,
          disc_number: null,
          year: null,
          genre: null,
          duration_seconds: null,
          format: null,
          analysis_version: 0,
        }));
        if (tracks.length > 0) {
          setQueue(tracks, 0);
        }
        break;
      }

      case 'playback': {
        const action = event.action as string;
        const store = usePlayerStore.getState();
        if (action === 'play') store.setIsPlaying(true);
        else if (action === 'pause') store.setIsPlaying(false);
        else if (action === 'next') store.playNext();
        else if (action === 'previous') store.playPrevious();
        break;
      }

      case 'error': {
        const errorContent = event.content as string || event.message as string || 'An error occurred';
        console.error('LLM error:', errorContent);
        await chatService.updateLastMessage(sessionId, {
          content: `**Error:** ${errorContent}`,
        });
        setCurrentSession((prev) => {
          if (!prev) return null;
          const messages = [...prev.messages];
          const lastIdx = messages.length - 1;
          messages[lastIdx] = {
            ...messages[lastIdx],
            content: `**Error:** ${errorContent}`,
          };
          return { ...prev, messages };
        });
        break;
      }

      case 'playlist_created': {
        // Invalidate playlists query so the new playlist appears in the list
        queryClient.invalidateQueries({ queryKey: ['playlists'] });
        // Navigate to the playlists view and highlight the new playlist
        window.dispatchEvent(
          new CustomEvent('show-playlist', {
            detail: {
              playlistId: event.playlist_id as string,
              playlistName: event.playlist_name as string,
            },
          })
        );
        break;
      }

      case 'navigate': {
        const view = event.view as string;
        if (view === 'proposed-changes') {
          // Switch to Proposed Changes browser view
          useLibraryViewStore.getState().setSelectedBrowserId('proposed-changes');
          // Refresh the changes list
          queryClient.invalidateQueries({ queryKey: ['proposed-changes'] });
          queryClient.invalidateQueries({ queryKey: ['proposed-changes-stats'] });
        }
        break;
      }
    }
  };

  const messages = currentSession?.messages || [];

  return (
    <div className="relative h-full">
      {/* History panel - overlay that slides out */}
      {showSessions && profileId && (
        <>
          {/* Backdrop to close on click outside */}
          <div
            className="absolute inset-0 bg-black/30 z-10"
            onClick={() => setShowSessions(false)}
          />
          <div className="absolute inset-y-0 left-0 w-[calc(100vw-2rem)] sm:w-72 max-w-72 z-20 shadow-xl">
            <ChatHistoryPanel
              sessions={sessions}
              currentSessionId={currentSession?.id || null}
              profileId={profileId}
              onSelectSession={selectSession}
              onNewSession={createNewSession}
              onSessionsChanged={handleSessionsChanged}
              onClose={() => setShowSessions(false)}
            />
          </div>
        </>
      )}

      {/* Main chat area */}
      <div className="h-full flex flex-col bg-zinc-900">
        {/* Header */}
        <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowSessions(!showSessions)}
              className={`p-2 rounded-lg transition-colors ${
                showSessions
                  ? 'bg-purple-500/20 text-purple-400'
                  : 'hover:bg-zinc-800'
              }`}
              title="Chat history"
            >
              <History className="w-5 h-5" />
            </button>
            <div>
              <h2 className="text-lg font-semibold">Familiar</h2>
              <p className="text-xs text-zinc-500 max-w-[200px] truncate">
                {currentSession ? currentSession.title : 'Ask me to play something'}
              </p>
            </div>
          </div>
          <button
            onClick={createNewSession}
            className="p-2 hover:bg-zinc-800 rounded-lg transition-colors"
            title="New chat"
          >
            <Plus className="w-5 h-5" />
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto overflow-x-hidden px-4 py-4 space-y-4">
          {/* Offline warning */}
          {isOffline && (
            <div className="p-3 bg-amber-900/20 border border-amber-800 rounded-lg flex items-start gap-2">
              <WifiOff className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-sm text-amber-400">You're offline</p>
                <p className="text-xs text-zinc-500 mt-1">
                  Chat requires a network connection. You can still browse and play cached music.
                </p>
              </div>
            </div>
          )}

          {/* LLM configuration warning */}
          {llmStatus && !llmStatus.configured && !isOffline && (
            <div className="p-3 bg-amber-900/20 border border-amber-800 rounded-lg flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-sm text-amber-400">AI assistant not configured</p>
                <p className="text-xs text-zinc-500 mt-1">
                  Configure your API key in the Admin panel to enable the chat.
                </p>
              </div>
            </div>
          )}

          {messages.length === 0 && (
            <div className="text-center py-12 text-zinc-500">
              <Music className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p className="text-sm">Try asking:</p>
              <p className="text-sm italic mt-2">"Play something chill for coding"</p>
              <p className="text-sm italic">"Find me upbeat electronic music"</p>
              <p className="text-sm italic">"What's similar to the current track?"</p>
            </div>
          )}

          {messages.map((message) => (
            <div
              key={message.id}
              className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-[85%] rounded-lg px-4 py-2 ${
                  message.role === 'user'
                    ? 'bg-green-600 text-white'
                    : 'bg-zinc-800 text-zinc-100'
                }`}
              >
                {/* Tool calls */}
                {message.toolCalls && message.toolCalls.length > 0 && (
                  <div className="mb-2 space-y-1">
                    {message.toolCalls.map((tc, i) => (
                      <ToolCallBadge key={i} toolCall={tc} />
                    ))}
                  </div>
                )}

                {/* Message content */}
                <p className="text-sm whitespace-pre-wrap break-words">{message.content}</p>

                {/* Streaming indicator */}
                {message.role === 'assistant' && !message.content && isLoading && (
                  <Loader2 className="w-4 h-4 animate-spin" />
                )}
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <form onSubmit={handleSubmit} data-chat-form className="p-4 border-t border-zinc-800">
          <div className="flex gap-2">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={isOffline ? 'Chat unavailable offline' : 'Ask Familiar...'}
              disabled={isLoading || isOffline}
              className="flex-1 bg-zinc-800 border border-zinc-700 rounded-full px-4 py-2 text-base placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!input.trim() || isLoading || isOffline}
              className="p-2 bg-green-600 text-white rounded-full hover:bg-green-500 disabled:opacity-50 disabled:hover:bg-green-600 transition-colors"
            >
              {isLoading ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Send className="w-5 h-5" />
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ToolCallBadge({ toolCall }: { toolCall: ChatToolCall }) {
  const toolNames: Record<string, string> = {
    search_library: 'Searching',
    find_similar_tracks: 'Finding similar',
    filter_tracks_by_features: 'Filtering',
    get_library_stats: 'Getting stats',
    get_library_genres: 'Getting genres',
    queue_tracks: 'Queueing',
    control_playback: 'Controlling',
    get_track_details: 'Getting details',
    get_spotify_status: 'Checking Spotify',
    get_spotify_favorites: 'Getting favorites',
    get_unmatched_spotify_favorites: 'Finding unmatched',
    get_spotify_sync_stats: 'Sync stats',
    search_bandcamp: 'Searching Bandcamp',
    recommend_bandcamp_purchases: 'Recommending',
    select_diverse_tracks: 'Selecting diverse tracks',
  };

  const displayName = toolNames[toolCall.name] || toolCall.name;
  const trackCount = (toolCall.result as { count?: number })?.count;

  return (
    <div className="flex items-center gap-1.5 text-xs text-zinc-400">
      {toolCall.status === 'running' ? (
        <Loader2 className="w-3 h-3 animate-spin" />
      ) : (
        <Wrench className="w-3 h-3" />
      )}
      <span>{displayName}</span>
      {trackCount !== undefined && (
        <span className="text-zinc-500">({trackCount} tracks)</span>
      )}
    </div>
  );
}
