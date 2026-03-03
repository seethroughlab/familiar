import { useState } from 'react';
import { Users, X, Copy, Check, Send, Crown, Loader2 } from 'lucide-react';
import type { SessionInfo, ChatMessage } from '../../hooks/useListeningSession';

interface SessionPanelProps {
  session: SessionInfo | null;
  isHost: boolean;
  isConnecting: boolean;
  error: string | null;
  chatMessages: ChatMessage[];
  onCreateSession: (name: string) => void;
  onJoinSession: (code: string) => void;
  onLeaveSession: () => void;
  onSendMessage: (message: string) => void;
  onClose: () => void;
}

export function SessionPanel({
  session,
  isHost,
  isConnecting,
  error,
  chatMessages,
  onCreateSession,
  onJoinSession,
  onLeaveSession,
  onSendMessage,
  onClose,
}: SessionPanelProps) {
  const [mode, setMode] = useState<'menu' | 'create' | 'join'>('menu');
  const [sessionName, setSessionName] = useState('');
  const [joinCode, setJoinCode] = useState('');
  const [chatInput, setChatInput] = useState('');
  const [copied, setCopied] = useState(false);

  const handleCopyCode = async () => {
    if (!session) return;
    await navigator.clipboard.writeText(session.code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatInput.trim()) return;
    onSendMessage(chatInput);
    setChatInput('');
  };

  // Active session view
  if (session) {
    return (
      <div className="fixed inset-y-0 right-0 w-80 bg-zinc-900 border-l border-zinc-800 flex flex-col z-40">
        {/* Header */}
        <div className="p-4 border-b border-zinc-800">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Users className="w-5 h-5 text-green-500" />
              <span className="font-medium">{session.name}</span>
            </div>
            <button
              onClick={onClose}
              className="p-1 hover:bg-zinc-800 rounded-md"
            >
              <X className="w-5 h-5 text-zinc-400" />
            </button>
          </div>

          {/* Join code */}
          <div className="mt-3 flex items-center gap-2">
            <div className="flex-1 px-3 py-2 bg-zinc-800 rounded-md font-mono text-lg tracking-wider text-center">
              {session.code}
            </div>
            <button
              onClick={handleCopyCode}
              className="p-2 bg-zinc-800 hover:bg-zinc-700 rounded-md transition-colors"
              title="Copy code"
            >
              {copied ? (
                <Check className="w-5 h-5 text-green-500" />
              ) : (
                <Copy className="w-5 h-5 text-zinc-400" />
              )}
            </button>
          </div>
        </div>

        {/* Participants */}
        <div className="p-4 border-b border-zinc-800">
          <h3 className="text-sm text-zinc-400 mb-2">
            Listeners ({session.participant_count})
          </h3>
          <div className="space-y-2 max-h-32 overflow-y-auto">
            {session.participants.map((p) => (
              <div key={p.user_id} className="flex items-center gap-2 text-sm">
                {p.role === 'host' && (
                  <Crown className="w-4 h-4 text-yellow-500" />
                )}
                <span className={p.role === 'host' ? 'text-white' : 'text-zinc-400'}>
                  {p.username}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Chat */}
        <div className="flex-1 flex flex-col min-h-0">
          <div className="flex-1 p-4 overflow-y-auto space-y-3">
            {chatMessages.length === 0 ? (
              <div className="text-sm text-zinc-500 text-center py-8">
                No messages yet
              </div>
            ) : (
              chatMessages.map((msg, i) => (
                <div key={i} className="text-sm">
                  <span className="font-medium text-zinc-300">{msg.username}: </span>
                  <span className="text-zinc-400">{msg.message}</span>
                </div>
              ))
            )}
          </div>

          {/* Chat input */}
          <form onSubmit={handleSendMessage} className="p-4 border-t border-zinc-800">
            <div className="flex gap-2">
              <input
                type="text"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                placeholder="Send a message..."
                className="flex-1 px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-md text-sm placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-green-500"
              />
              <button
                type="submit"
                disabled={!chatInput.trim()}
                className="p-2 bg-green-600 hover:bg-green-500 disabled:bg-zinc-700 rounded-md transition-colors"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </form>
        </div>

        {/* Leave button */}
        <div className="p-4 border-t border-zinc-800">
          <button
            onClick={onLeaveSession}
            className="w-full py-2 bg-red-600/20 hover:bg-red-600/30 text-red-400 rounded-md transition-colors"
          >
            {isHost ? 'End Session' : 'Leave Session'}
          </button>
        </div>
      </div>
    );
  }

  // Create/Join menu
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-zinc-900 rounded-xl border border-zinc-800 w-full max-w-md mx-4">
        {/* Header */}
        <div className="p-4 border-b border-zinc-800 flex items-center justify-between">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Users className="w-5 h-5 text-green-500" />
            Listening Session
          </h2>
          <button
            onClick={onClose}
            className="p-1 hover:bg-zinc-800 rounded-md"
          >
            <X className="w-5 h-5 text-zinc-400" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4">
          {error && (
            <div className="mb-4 p-3 bg-red-500/20 border border-red-500/30 rounded-md text-red-400 text-sm">
              {error}
            </div>
          )}

          {mode === 'menu' && (
            <div className="space-y-3">
              <p className="text-sm text-zinc-400 mb-4">
                Listen to music together in real-time with friends.
              </p>
              <button
                onClick={() => setMode('create')}
                className="w-full py-3 bg-green-600 hover:bg-green-500 text-white rounded-lg font-medium transition-colors"
              >
                Create Session
              </button>
              <button
                onClick={() => setMode('join')}
                className="w-full py-3 bg-zinc-800 hover:bg-zinc-700 text-white rounded-lg font-medium transition-colors"
              >
                Join Session
              </button>
            </div>
          )}

          {mode === 'create' && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm text-zinc-400 mb-2">
                  Session Name
                </label>
                <input
                  type="text"
                  value={sessionName}
                  onChange={(e) => setSessionName(e.target.value)}
                  placeholder="My Listening Session"
                  className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-md placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-green-500"
                />
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setMode('menu')}
                  className="flex-1 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-md transition-colors"
                >
                  Back
                </button>
                <button
                  onClick={() => onCreateSession(sessionName || 'Listening Session')}
                  disabled={isConnecting}
                  className="flex-1 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded-md font-medium transition-colors flex items-center justify-center gap-2"
                >
                  {isConnecting ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : null}
                  Create
                </button>
              </div>
            </div>
          )}

          {mode === 'join' && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm text-zinc-400 mb-2">
                  Join Code
                </label>
                <input
                  type="text"
                  value={joinCode}
                  onChange={(e) => setJoinCode(e.target.value.toUpperCase())}
                  placeholder="ABC123"
                  maxLength={6}
                  className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-md font-mono text-lg tracking-wider text-center uppercase placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-green-500"
                />
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setMode('menu')}
                  className="flex-1 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-md transition-colors"
                >
                  Back
                </button>
                <button
                  onClick={() => onJoinSession(joinCode)}
                  disabled={isConnecting || joinCode.length !== 6}
                  className="flex-1 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded-md font-medium transition-colors flex items-center justify-center gap-2"
                >
                  {isConnecting ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : null}
                  Join
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
