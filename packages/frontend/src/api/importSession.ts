import api from './base';

export interface QualityInfo {
  format_tier: number;
  format_tier_name: string;
  bitrate: number | null;
  sample_rate: number | null;
  bit_depth: number | null;
  is_lossless: boolean;
  bitrate_mode: string | null;
}

export interface TrackPreview {
  filename: string;
  relative_path: string;
  detected_artist: string | null;
  detected_album: string | null;
  detected_title: string | null;
  detected_track_num: number | null;
  detected_year: number | null;
  format: string;
  duration_seconds: number | null;
  file_size_bytes: number;
  sample_rate: number | null;
  bit_depth: number | null;
  bitrate: number | null;
  bitrate_mode: string | null;
  duplicate_of: string | null;
  duplicate_info: string | null;
  duplicate_match_type: 'exact' | 'normalized' | 'artist_title' | null;
  trump_status: 'trumps' | 'trumped_by' | 'equal' | null;
  trump_reason: string | null;
  incoming_quality: QualityInfo | null;
  existing_quality: QualityInfo | null;
}

export interface PreviewResponse {
  session_id: string;
  tracks: TrackPreview[];
  total_size_bytes: number;
  estimated_sizes: {
    original: number;
    flac: number;
    mp3_320: number;
  };
  has_convertible_formats: boolean;
}

export interface ImportTrackPayload {
  filename: string;
  relative_path: string;
  artist: string | null;
  album: string | null;
  title: string | null;
  track_num: number | null;
  year: number | null;
  detected_artist: string | null;
  detected_album: string | null;
  detected_title: string | null;
  detected_track_num: number | null;
  detected_year: number | null;
  action: 'import' | 'replace' | 'skip';
  replace_track_id: string | null;
}

export interface ExecuteImportOptions {
  format: 'original' | 'flac' | 'mp3';
  mp3_quality: number;
  organization: 'organized' | 'imports';
  queue_analysis: boolean;
}

export interface ExecuteImportRequest {
  session_id: string;
  tracks: ImportTrackPayload[];
  options: ExecuteImportOptions;
}

export interface ExecuteImportResponse {
  imported_count: number;
  replaced_count?: number;
  errors?: string[];
}

export const importSessionApi = {
  preview: async (
    file: File,
    onProgress?: (progressPercent: number) => void,
  ): Promise<PreviewResponse> => {
    const formData = new FormData();
    formData.append('file', file);

    const { data } = await api.post('/library/import/preview', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (progressEvent) => {
        if (progressEvent.total && onProgress) {
          const percent = Math.round((progressEvent.loaded / progressEvent.total) * 100);
          onProgress(percent);
        }
      },
    });

    return data;
  },

  execute: async (request: ExecuteImportRequest): Promise<ExecuteImportResponse> => {
    const { data } = await api.post('/library/import/execute', request);
    return data;
  },
};
