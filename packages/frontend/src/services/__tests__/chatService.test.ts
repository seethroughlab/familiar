/**
 * Tests for chatService - session CRUD, message streaming, tool call tracking, and search.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock db tables
const mockSessionsAdd = vi.fn();
const mockSessionsGet = vi.fn();
const mockSessionsUpdate = vi.fn();
const mockSessionsDelete = vi.fn();
const mockSessionsWhere = vi.fn();

vi.mock('../../db', () => ({
  db: {
    chatSessions: {
      add: (...args: unknown[]) => mockSessionsAdd(...args),
      get: (...args: unknown[]) => mockSessionsGet(...args),
      update: (...args: unknown[]) => mockSessionsUpdate(...args),
      delete: (...args: unknown[]) => mockSessionsDelete(...args),
      where: (...args: unknown[]) => mockSessionsWhere(...args),
    },
  },
}));

vi.mock('../../utils/uuid', () => ({
  generateUUID: vi.fn(() => 'mock-uuid-' + Math.random().toString(36).slice(2, 8)),
}));

const getModule = async () => await import('../chatService');

describe('chatService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSessionsAdd.mockResolvedValue('mock-id');
    mockSessionsGet.mockResolvedValue(undefined);
    mockSessionsUpdate.mockResolvedValue(1);
    mockSessionsDelete.mockResolvedValue(undefined);
  });

  describe('createSession', () => {
    it('should create a new session with default title', async () => {
      const { createSession } = await getModule();
      const session = await createSession('profile-123');

      expect(session.profileId).toBe('profile-123');
      expect(session.title).toBe('New conversation');
      expect(session.messages).toEqual([]);
      expect(session.createdAt).toBeInstanceOf(Date);
      expect(session.updatedAt).toBeInstanceOf(Date);
      expect(mockSessionsAdd).toHaveBeenCalledWith(session);
    });

    it('should generate a UUID for the session ID', async () => {
      const { createSession } = await getModule();
      const session = await createSession('profile-123');

      expect(session.id).toMatch(/^mock-uuid-/);
    });
  });

  describe('getSession', () => {
    it('should return session by ID', async () => {
      const session = {
        id: 'session-1',
        profileId: 'profile-123',
        title: 'Test',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      };
      mockSessionsGet.mockResolvedValueOnce(session);

      const { getSession } = await getModule();
      const result = await getSession('session-1');

      expect(result?.title).toBe('Test');
      expect(mockSessionsGet).toHaveBeenCalledWith('session-1');
    });

    it('should return undefined for nonexistent session', async () => {
      const { getSession } = await getModule();
      const result = await getSession('nonexistent');

      expect(result).toBeUndefined();
    });
  });

  describe('listSessions', () => {
    it('should list sessions for a profile sorted by updatedAt', async () => {
      const sessions = [
        { id: 's1', profileId: 'p1', title: 'First', messages: [], updatedAt: new Date('2024-01-02') },
        { id: 's2', profileId: 'p1', title: 'Second', messages: [], updatedAt: new Date('2024-01-01') },
      ];
      const mockSortBy = vi.fn().mockResolvedValue(sessions);
      const mockReverse = vi.fn().mockReturnValue({ sortBy: mockSortBy });
      const mockEquals = vi.fn().mockReturnValue({ reverse: mockReverse });
      mockSessionsWhere.mockReturnValue({ equals: mockEquals });

      const { listSessions } = await getModule();
      const result = await listSessions('p1');

      expect(result).toHaveLength(2);
      expect(mockSessionsWhere).toHaveBeenCalledWith('profileId');
      expect(mockEquals).toHaveBeenCalledWith('p1');
      expect(mockSortBy).toHaveBeenCalledWith('updatedAt');
    });
  });

  describe('addMessage', () => {
    it('should add a user message to a session', async () => {
      const session = {
        id: 'session-1',
        profileId: 'p1',
        title: 'New conversation',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      };
      mockSessionsGet.mockResolvedValueOnce(session);

      const { addMessage } = await getModule();
      const msg = await addMessage('session-1', { role: 'user', content: 'Hello world' });

      expect(msg.role).toBe('user');
      expect(msg.content).toBe('Hello world');
      expect(msg.id).toMatch(/^mock-uuid-/);
      expect(msg.timestamp).toBeInstanceOf(Date);
    });

    it('should update session title from first user message', async () => {
      const session = {
        id: 'session-1',
        profileId: 'p1',
        title: 'New conversation',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      };
      mockSessionsGet.mockResolvedValueOnce(session);

      const { addMessage } = await getModule();
      await addMessage('session-1', { role: 'user', content: 'Play some jazz music' });

      expect(mockSessionsUpdate).toHaveBeenCalledWith('session-1', expect.objectContaining({
        title: 'Play some jazz music',
      }));
    });

    it('should truncate long titles at word boundary', async () => {
      const session = {
        id: 'session-1',
        profileId: 'p1',
        title: 'New conversation',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      };
      mockSessionsGet.mockResolvedValueOnce(session);

      const { addMessage } = await getModule();
      const longMessage = 'This is a very long message that should be truncated at a word boundary for the title';
      await addMessage('session-1', { role: 'user', content: longMessage });

      const updateCall = mockSessionsUpdate.mock.calls[0][1];
      expect(updateCall.title.length).toBeLessThanOrEqual(53); // 50 chars + "..."
      expect(updateCall.title.endsWith('...')).toBe(true);
    });

    it('should throw for nonexistent session', async () => {
      const { addMessage } = await getModule();
      await expect(
        addMessage('nonexistent', { role: 'user', content: 'Hello' })
      ).rejects.toThrow('Session nonexistent not found');
    });

    it('should not change title from assistant messages', async () => {
      const session = {
        id: 'session-1',
        profileId: 'p1',
        title: 'New conversation',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      };
      mockSessionsGet.mockResolvedValueOnce(session);

      const { addMessage } = await getModule();
      await addMessage('session-1', { role: 'assistant', content: 'How can I help?' });

      expect(mockSessionsUpdate).toHaveBeenCalledWith('session-1', expect.objectContaining({
        title: 'New conversation',
      }));
    });
  });

  describe('updateLastMessage', () => {
    it('should update the last message with partial data', async () => {
      const session = {
        id: 'session-1',
        profileId: 'p1',
        title: 'Test',
        messages: [
          { id: 'msg-1', role: 'assistant', content: 'Thinking...', timestamp: new Date() },
        ],
        createdAt: new Date(),
        updatedAt: new Date(),
      };
      mockSessionsGet.mockResolvedValueOnce(session);

      const { updateLastMessage } = await getModule();
      await updateLastMessage('session-1', { content: 'Here is the answer.' });

      const updateCall = mockSessionsUpdate.mock.calls[0][1];
      expect(updateCall.messages[0].content).toBe('Here is the answer.');
    });

    it('should do nothing for empty session', async () => {
      mockSessionsGet.mockResolvedValueOnce({
        id: 'session-1', profileId: 'p1', title: 'Test', messages: [],
        createdAt: new Date(), updatedAt: new Date(),
      });

      const { updateLastMessage } = await getModule();
      await updateLastMessage('session-1', { content: 'Update' });

      expect(mockSessionsUpdate).not.toHaveBeenCalled();
    });
  });

  describe('appendToLastMessage', () => {
    it('should append content to the last message', async () => {
      const session = {
        id: 'session-1',
        profileId: 'p1',
        title: 'Test',
        messages: [
          { id: 'msg-1', role: 'assistant', content: 'Hello', timestamp: new Date() },
        ],
        createdAt: new Date(),
        updatedAt: new Date(),
      };
      mockSessionsGet.mockResolvedValueOnce(session);

      const { appendToLastMessage } = await getModule();
      await appendToLastMessage('session-1', ' world');

      const updateCall = mockSessionsUpdate.mock.calls[0][1];
      expect(updateCall.messages[0].content).toBe('Hello world');
    });
  });

  describe('addToolCallToLastMessage', () => {
    it('should add a tool call to the last message', async () => {
      const session = {
        id: 'session-1',
        profileId: 'p1',
        title: 'Test',
        messages: [
          { id: 'msg-1', role: 'assistant', content: 'Searching...', timestamp: new Date() },
        ],
        createdAt: new Date(),
        updatedAt: new Date(),
      };
      mockSessionsGet.mockResolvedValueOnce(session);

      const toolCall = { name: 'search_library', input: { query: 'jazz' }, status: 'running' as const };

      const { addToolCallToLastMessage } = await getModule();
      await addToolCallToLastMessage('session-1', toolCall);

      const updateCall = mockSessionsUpdate.mock.calls[0][1];
      expect(updateCall.messages[0].toolCalls).toHaveLength(1);
      expect(updateCall.messages[0].toolCalls[0].name).toBe('search_library');
    });

    it('should append to existing tool calls', async () => {
      const session = {
        id: 'session-1',
        profileId: 'p1',
        title: 'Test',
        messages: [
          {
            id: 'msg-1', role: 'assistant', content: '', timestamp: new Date(),
            toolCalls: [{ name: 'search_library', input: { query: 'jazz' }, status: 'complete' as const }],
          },
        ],
        createdAt: new Date(),
        updatedAt: new Date(),
      };
      mockSessionsGet.mockResolvedValueOnce(session);

      const { addToolCallToLastMessage } = await getModule();
      await addToolCallToLastMessage('session-1', {
        name: 'create_playlist', input: { tracks: [] }, status: 'running' as const,
      });

      const updateCall = mockSessionsUpdate.mock.calls[0][1];
      expect(updateCall.messages[0].toolCalls).toHaveLength(2);
    });
  });

  describe('updateToolCallInLastMessage', () => {
    it('should update a tool call by name', async () => {
      const session = {
        id: 'session-1',
        profileId: 'p1',
        title: 'Test',
        messages: [
          {
            id: 'msg-1', role: 'assistant', content: '', timestamp: new Date(),
            toolCalls: [{ name: 'search_library', input: { query: 'jazz' }, status: 'running' as const }],
          },
        ],
        createdAt: new Date(),
        updatedAt: new Date(),
      };
      mockSessionsGet.mockResolvedValueOnce(session);

      const { updateToolCallInLastMessage } = await getModule();
      await updateToolCallInLastMessage('session-1', 'search_library', {
        status: 'complete',
        result: { tracks: [], count: 0 },
      });

      const updateCall = mockSessionsUpdate.mock.calls[0][1];
      expect(updateCall.messages[0].toolCalls[0].status).toBe('complete');
      expect(updateCall.messages[0].toolCalls[0].result).toEqual({ tracks: [], count: 0 });
    });
  });

  describe('deleteSession', () => {
    it('should delete a session by ID', async () => {
      const { deleteSession } = await getModule();
      await deleteSession('session-1');

      expect(mockSessionsDelete).toHaveBeenCalledWith('session-1');
    });
  });

  describe('renameSession', () => {
    it('should rename a session', async () => {
      const { renameSession } = await getModule();
      await renameSession('session-1', 'New Title');

      expect(mockSessionsUpdate).toHaveBeenCalledWith('session-1', expect.objectContaining({
        title: 'New Title',
      }));
    });

    it('should use "Untitled" for empty title', async () => {
      const { renameSession } = await getModule();
      await renameSession('session-1', '  ');

      expect(mockSessionsUpdate).toHaveBeenCalledWith('session-1', expect.objectContaining({
        title: 'Untitled',
      }));
    });
  });

  describe('searchSessions', () => {
    it('should search by title', async () => {
      const sessions = [
        { id: 's1', profileId: 'p1', title: 'Jazz playlist', messages: [{ content: 'msg' }], updatedAt: new Date('2024-01-02') },
        { id: 's2', profileId: 'p1', title: 'Rock playlist', messages: [{ content: 'msg' }], updatedAt: new Date('2024-01-01') },
      ];
      const mockToArray = vi.fn().mockResolvedValue(sessions);
      const mockEquals = vi.fn().mockReturnValue({ toArray: mockToArray });
      mockSessionsWhere.mockReturnValue({ equals: mockEquals });

      const { searchSessions } = await getModule();
      const result = await searchSessions('p1', 'jazz');

      expect(result).toHaveLength(1);
      expect(result[0].title).toBe('Jazz playlist');
    });

    it('should search by message content', async () => {
      const sessions = [
        { id: 's1', profileId: 'p1', title: 'Chat 1', messages: [{ content: 'Play some jazz for me' }], updatedAt: new Date() },
        { id: 's2', profileId: 'p1', title: 'Chat 2', messages: [{ content: 'Play rock music' }], updatedAt: new Date() },
      ];
      const mockToArray = vi.fn().mockResolvedValue(sessions);
      const mockEquals = vi.fn().mockReturnValue({ toArray: mockToArray });
      mockSessionsWhere.mockReturnValue({ equals: mockEquals });

      const { searchSessions } = await getModule();
      const result = await searchSessions('p1', 'jazz');

      expect(result).toHaveLength(1);
      expect(result[0].id).toBe('s1');
    });

    it('should return all sessions for empty query', async () => {
      const sessions = [
        { id: 's1', profileId: 'p1', title: 'Chat', messages: [], updatedAt: new Date() },
      ];
      const mockSortBy = vi.fn().mockResolvedValue(sessions);
      const mockReverse = vi.fn().mockReturnValue({ sortBy: mockSortBy });
      const mockEquals = vi.fn().mockReturnValue({ reverse: mockReverse });
      mockSessionsWhere.mockReturnValue({ equals: mockEquals });

      const { searchSessions } = await getModule();
      const result = await searchSessions('p1', '  ');

      expect(result).toHaveLength(1);
    });
  });

  describe('clearAllSessions', () => {
    it('should delete all sessions for a profile', async () => {
      const mockDeleteResult = vi.fn().mockResolvedValue(5);
      const mockEquals = vi.fn().mockReturnValue({ delete: mockDeleteResult });
      mockSessionsWhere.mockReturnValue({ equals: mockEquals });

      const { clearAllSessions } = await getModule();
      await clearAllSessions('p1');

      expect(mockSessionsWhere).toHaveBeenCalledWith('profileId');
      expect(mockEquals).toHaveBeenCalledWith('p1');
      expect(mockDeleteResult).toHaveBeenCalled();
    });
  });

  describe('getSessionCount', () => {
    it('should return session count for a profile', async () => {
      const mockCountResult = vi.fn().mockResolvedValue(7);
      const mockEquals = vi.fn().mockReturnValue({ count: mockCountResult });
      mockSessionsWhere.mockReturnValue({ equals: mockEquals });

      const { getSessionCount } = await getModule();
      const count = await getSessionCount('p1');

      expect(count).toBe(7);
    });
  });
});
