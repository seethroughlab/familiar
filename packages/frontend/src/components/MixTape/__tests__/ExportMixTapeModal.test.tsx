/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ExportMixTapeModal } from '../ExportMixTapeModal';

vi.mock('../../../api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../../api');
  return {
    ...actual,
    mixtapesApi: {
      create: vi.fn(),
    },
  };
});

vi.mock('../../../stores/toastStore', () => ({
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

import { mixtapesApi } from '../../../api';

function renderModal(extraProps: Partial<Parameters<typeof ExportMixTapeModal>[0]> = {}) {
  const onClose = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const props = {
    isOpen: true,
    onClose,
    source: { kind: 'playlist', id: 'pl-123', defaultName: 'Workout' },
    ...extraProps,
  } as Parameters<typeof ExportMixTapeModal>[0];
  const utils = render(
    <QueryClientProvider client={client}>
      <ExportMixTapeModal {...props} />
    </QueryClientProvider>
  );
  return { ...utils, onClose };
}

describe('ExportMixTapeModal', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('does not render when closed', () => {
    const { container } = renderModal({ isOpen: false });
    expect(container.querySelector('input')).toBeNull();
  });

  it('prefills the name with "<Playlist Name> Mix Tape"', () => {
    renderModal();
    const input = screen.getByPlaceholderText('My Mix Tape') as HTMLInputElement;
    expect(input.value).toBe('Workout Mix Tape');
  });

  it('shows the duration slider when crossfade is checked, hides when unchecked', () => {
    renderModal();
    // Default: enabled → slider visible
    expect(screen.getByText('5s')).toBeTruthy();
    const checkbox = screen.getByRole('checkbox') as HTMLInputElement;
    fireEvent.click(checkbox);
    expect(screen.queryByText(/^\d+s$/)).toBeNull();
  });

  it('submits the request and closes on success', async () => {
    (mixtapesApi.create as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: 'mt-1',
      name: 'Workout Mix Tape',
      status: 'pending',
    });
    const { onClose } = renderModal();

    fireEvent.click(screen.getByText('Start Render'));

    await waitFor(() => {
      expect(mixtapesApi.create).toHaveBeenCalledWith({
        name: 'Workout Mix Tape',
        crossfade_seconds: 5,
        byline: null,
        source_playlist_id: 'pl-123',
      });
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('renders an optional byline input', () => {
    renderModal();
    const bylineInput = screen.getByPlaceholderText('Your name') as HTMLInputElement;
    expect(bylineInput).toBeTruthy();
    expect(bylineInput.value).toBe('');
  });

  it('sends a trimmed byline in the payload when filled', async () => {
    (mixtapesApi.create as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: 'mt-byline',
      name: 'Workout Mix Tape',
      status: 'pending',
    });
    renderModal();
    const bylineInput = screen.getByPlaceholderText('Your name');
    fireEvent.change(bylineInput, { target: { value: '  Jeff  ' } });
    fireEvent.click(screen.getByText('Start Render'));

    await waitFor(() => {
      expect(mixtapesApi.create).toHaveBeenCalledWith(
        expect.objectContaining({ byline: 'Jeff' })
      );
    });
  });

  it('passes source_smart_playlist_id when source kind is smart_playlist', async () => {
    (mixtapesApi.create as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: 'mt-2',
      name: 'Smart Mix Tape',
      status: 'pending',
    });
    renderModal({
      source: { kind: 'smart_playlist', id: 'sp-9', defaultName: 'Smart' },
    });
    fireEvent.click(screen.getByText('Start Render'));

    await waitFor(() => {
      expect(mixtapesApi.create).toHaveBeenCalledWith(
        expect.objectContaining({ source_smart_playlist_id: 'sp-9' })
      );
    });
  });

  it('omits crossfade_seconds when crossfade is disabled', async () => {
    (mixtapesApi.create as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: 'mt-3',
      name: 'No Xfade',
      status: 'pending',
    });
    renderModal();
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByText('Start Render'));

    await waitFor(() => {
      expect(mixtapesApi.create).toHaveBeenCalledWith(
        expect.objectContaining({ crossfade_seconds: null })
      );
    });
  });

  it('disables submit when name is empty', () => {
    renderModal({
      source: { kind: 'playlist', id: 'pl-x', defaultName: '' },
    });
    const button = screen.getByText('Start Render') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });
});
