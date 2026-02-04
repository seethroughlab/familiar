import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { X, Plus, Trash2, Save, Loader2 } from 'lucide-react';
import { smartPlaylistsApi } from '../../api/client';
import type { SmartPlaylistRule, SmartPlaylist } from '../../api/client';

interface Props {
  playlist?: SmartPlaylist;
  onClose: () => void;
  onSaved?: (playlist: SmartPlaylist) => void;
}

const OPERATOR_LABELS: Record<string, string> = {
  equals: 'equals',
  not_equals: 'does not equal',
  contains: 'contains',
  not_contains: 'does not contain',
  starts_with: 'starts with',
  ends_with: 'ends with',
  greater_than: '>',
  less_than: '<',
  greater_or_equal: '>=',
  less_or_equal: '<=',
  between: 'between',
  is_empty: 'is empty',
  is_not_empty: 'is not empty',
  within_days: 'within last',
  not_within_days: 'not within last',
};

export function SmartPlaylistBuilder({ playlist, onClose, onSaved }: Props) {
  const queryClient = useQueryClient();
  const isEditing = !!playlist;

  const [name, setName] = useState(playlist?.name || '');
  const [description, setDescription] = useState(playlist?.description || '');
  const [rules, setRules] = useState<SmartPlaylistRule[]>(playlist?.rules || []);
  const [matchMode, setMatchMode] = useState<'all' | 'any'>(playlist?.match_mode || 'all');
  const [orderBy, setOrderBy] = useState(playlist?.order_by || 'title');
  const [orderDirection, setOrderDirection] = useState<'asc' | 'desc'>(playlist?.order_direction || 'asc');
  const [maxTracks, setMaxTracks] = useState<number | ''>(playlist?.max_tracks || '');

  const { data: fields } = useQuery({
    queryKey: ['smart-playlist-fields'],
    queryFn: smartPlaylistsApi.getAvailableFields,
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      const data = {
        name,
        description: description || undefined,
        rules,
        match_mode: matchMode,
        order_by: orderBy,
        order_direction: orderDirection,
        max_tracks: maxTracks || undefined,
      };

      if (isEditing) {
        return smartPlaylistsApi.update(playlist.id, data);
      } else {
        return smartPlaylistsApi.create(data);
      }
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ['smart-playlists'] });
      onSaved?.(saved);
      onClose();
    },
  });

  const addRule = () => {
    setRules([...rules, { field: 'genre', operator: 'contains', value: '' }]);
  };

  const updateRule = (index: number, updates: Partial<SmartPlaylistRule>) => {
    const newRules = [...rules];
    newRules[index] = { ...newRules[index], ...updates };
    setRules(newRules);
  };

  const removeRule = (index: number) => {
    setRules(rules.filter((_, i) => i !== index));
  };

  const getFieldType = (fieldName: string): string => {
    const trackField = fields?.track_fields.find(f => f.name === fieldName);
    if (trackField) return trackField.type;

    const analysisField = fields?.analysis_fields.find(f => f.name === fieldName);
    if (analysisField) return analysisField.type;

    const playHistoryField = fields?.play_history_fields?.find(f => f.name === fieldName);
    if (playHistoryField) return playHistoryField.type;

    return 'string';
  };

  const getOperatorsForField = (fieldName: string): string[] => {
    const type = getFieldType(fieldName);
    return fields?.operators[type as keyof typeof fields.operators] || [];
  };

  const handleFieldChange = (index: number, newField: string) => {
    const newOperators = getOperatorsForField(newField);
    const currentRule = rules[index];
    // Reset operator to first valid one if current operator isn't valid for new field
    const newOperator = newOperators.includes(currentRule.operator)
      ? currentRule.operator
      : newOperators[0] || 'equals';
    updateRule(index, { field: newField, operator: newOperator, value: '' });
  };

  const allFields = [
    ...(fields?.track_fields || []),
    ...(fields?.analysis_fields || []),
    ...(fields?.play_history_fields || []),
  ];

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-zinc-900 rounded-xl border border-zinc-800 w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-zinc-800 flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            {isEditing ? 'Edit Smart Playlist' : 'Create Smart Playlist'}
          </h2>
          <button onClick={onClose} className="p-1 hover:bg-zinc-800 rounded-md">
            <X className="w-5 h-5 text-zinc-400" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          {/* Name & Description */}
          <div className="space-y-3">
            <div>
              <label className="block text-sm text-zinc-400 mb-1">Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="My Smart Playlist"
                className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-md placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-green-500"
              />
            </div>
            <div>
              <label className="block text-sm text-zinc-400 mb-1">Description (optional)</label>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="A playlist for..."
                className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-md placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-green-500"
              />
            </div>
          </div>

          {/* Rules */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <label className="text-sm text-zinc-400">Rules</label>
              <div className="flex items-center gap-2 text-sm">
                <span className="text-zinc-500">Match</span>
                <select
                  value={matchMode}
                  onChange={(e) => setMatchMode(e.target.value as 'all' | 'any')}
                  className="px-2 py-1 bg-zinc-800 border border-zinc-700 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
                >
                  <option value="all">all rules</option>
                  <option value="any">any rule</option>
                </select>
              </div>
            </div>

            <div className="space-y-2">
              {rules.map((rule, index) => (
                <RuleRow
                  key={index}
                  rule={rule}
                  fields={allFields}
                  operators={getOperatorsForField(rule.field)}
                  fieldType={getFieldType(rule.field)}
                  onFieldChange={(field) => handleFieldChange(index, field)}
                  onChange={(updates) => updateRule(index, updates)}
                  onRemove={() => removeRule(index)}
                />
              ))}

              <button
                onClick={addRule}
                className="flex items-center gap-2 px-3 py-2 text-sm text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-md transition-colors"
              >
                <Plus className="w-4 h-4" />
                Add Rule
              </button>
            </div>
          </div>

          {/* Ordering */}
          <div className="flex gap-4">
            <div className="flex-1">
              <label className="block text-sm text-zinc-400 mb-1">Order by</label>
              <select
                value={orderBy}
                onChange={(e) => setOrderBy(e.target.value)}
                className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500"
              >
                {allFields.map((f) => (
                  <option key={f.name} value={f.name}>
                    {f.description}
                  </option>
                ))}
              </select>
            </div>
            <div className="w-32">
              <label className="block text-sm text-zinc-400 mb-1">Direction</label>
              <select
                value={orderDirection}
                onChange={(e) => setOrderDirection(e.target.value as 'asc' | 'desc')}
                className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500"
              >
                <option value="asc">Ascending</option>
                <option value="desc">Descending</option>
              </select>
            </div>
          </div>

          {/* Max tracks */}
          <div>
            <label className="block text-sm text-zinc-400 mb-1">Max tracks (optional)</label>
            <input
              type="number"
              value={maxTracks}
              onChange={(e) => setMaxTracks(e.target.value ? parseInt(e.target.value) : '')}
              placeholder="No limit"
              min={1}
              max={10000}
              className="w-32 px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-md placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-green-500"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-zinc-800 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-md transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => saveMutation.mutate()}
            disabled={!name || saveMutation.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-md font-medium transition-colors"
          >
            {saveMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            {isEditing ? 'Save' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}

interface RuleRowProps {
  rule: SmartPlaylistRule;
  fields: Array<{ name: string; description: string }>;
  operators: string[];
  fieldType: string;
  onFieldChange: (field: string) => void;
  onChange: (updates: Partial<SmartPlaylistRule>) => void;
  onRemove: () => void;
}

function RuleRow({ rule, fields, operators, fieldType, onFieldChange, onChange, onRemove }: RuleRowProps) {
  const needsValue = !['is_empty', 'is_not_empty'].includes(rule.operator);
  const isBetween = rule.operator === 'between';
  const isBoolean = fieldType === 'boolean';
  const isDateWithDays = ['within_days', 'not_within_days'].includes(rule.operator);

  return (
    <div className="flex items-center gap-2 p-2 bg-zinc-800/50 rounded-md">
      {/* Field selector */}
      <select
        value={rule.field}
        onChange={(e) => onFieldChange(e.target.value)}
        className="flex-1 px-2 py-1.5 bg-zinc-700 border border-zinc-600 rounded text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
      >
        {fields.map((f) => (
          <option key={f.name} value={f.name}>
            {f.description}
          </option>
        ))}
      </select>

      {/* Operator selector */}
      <select
        value={rule.operator}
        onChange={(e) => onChange({ operator: e.target.value })}
        className="w-36 px-2 py-1.5 bg-zinc-700 border border-zinc-600 rounded text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
      >
        {operators.map((op) => (
          <option key={op} value={op}>
            {OPERATOR_LABELS[op] || op}
          </option>
        ))}
      </select>

      {/* Boolean value dropdown */}
      {needsValue && isBoolean && (
        <select
          value={rule.value === true ? 'true' : 'false'}
          onChange={(e) => onChange({ value: e.target.value === 'true' })}
          className="w-24 px-2 py-1.5 bg-zinc-700 border border-zinc-600 rounded text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
        >
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      )}

      {/* Value input */}
      {needsValue && !isBetween && !isBoolean && (
        <input
          type={fieldType === 'number' || isDateWithDays ? 'number' : 'text'}
          value={rule.value as string || ''}
          onChange={(e) => onChange({
            value: fieldType === 'number' || isDateWithDays ? parseFloat(e.target.value) || '' : e.target.value
          })}
          placeholder="value"
          step={fieldType === 'number' ? 0.1 : 1}
          min={isDateWithDays ? 1 : undefined}
          className="flex-1 px-2 py-1.5 bg-zinc-700 border border-zinc-600 rounded text-sm placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-green-500"
        />
      )}

      {/* Between inputs */}
      {isBetween && (
        <>
          <input
            type="number"
            value={(rule.value as [number, number])?.[0] ?? ''}
            onChange={(e) => {
              const current = (rule.value as [number, number]) || [0, 0];
              onChange({ value: [parseFloat(e.target.value) || 0, current[1]] });
            }}
            placeholder="min"
            step={0.1}
            className="w-20 px-2 py-1.5 bg-zinc-700 border border-zinc-600 rounded text-sm placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-green-500"
          />
          <span className="text-zinc-500 text-sm">to</span>
          <input
            type="number"
            value={(rule.value as [number, number])?.[1] ?? ''}
            onChange={(e) => {
              const current = (rule.value as [number, number]) || [0, 0];
              onChange({ value: [current[0], parseFloat(e.target.value) || 0] });
            }}
            placeholder="max"
            step={0.1}
            className="w-20 px-2 py-1.5 bg-zinc-700 border border-zinc-600 rounded text-sm placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-green-500"
          />
        </>
      )}

      {/* Days suffix for within_days and not_within_days */}
      {isDateWithDays && (
        <span className="text-zinc-500 text-sm">days</span>
      )}

      {/* Remove button */}
      <button
        onClick={onRemove}
        className="p-1 hover:bg-zinc-700 rounded transition-colors"
      >
        <Trash2 className="w-4 h-4 text-zinc-500 hover:text-red-400" />
      </button>
    </div>
  );
}
