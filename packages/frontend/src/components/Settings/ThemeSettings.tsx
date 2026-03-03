import { Sun, Moon, Monitor } from 'lucide-react';
import { useThemeStore } from '../../stores/themeStore';

type Theme = 'dark' | 'light' | 'system';

const themes: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
];

export function ThemeSettings() {
  const { theme, setTheme } = useThemeStore();

  return (
    <div className="bg-zinc-800/50 dark:bg-zinc-800/50 light:bg-white rounded-lg p-4">
      <div className="flex items-center justify-between">
        <div>
          <h4 className="font-medium text-white dark:text-white light:text-zinc-900">Appearance</h4>
          <p className="text-sm text-zinc-400 dark:text-zinc-400 light:text-zinc-600">
            Choose your preferred theme
          </p>
        </div>
      </div>

      <div className="mt-4 flex gap-2">
        {themes.map(({ value, label, icon: Icon }) => (
          <button
            key={value}
            onClick={() => setTheme(value)}
            className={`flex-1 flex flex-col items-center gap-2 p-3 rounded-lg border transition-colors ${
              theme === value
                ? 'border-purple-500 bg-purple-500/10 text-purple-400'
                : 'border-zinc-700 dark:border-zinc-700 light:border-zinc-300 hover:border-zinc-500 text-zinc-400 dark:text-zinc-400 light:text-zinc-600'
            }`}
          >
            <Icon className="w-5 h-5" />
            <span className="text-sm">{label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
