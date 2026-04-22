import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Send, Loader2, Music, Wrench, Plus, History, AlertTriangle, WifiOff, X } from 'lucide-react';
import { chatApi, parseChatStreamEvent, type ChatStreamEvent } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import { createLogger } from '../../utils/logger';

const log = createLogger('ChatPanel');
import { useQueryClient } from '@tanstack/react-query';
import { usePlayerStore } from '../../stores/playerStore';
import { useVisibleTracksStore } from '../../stores/visibleTracksStore';
import { useEphemeralPlaylistStore } from '../../stores/ephemeralPlaylistStore';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';
import { getOrCreateDeviceProfile } from '../../services/profileService';
import * as chatService from '../../services/chatService';
import { ChatHistoryPanel } from './ChatHistoryPanel';
import { notifyError } from '../../utils/errorNotifications';
import type { ChatSession, ChatToolCall } from '../../db';

interface ChatPanelProps {
  /** Pre-filled message to auto-submit (from context menu actions) */
  pendingMessage?: string | null;
  /** Called after pending message is consumed */
  onPendingMessageConsumed?: () => void;
  /** Called when close button is clicked (renders inline X in header) */
  onClose?: () => void;
}

export function ChatPanel({ pendingMessage, onPendingMessageConsumed, onClose }: ChatPanelProps = {}) {
  const chatNavigate = useNavigate();
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
  const setQueue = usePlayerStore((s) => s.setQueue);
  const { isOffline } = useOfflineStatus();

  // Load profile and sessions on mount
  useEffect(() => {
    const init = async () => {
      try {
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
      } catch (error) {
        log.error('Failed to initialize chat:', error);
        notifyError(error, { operation: 'initialize chat' });
      }
    };
    init();
  }, []);

  // Check LLM configuration status on mount
  // Track network vs config errors separately
  const [llmError, setLlmError] = useState<'network' | null>(null);
  useEffect(() => {
    chatApi.getStatus()
      .then((status) => {
        setLlmStatus(status);
        setLlmError(null);
      })
      .catch((error) => {
        log.error('Failed to check LLM status:', error);
        // Distinguish network errors from config errors
        setLlmError('network');
        setLlmStatus(null);
      });
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

      const response = await chatApi.stream({
        message: userMessageContent,
        history,
        visible_track_ids: visibleTrackIds,
      }, profileId);

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
              const parsed = parseChatStreamEvent(JSON.parse(data));
              if (parsed) {
                await handleStreamEvent(parsed, session!.id);
              }
            } catch {
              // Ignore parse errors
            }
          }
        }
      }
    } catch (error) {
      log.error('Chat error:', error);
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
    event: ChatStreamEvent,
    sessionId: string
  ) => {
    switch (event.type) {
      case 'text':
        await chatService.appendToLastMessage(sessionId, event.content);
        // Update local state for immediate feedback
        setCurrentSession((prev) => {
          if (!prev) return null;
          const messages = [...prev.messages];
          const lastIdx = messages.length - 1;
          messages[lastIdx] = {
            ...messages[lastIdx],
            content: messages[lastIdx].content + event.content,
          };
          return { ...prev, messages };
        });
        break;

      case 'tool_call': {
        const toolCall: ChatToolCall = {
          name: event.name,
          input: event.input,
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
        const result = event.result;
        await chatService.updateToolCallInLastMessage(sessionId, event.name, {
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
        const tracks = event.tracks.map((t) => ({
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
        const action = event.action;
        const store = usePlayerStore.getState();
        if (action === 'play') store.setIsPlaying(true);
        else if (action === 'pause') store.setIsPlaying(false);
        else if (action === 'next') store.playNext();
        else if (action === 'previous') store.playPrevious();
        break;
      }

      case 'error': {
        const errorContent = event.content || event.message || 'An error occurred';
        log.error('LLM error:', errorContent);
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

      case 'ephemeral_playlist_created': {
        // Add to ephemeral store instead of saving to database
        const tracks = event.tracks || [];
        const trackIds = event.track_ids || [];
        const name = event.name || 'AI Playlist';
        const generationPrompt = event.generation_prompt || '';

        const ephemeralId = useEphemeralPlaylistStore.getState().addPlaylist({
          name,
          generationPrompt,
          tracks,
          trackIds,
        });

        // Navigate to the playlists view to show the unsaved section
        window.dispatchEvent(
          new CustomEvent('show-ephemeral-playlist', {
            detail: { ephemeralId },
          })
        );
        break;
      }

      case 'navigate': {
        const view = event.view;
        if (view === 'proposed-changes') {
          // Navigate to Proposed Changes browser view
          chatNavigate('/library/proposed-changes');
          // Refresh the changes list
          queryClient.invalidateQueries({ queryKey: queryKeys.proposedChanges.all });
          queryClient.invalidateQueries({ queryKey: queryKeys.proposedChanges.stats });
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
          <div className="flex items-center gap-1">
            <button
              onClick={createNewSession}
              className="p-2 hover:bg-zinc-800 rounded-lg transition-colors"
              title="New chat"
            >
              <Plus className="w-5 h-5" />
            </button>
            {onClose && (
              <button
                onClick={onClose}
                className="p-2 hover:bg-zinc-800 rounded-lg transition-colors"
                aria-label="Close chat"
              >
                <X className="w-5 h-5" />
              </button>
            )}
          </div>
        </div>

        {/* Messages */}
        <div role="log" aria-label="Chat messages" className="flex-1 overflow-y-auto overflow-x-hidden px-4 py-4 space-y-4">
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

          {/* LLM network error warning */}
          {llmError === 'network' && !isOffline && (
            <div className="p-3 bg-red-900/20 border border-red-800 rounded-lg flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-red-400 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-sm text-red-400">Connection error</p>
                <p className="text-xs text-zinc-500 mt-1">
                  Could not connect to the server. Check your network connection and try refreshing.
                </p>
              </div>
            </div>
          )}

          {/* LLM configuration warning */}
          {llmStatus && !llmStatus.configured && !isOffline && !llmError && (
            <div className="p-3 bg-amber-900/20 border border-amber-800 rounded-lg flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-sm text-amber-400">
                  AI assistant not configured
                  {llmStatus.provider ? ` (${llmStatus.provider})` : ''}
                </p>
                <p className="text-xs text-zinc-500 mt-1">
                  {llmStatus.provider === 'openai'
                    ? 'Set OPENAI_API_KEY, OPENAI_CHAT_MODEL, and OPENAI_UTILITY_MODEL in docker-compose to enable the chat.'
                    : 'Set ANTHROPIC_API_KEY in docker-compose to enable the chat.'}
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
                <p className="text-sm whitespace-pre-wrap break-words select-text">{message.content}</p>

                {/* Streaming indicator */}
                {message.role === 'assistant' && !message.content && isLoading && (
                  <Loader2 role="status" aria-label="Generating response" className="w-4 h-4 animate-spin" />
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
              aria-label="Chat message"
              className="flex-1 bg-zinc-800 border border-zinc-700 rounded-full px-4 py-2 text-base placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!input.trim() || isLoading || isOffline}
              aria-label={isLoading ? 'Sending message' : 'Send message'}
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
