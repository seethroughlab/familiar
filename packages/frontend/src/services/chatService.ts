/**
 * Chat service for managing chat sessions in IndexedDB.
 */
import { db, type ChatSession, type ChatMessage, type ChatToolCall } from '../db';
import { generateUUID } from '../utils/uuid';

/**
 * Generate a title from the first user message.
 */
function generateTitle(message: string): string {
  // Take first 50 chars, cut at word boundary
  const maxLen = 50;
  if (message.length <= maxLen) return message;

  const truncated = message.slice(0, maxLen);
  const lastSpace = truncated.lastIndexOf(' ');
  return lastSpace > 20 ? truncated.slice(0, lastSpace) + '...' : truncated + '...';
}

/**
 * Create a new chat session.
 */
export async function createSession(profileId: string): Promise<ChatSession> {
  const now = new Date();
  const session: ChatSession = {
    id: generateUUID(),
    profileId,
    title: 'New conversation',
    messages: [],
    createdAt: now,
    updatedAt: now,
  };

  await db.chatSessions.add(session);
  return session;
}

/**
 * Get a chat session by ID.
 */
export async function getSession(sessionId: string): Promise<ChatSession | undefined> {
  return db.chatSessions.get(sessionId);
}

/**
 * List all chat sessions for a profile, sorted by most recent first.
 */
export async function listSessions(profileId: string): Promise<ChatSession[]> {
  return db.chatSessions
    .where('profileId')
    .equals(profileId)
    .reverse()
    .sortBy('updatedAt');
}

/**
 * Add a message to a session.
 */
export async function addMessage(
  sessionId: string,
  message: Omit<ChatMessage, 'id' | 'timestamp'>
): Promise<ChatMessage> {
  const session = await db.chatSessions.get(sessionId);
  if (!session) {
    throw new Error(`Session ${sessionId} not found`);
  }

  const newMessage: ChatMessage = {
    ...message,
    id: generateUUID(),
    timestamp: new Date(),
  };

  const updatedMessages = [...session.messages, newMessage];

  // Update title from first user message if still default
  let title = session.title;
  if (title === 'New conversation' && message.role === 'user' && message.content) {
    title = generateTitle(message.content);
  }

  await db.chatSessions.update(sessionId, {
    messages: updatedMessages,
    title,
    updatedAt: new Date(),
  });

  return newMessage;
}

/**
 * Update the last message in a session (for streaming updates).
 */
export async function updateLastMessage(
  sessionId: string,
  updates: Partial<Omit<ChatMessage, 'id' | 'timestamp'>>
): Promise<void> {
  const session = await db.chatSessions.get(sessionId);
  if (!session || session.messages.length === 0) {
    return;
  }

  const messages = [...session.messages];
  const lastIndex = messages.length - 1;
  messages[lastIndex] = {
    ...messages[lastIndex],
    ...updates,
  };

  await db.chatSessions.update(sessionId, {
    messages,
    updatedAt: new Date(),
  });
}

/**
 * Append content to the last message (for streaming text).
 */
export async function appendToLastMessage(
  sessionId: string,
  content: string
): Promise<void> {
  const session = await db.chatSessions.get(sessionId);
  if (!session || session.messages.length === 0) {
    return;
  }

  const messages = [...session.messages];
  const lastIndex = messages.length - 1;
  messages[lastIndex] = {
    ...messages[lastIndex],
    content: messages[lastIndex].content + content,
  };

  await db.chatSessions.update(sessionId, {
    messages,
    updatedAt: new Date(),
  });
}

/**
 * Add a tool call to the last message.
 */
export async function addToolCallToLastMessage(
  sessionId: string,
  toolCall: ChatToolCall
): Promise<void> {
  const session = await db.chatSessions.get(sessionId);
  if (!session || session.messages.length === 0) {
    return;
  }

  const messages = [...session.messages];
  const lastIndex = messages.length - 1;
  const lastMessage = messages[lastIndex];

  messages[lastIndex] = {
    ...lastMessage,
    toolCalls: [...(lastMessage.toolCalls || []), toolCall],
  };

  await db.chatSessions.update(sessionId, {
    messages,
    updatedAt: new Date(),
  });
}

/**
 * Update a tool call in the last message by name.
 */
export async function updateToolCallInLastMessage(
  sessionId: string,
  toolName: string,
  updates: Partial<ChatToolCall>
): Promise<void> {
  const session = await db.chatSessions.get(sessionId);
  if (!session || session.messages.length === 0) {
    return;
  }

  const messages = [...session.messages];
  const lastIndex = messages.length - 1;
  const lastMessage = messages[lastIndex];

  if (!lastMessage.toolCalls) {
    return;
  }

  messages[lastIndex] = {
    ...lastMessage,
    toolCalls: lastMessage.toolCalls.map((tc) =>
      tc.name === toolName ? { ...tc, ...updates } : tc
    ),
  };

  await db.chatSessions.update(sessionId, {
    messages,
    updatedAt: new Date(),
  });
}

/**
 * Delete a chat session.
 */
export async function deleteSession(sessionId: string): Promise<void> {
  await db.chatSessions.delete(sessionId);
}

/**
 * Rename a chat session.
 */
export async function renameSession(
  sessionId: string,
  title: string
): Promise<void> {
  await db.chatSessions.update(sessionId, {
    title: title.trim() || 'Untitled',
    updatedAt: new Date(),
  });
}

/**
 * Search sessions by title and message content.
 */
export async function searchSessions(
  profileId: string,
  query: string
): Promise<ChatSession[]> {
  const normalizedQuery = query.toLowerCase().trim();
  if (!normalizedQuery) {
    return listSessions(profileId);
  }

  const allSessions = await db.chatSessions
    .where('profileId')
    .equals(profileId)
    .toArray();

  // Filter by title or message content
  const filtered = allSessions.filter((session) => {
    // Check title
    if (session.title.toLowerCase().includes(normalizedQuery)) {
      return true;
    }
    // Check message content
    return session.messages.some((msg) =>
      msg.content.toLowerCase().includes(normalizedQuery)
    );
  });

  // Sort by most recent first
  return filtered.sort(
    (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
  );
}

/**
 * Clear all sessions for a profile.
 */
export async function clearAllSessions(profileId: string): Promise<void> {
  await db.chatSessions.where('profileId').equals(profileId).delete();
}

/**
 * Get session count for a profile.
 */
export async function getSessionCount(profileId: string): Promise<number> {
  return db.chatSessions.where('profileId').equals(profileId).count();
}
