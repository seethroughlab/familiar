const APP_STORE_URL = 'https://apps.apple.com/app/id6759879772';

interface Props {
  onContinue: () => void;
}

export function MobileAppRedirect({ onContinue }: Props) {
  return (
    <div className="min-h-screen bg-zinc-950 flex flex-col items-center justify-center p-8 gap-8">
      <div className="flex flex-col items-center gap-4 text-center">
        <img src="/icons/icon-192.png" alt="Familiar" className="w-20 h-20 rounded-2xl" />
        <div className="space-y-1">
          <h1 className="text-2xl font-bold text-white">Familiar</h1>
          <p className="text-zinc-400">Your music, your way</p>
        </div>
      </div>
      <div className="w-full max-w-xs flex flex-col gap-4">
        <a
          href={APP_STORE_URL}
          className="w-full bg-blue-600 hover:bg-blue-500 text-white font-semibold py-3 px-6 rounded-xl text-center transition-colors"
        >
          Open in App Store
        </a>
        <button
          onClick={onContinue}
          className="text-zinc-500 hover:text-zinc-300 text-sm transition-colors"
        >
          Continue in browser
        </button>
      </div>
    </div>
  );
}
