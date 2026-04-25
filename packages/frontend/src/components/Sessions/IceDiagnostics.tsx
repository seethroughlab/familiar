import { useEffect, useRef, useState } from 'react';
import { Loader2, ShieldCheck, ShieldAlert } from 'lucide-react';

interface IceServer {
  urls: string;
  username?: string;
  credential?: string;
}

interface IceDiagnosticsProps {
  iceServers: IceServer[];
}

interface Result {
  ok: boolean;
  message: string;
}

export function IceDiagnostics({ iceServers }: IceDiagnosticsProps) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const mountedRef = useRef(true);
  const activePcRef = useRef<RTCPeerConnection | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      activePcRef.current?.close();
      activePcRef.current = null;
    };
  }, []);

  const run = async () => {
    setRunning(true);
    setResult(null);

    let pc: RTCPeerConnection | null = null;
    try {
      pc = new RTCPeerConnection({ iceServers });
      activePcRef.current = pc;
      pc.createDataChannel('probe');
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      const candidates: RTCIceCandidate[] = [];
      const done = new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, 4000);
        pc!.onicecandidate = (event) => {
          if (event.candidate) candidates.push(event.candidate);
          else {
            clearTimeout(timer);
            resolve();
          }
        };
      });
      await done;

      if (!mountedRef.current) return;

      const types = new Set(candidates.map((c) => c.type ?? '').filter(Boolean));
      if (types.has('relay')) {
        setResult({ ok: true, message: `TURN works (${candidates.length} candidates, relay confirmed)` });
      } else if (types.has('srflx')) {
        setResult({
          ok: false,
          message:
            'STUN works but no TURN relay candidates were gathered. Symmetric-NAT guests may fail to connect.',
        });
      } else if (candidates.length === 0) {
        setResult({ ok: false, message: 'No ICE candidates gathered. Check network connectivity.' });
      } else {
        setResult({ ok: false, message: `Only host-typed candidates (${candidates.length}). TURN/STUN unreachable.` });
      }
    } catch (err) {
      if (mountedRef.current) {
        setResult({ ok: false, message: `Probe failed: ${(err as Error).message}` });
      }
    } finally {
      pc?.close();
      if (activePcRef.current === pc) activePcRef.current = null;
      if (mountedRef.current) setRunning(false);
    }
  };

  return (
    <div className="space-y-2">
      <button
        onClick={run}
        disabled={running}
        className="px-3 py-2 text-sm bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 rounded-md flex items-center gap-2"
      >
        {running && <Loader2 className="w-4 h-4 animate-spin" />}
        Test TURN connectivity
      </button>
      {result && (
        <div
          className={`text-xs flex items-start gap-2 px-3 py-2 rounded-md ${
            result.ok ? 'bg-green-500/10 text-green-400' : 'bg-amber-500/10 text-amber-400'
          }`}
        >
          {result.ok ? (
            <ShieldCheck className="w-4 h-4 mt-0.5 shrink-0" />
          ) : (
            <ShieldAlert className="w-4 h-4 mt-0.5 shrink-0" />
          )}
          <span>{result.message}</span>
        </div>
      )}
    </div>
  );
}
