/**
 * Ambient mode API client.
 */

import api from './base';
import type {
  AmbientSeedRequest,
  AmbientSeedResponse,
  AmbientCandidatesRequest,
  AmbientCandidatesResponse,
  AmbientDescriptor,
} from '../player/ambient/types';

export const ambientApi = {
  getSeed: async (request: AmbientSeedRequest): Promise<AmbientSeedResponse> => {
    const { data } = await api.post('/ambient/seed', request);
    return data;
  },

  getCandidates: async (request: AmbientCandidatesRequest): Promise<AmbientCandidatesResponse> => {
    const { data } = await api.post('/ambient/candidates', request);
    return data;
  },

  getDescriptor: async (trackId: string): Promise<AmbientDescriptor> => {
    const { data } = await api.get(`/ambient/descriptor/${trackId}`);
    return data;
  },
};
