import { useState } from 'react';
import { Copy, Check, Crown, Loader2, Send, UserMinus, Share2, Lock } from 'lucide-react';
import type { SessionInfo, ChatMessage, IceServer } from '../../hooks/useListeningSession';
import { buildShareLink } from '../../hooks/useListeningSession';
import type { FamiliarConfig, SessionReaction, SessionReactionKind } from '../../services/listeningSessionFamiliars';
import { IceDiagnostics } from './IceDiagnostics';
import { FamiliarPicker, FamiliarRoom, ReactionBar } from './FamiliarRoom';
import { showError } from '../../stores/toastStore';
import { useThemeStore } from '../../stores/themeStore';

const CHAT_MESSAGE_MAX_LENGTH = 500;

interface SessionPanelProps {
  session: SessionInfo | null;
  isHost: boolean;
  myUserId: string | null;
  isConnecting: boolean;
  error: string | null;
  hostDisabled: boolean;
  iceServers: IceServer[];
  chatMessages: ChatMessage[];
  reactions: SessionReaction[];
  myFamiliar: FamiliarConfig;
  onCreateSession: (name: string, password?: string) => void;
  onJoinSession: (code: string, password?: string) => void;
  onLeaveSession: () => void;
  onSendMessage: (message: string) => void;
  onReact: (kind: SessionReactionKind) => void;
  onFamiliarChange: (familiar: FamiliarConfig) => void;
  onKick: (userId: string) => void;
}

