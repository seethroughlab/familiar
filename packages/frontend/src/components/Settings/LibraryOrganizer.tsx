/**
 * Library organization settings component.
 */
import { useState, useEffect } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
  FolderTree,
  Eye,
  Loader2,
  CheckCircle,
  XCircle,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { organizerApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import type { OrganizeStats, OrganizeResult } from '../../api';

export function LibraryOrganizer() {
  const [selectedTemplate, setSelectedTemplate] = useState<string>('');
  const [showResults, setShowResults] = useState(false);
  const [previewStats, setPreviewStats] = useState<OrganizeStats | null>(null);

  const { data: templatesData, isLoading: templatesLoading } = useQuery({
    queryKey: queryKeys.organizeTemplates.all,
    queryFn: organizerApi.getTemplates,
  });

  const previewMutation = useMutation({
    mutationFn: () => organizerApi.preview(selectedTemplate || templatesData?.templates[0].template || '', 100),
    onSuccess: (data) => {
      setPreviewStats(data);
      setShowResults(true);
    },
  });

  const templates = templatesData?.templates || [];
  const currentTemplate = templates.find(t => t.template === selectedTemplate) || templates[0];

  // Set default template when loaded
  useEffect(() => {
    if (templates.length > 0 && !selectedTemplate) {
      setSelectedTemplate(templates[0].template);
    }
  }, [templates, selectedTemplate]);

  const getStatusIcon = (status: OrganizeResult['status']) => {
    switch (status) {
      case 'moved':
        return <CheckCircle className="w-4 h-4 text-green-500" />;
      case 'skipped':
        return <AlertTriangle className="w-4 h-4 text-yellow-500" />;
      case 'error':
        return <XCircle className="w-4 h-4 text-red-500" />;
    }
  };

  const getStatusColor = (status: OrganizeResult['status']) => {
    switch (status) {
      case 'moved':
        return 'text-green-400';
      case 'skipped':
        return 'text-yellow-400';
      case 'error':
        return 'text-red-400';
    }
  };

  if (templatesLoading) {
    return (
      <div className="bg-zinc-800/50 rounded-lg p-4">
        <div className="flex items-center gap-3">
          <Loader2 className="w-5 h-5 animate-spin text-zinc-400" />
          <span className="text-zinc-400">Loading...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-zinc-800/50 rounded-lg p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="p-2 bg-zinc-700 rounded-lg">
          <FolderTree className="w-5 h-5 text-blue-400" />
        </div>
        <div>
          <h4 className="font-medium text-white">Library Organization</h4>
          <p className="text-xs text-zinc-400">
            Preview how your library would be organized
          </p>
        </div>
      </div>

      {/* Template selector */}
      <div>
        <label className="block text-sm text-zinc-400 mb-2">Organization Template</label>
        <select
          value={selectedTemplate}
          onChange={(e) => {
            setSelectedTemplate(e.target.value);
            setPreviewStats(null);
            setShowResults(false);
          }}
          className="w-full px-3 py-2 bg-zinc-700 border border-zinc-600 rounded-md text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {templates.map((t) => (
            <option key={t.name} value={t.template}>
              {t.name}
            </option>
          ))}
        </select>
        {currentTemplate && (
          <div className="mt-2 p-2 bg-zinc-900/50 rounded text-xs font-mono text-zinc-400">
            <div className="text-zinc-500 mb-1">Template:</div>
            <div className="text-zinc-300">{currentTemplate.template}</div>
            <div className="text-zinc-500 mt-2 mb-1">Example:</div>
            <div className="text-blue-300">{currentTemplate.example}</div>
          </div>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex flex-col sm:flex-row gap-2">
        <button
          onClick={() => previewMutation.mutate()}
          disabled={previewMutation.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-zinc-700 hover:bg-zinc-600 text-white rounded-md disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {previewMutation.isPending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Eye className="w-4 h-4" />
          )}
          Preview
        </button>
      </div>

      {/* Results */}
      {previewStats && (
        <div className="space-y-3">
          {/* Stats summary */}
          <div className="flex items-center justify-between p-3 bg-zinc-900/50 rounded-md">
            <div className="flex items-center gap-4">
              <div className="text-center">
                <div className="text-xl font-bold text-white">{previewStats.total}</div>
                <div className="text-xs text-zinc-500">Total</div>
              </div>
              <div className="text-center">
                <div className="text-xl font-bold text-green-500">{previewStats.moved}</div>
                <div className="text-xs text-zinc-500">Would Move</div>
              </div>
              <div className="text-center">
                <div className="text-xl font-bold text-yellow-500">{previewStats.skipped}</div>
                <div className="text-xs text-zinc-500">Skipped</div>
              </div>
              <div className="text-center">
                <div className="text-xl font-bold text-red-500">{previewStats.errors}</div>
                <div className="text-xs text-zinc-500">Errors</div>
              </div>
            </div>
            <button
              onClick={() => setShowResults(!showResults)}
              className="p-1 hover:bg-zinc-700 rounded transition-colors"
            >
              {showResults ? (
                <ChevronUp className="w-5 h-5 text-zinc-400" />
              ) : (
                <ChevronDown className="w-5 h-5 text-zinc-400" />
              )}
            </button>
          </div>

          {/* Detailed results */}
          {showResults && previewStats.results.length > 0 && (
            <div className="max-h-64 overflow-y-auto space-y-1">
              {previewStats.results.map((result) => (
                <div
                  key={result.track_id}
                  className="p-2 bg-zinc-900/30 rounded text-xs"
                >
                  <div className="flex items-center gap-2">
                    {getStatusIcon(result.status)}
                    <span className={getStatusColor(result.status)}>
                      {result.message}
                    </span>
                  </div>
                  {result.new_path && result.status === 'moved' && (
                    <div className="mt-1 pl-6 text-zinc-500 truncate">
                      <span className="text-zinc-600">→</span>{' '}
                      <span className="text-zinc-400">{result.new_path}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
