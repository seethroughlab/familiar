import api from './base';

// Plugins API
export type PluginType = 'visualizer' | 'browser';

export interface PluginAuthor {
  name: string | null;
  url: string | null;
}

export interface Plugin {
  id: string;
  plugin_id: string;
  name: string;
  version: string;
  type: PluginType;
  description: string | null;
  author: PluginAuthor | null;
  repository_url: string;
  enabled: boolean;
  load_error: string | null;
  api_version: number;
  icon: string | null;
  preview: string | null;
}

export interface PluginListResponse {
  plugins: Plugin[];
  total: number;
}

export interface PluginInstallRequest {
  url: string;
}

export interface PluginInstallResponse {
  success: boolean;
  plugin_id: string | null;
  error: string | null;
}

export interface PluginUpdateCheckResponse {
  has_update: boolean;
  current_version: string;
  latest_version: string | null;
  error: string | null;
}

export const pluginsApi = {
  list: async (params?: {
    type?: PluginType;
    enabled_only?: boolean;
  }): Promise<PluginListResponse> => {
    const { data } = await api.get('/plugins', { params });
    return data;
  },

  get: async (pluginId: string): Promise<Plugin> => {
    const { data } = await api.get(`/plugins/${pluginId}`);
    return data;
  },

  install: async (url: string): Promise<PluginInstallResponse> => {
    const { data } = await api.post('/plugins/install', { url });
    return data;
  },

  update: async (
    pluginId: string,
    settings: { enabled?: boolean }
  ): Promise<Plugin> => {
    const { data } = await api.patch(`/plugins/${pluginId}`, settings);
    return data;
  },

  uninstall: async (pluginId: string): Promise<{ success: boolean }> => {
    const { data } = await api.delete(`/plugins/${pluginId}`);
    return data;
  },

  checkUpdate: async (pluginId: string): Promise<PluginUpdateCheckResponse> => {
    const { data } = await api.post(`/plugins/${pluginId}/check-update`);
    return data;
  },

  updateVersion: async (pluginId: string): Promise<PluginInstallResponse> => {
    const { data } = await api.post(`/plugins/${pluginId}/update`);
    return data;
  },

  reportError: async (
    pluginId: string,
    error: string
  ): Promise<{ success: boolean }> => {
    const { data } = await api.post(`/plugins/${pluginId}/report-error`, {
      error,
    });
    return data;
  },
};