export function SessionPanel({
  session,
  isHost,
  myUserId,
  isConnecting,
  error,
  hostDisabled,
  iceServers,
  chatMessages,
  reactions,
  myFamiliar,
  onCreateSession,
  onJoinSession,
  onLeaveSession,
  onSendMessage,
  onReact,
  onFamiliarChange,
  onKick,
}: SessionPanelProps) {
  const [mode, setMode] = useState<'menu' | 'create' | 'join'>('menu');
  const [sessionName, setSessionName] = useState('');
  const [createPassword, setCreatePassword] = useState('');
  const [joinCode, setJoinCode] = useState('');
  const [joinPassword, setJoinPassword] = useState('');
  const [chatInput, setChatInput] = useState('');
  const [copied, setCopied] = useState(false);
  const [shareCopied, setShareCopied] = useState(false);
  const isLight = useThemeStore((state) => state.resolvedTheme === 'light');
  const panelBorder = isLight ? 'border-zinc-200' : 'border-zinc-800';
  const panelMuted = isLight ? 'text-zinc-500' : 'text-zinc-400';
  const panelSubtle = isLight ? 'bg-zinc-50' : 'bg-zinc-800';
  const panelSubtleHover = isLight ? 'hover:bg-zinc-100' : 'hover:bg-zinc-700';
  const inputClasses = isLight
    ? 'bg-white border-zinc-200 text-zinc-900 placeholder-zinc-400'
    : 'bg-zinc-800 border-zinc-700 text-white placeholder-zinc-500';

  const handleCopyCode = async () => {
    if (!session) return;
    try {
      await navigator.clipboard.writeText(session.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      showError("Couldn't copy code", { description: 'Select and copy it manually.' });
    }
  };

  const handleCopyShareLink = async () => {
    if (!session) return;
    try {
      await navigator.clipboard.writeText(buildShareLink(session.code));
      setShareCopied(true);
      setTimeout(() => setShareCopied(false), 2000);
    } catch {
      showError("Couldn't copy link", { description: 'Select and copy it manually.' });
    }
  };

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatInput.trim()) return;
    onSendMessage(chatInput);
    setChatInput('');
  };

  if (session) {
    return (
      <div className="h-full flex flex-col">
        <div className={`p-4 border-b ${panelBorder} space-y-4`}>
          <div className={`text-sm ${panelMuted}`}>{session.name}</div>
          <div className="flex items-center gap-2">
            <div className={`flex-1 px-3 py-2 rounded-md font-mono text-lg tracking-wider text-center ${panelSubtle}`}>
              {session.code}
            </div>
            <button
              onClick={handleCopyCode}
              className={`p-2 rounded-md ${panelSubtle} ${panelSubtleHover}`}
              title="Copy code"
              aria-label="Copy session code"
            >
              {copied ? <Check className="w-5 h-5 text-green-500" /> : <Copy className={`w-5 h-5 ${panelMuted}`} />}
            </button>
            <button
              onClick={handleCopyShareLink}
              className={`p-2 rounded-md ${panelSubtle} ${panelSubtleHover}`}
              title="Copy share link"
              aria-label="Copy share link"
            >
              {shareCopied ? <Check className="w-5 h-5 text-green-500" /> : <Share2 className={`w-5 h-5 ${panelMuted}`} />}
            </button>
          </div>
          {session.has_password && (
            <div className={`flex items-center gap-2 text-xs ${panelMuted}`}>
              <Lock className="w-3 h-3" /> Password protected
            </div>
          )}
          {hostDisabled && isHost && (
            <div className="p-2 bg-amber-500/10 border border-amber-500/20 rounded-md text-amber-400 text-xs">
              Listening sessions are not supported on iOS host yet. Listeners can still join, but no audio will stream until you host from a desktop browser.
            </div>
          )}
          {error && (
            <div className="p-2 bg-red-500/20 border border-red-500/30 rounded-md text-red-400 text-xs">
              {error}
            </div>
          )}
          <FamiliarRoom
            participants={session.participants}
            reactions={reactions}
            myUserId={myUserId}
            isLight={isLight}
          />
          <FamiliarPicker value={myFamiliar} onChange={onFamiliarChange} isLight={isLight} />
          <div>
            <div className={`mb-2 text-sm ${panelMuted}`}>Quick reactions</div>
            <ReactionBar onReact={onReact} isLight={isLight} />
          </div>
          {isHost && iceServers.length > 0 && <IceDiagnostics iceServers={iceServers} />}
        </div>

        <div className={`p-4 border-b ${panelBorder}`}>
          <h3 className={`text-sm ${panelMuted} mb-2`}>Listeners ({session.participant_count})</h3>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {session.participants.map((p) => (
              <div key={p.user_id} className="flex items-center justify-between gap-2 text-sm py-1">
                <div className="flex items-center gap-2 min-w-0">
                  {p.role === 'host' && <Crown className="w-4 h-4 text-yellow-500 shrink-0" />}
                  <span className={`truncate ${p.role === 'host' ? (isLight ? 'text-zinc-900' : 'text-white') : isLight ? 'text-zinc-700' : 'text-zinc-300'}`}>
                    {p.username}
                  </span>
                </div>
                {isHost && p.role !== 'host' && (
                  <button
                    onClick={() => onKick(p.user_id)}
                    className={`p-1 ${panelMuted} hover:text-red-400 rounded`}
                    title="Remove from session"
                    aria-label={`Remove ${p.username} from session`}
                  >
                    <UserMinus className="w-4 h-4" />
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="flex-1 flex flex-col min-h-0">
          <div className="flex-1 p-4 overflow-y-auto space-y-2">
            {chatMessages.length === 0 ? (
              <div className={`text-sm ${panelMuted} text-center py-8`}>No messages yet</div>
            ) : (
              chatMessages.map((msg, i) => (
                <div key={i} className="text-sm">
                  <span className={`font-medium ${isLight ? 'text-zinc-800' : 'text-zinc-300'}`}>{msg.username}: </span>
                  <span className={isLight ? 'text-zinc-600' : 'text-zinc-400'}>{msg.message}</span>
                </div>
              ))
            )}
          </div>
          <form onSubmit={handleSendMessage} className={`p-4 border-t ${panelBorder}`}>
            <div className="flex gap-2">
              <input
                type="text"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                placeholder="Send a message..."
                maxLength={CHAT_MESSAGE_MAX_LENGTH}
                className={`flex-1 px-3 py-2 border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-green-500 ${inputClasses}`}
              />
              <button
                type="submit"
                disabled={!chatInput.trim()}
                className="p-2 bg-green-600 hover:bg-green-500 disabled:bg-zinc-700 rounded-md"
                aria-label="Send chat message"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </form>
        </div>

        <div className={`p-4 border-t ${panelBorder}`}>
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

  return (
    <div className="h-full overflow-y-auto p-4">
      {error && (
        <div className="mb-4 p-3 bg-red-500/20 border border-red-500/30 rounded-md text-red-400 text-sm">
          {error}
        </div>
      )}

      {mode === 'menu' && (
        <div className="space-y-3">
          <p className={`text-sm ${panelMuted}`}>
            Listen to music together in real-time. Create a session and share the code or link with friends.
          </p>
          <FamiliarPicker value={myFamiliar} onChange={onFamiliarChange} isLight={isLight} />
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
            <label className={`block text-sm ${panelMuted} mb-2`}>Session name</label>
            <input
              type="text"
              value={sessionName}
              onChange={(e) => setSessionName(e.target.value)}
              placeholder="My Listening Session"
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 ${inputClasses}`}
            />
          </div>
          <div>
            <label className={`block text-sm ${panelMuted} mb-2`}>
              Password (optional)
            </label>
            <input
              type="password"
              value={createPassword}
              onChange={(e) => setCreatePassword(e.target.value)}
              placeholder="Leave blank for open session"
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 ${inputClasses}`}
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
              onClick={() =>
                onCreateSession(sessionName || 'Listening Session', createPassword || undefined)
              }
              disabled={isConnecting}
              className="flex-1 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded-md font-medium transition-colors flex items-center justify-center gap-2"
            >
              {isConnecting && <Loader2 className="w-4 h-4 animate-spin" />}
              Create
            </button>
          </div>
        </div>
      )}

      {mode === 'join' && (
        <div className="space-y-4">
          <div>
            <label className={`block text-sm ${panelMuted} mb-2`}>Join code</label>
            <input
              type="text"
              value={joinCode}
              onChange={(e) => setJoinCode(e.target.value.toUpperCase())}
              placeholder="ABCDEF12"
              className={`w-full px-3 py-2 border rounded-md font-mono text-lg tracking-wider text-center uppercase focus:outline-none focus:ring-2 focus:ring-green-500 ${inputClasses}`}
            />
          </div>
          <div>
            <label className={`block text-sm ${panelMuted} mb-2`}>Password</label>
            <input
              type="password"
              value={joinPassword}
              onChange={(e) => setJoinPassword(e.target.value)}
              placeholder="Leave blank if not required"
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 ${inputClasses}`}
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
              onClick={() => onJoinSession(joinCode, joinPassword || undefined)}
              disabled={isConnecting || joinCode.length < 8}
              className="flex-1 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded-md font-medium transition-colors flex items-center justify-center gap-2"
            >
              {isConnecting && <Loader2 className="w-4 h-4 animate-spin" />}
              Join
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default SessionPanel;
