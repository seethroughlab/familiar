import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Smartphone } from 'lucide-react';
import QRCode from 'qrcode';
import { buildPairingLink, pairingApi, pairingHost } from '../../api';
import { setServerToken } from '../../api/base';
import { queryKeys } from '../../api/queryKeys';

/**
 * Pair a phone or Mac with this server (ADR-0134 point 5).
 *
 * The QR code is a `familiar://pair` link carrying this server's id, name, address and token.
 * Familiar on the phone scans it, asks the listener to confirm, and keeps the token under the
 * server's id. A server with no token has nothing to pair with, so the first thing offered is
 * creating one. Creating it also stores it here, because the gate turns on the moment a token
 * exists, and this page must not lock itself out.
 */
export function PairDevicePanel() {
  const queryClient = useQueryClient();
  const [qr, setQr] = useState<string | null>(null);
  const [showLink, setShowLink] = useState(false);

  const { data: status, isLoading: loadingStatus } = useQuery({
    queryKey: queryKeys.pairing.token,
    queryFn: pairingApi.tokenStatus,
  });

  const { data: info, error: pairingError } = useQuery({
    queryKey: queryKeys.pairing.info,
    queryFn: pairingApi.pairing,
    enabled: status?.configured === true,
    retry: false,
  });

  const create = useMutation({
    mutationFn: pairingApi.issueToken,
    onSuccess: async (token) => {
      await setServerToken(token);
      await queryClient.invalidateQueries({ queryKey: ['pairing'] });
    },
  });

  const target = info ? pairingHost(info, window.location) : null;
  const link = info && target ? buildPairingLink(info, target) : null;

  useEffect(() => {
    if (!link) {
      setQr(null);
      return;
    }
    let cancelled = false;
    QRCode.toDataURL(link, { margin: 1, width: 240, errorCorrectionLevel: 'M' })
      .then((url) => !cancelled && setQr(url))
      .catch(() => !cancelled && setQr(null));
    return () => {
      cancelled = true;
    };
  }, [link]);

  return (
    <div className="bg-zinc-800/50 rounded-lg p-4 mt-4">
      <div className="flex items-center gap-3 mb-4">
        <Smartphone className="w-5 h-5 text-warning" />
        <div>
          <h4 className="font-medium text-white">Pair a Device</h4>
          <p className="text-sm text-zinc-400">
            Scan this with Familiar on your iPhone to connect it to this server.
          </p>
        </div>
      </div>

      {loadingStatus && <Loader2 className="w-4 h-4 animate-spin text-zinc-400" />}

      {status && !status.configured && (
        <div className="space-y-3">
          <p className="text-sm text-zinc-300">
            Pairing gives a device this server&apos;s token, and this server has none yet. Creating
            one also turns on authentication: from then on, a client needs the token to use the API.
            This browser keeps it automatically.
          </p>
          <button
            onClick={() => create.mutate()}
            disabled={create.isPending}
            className="px-4 py-2 bg-warning-strong hover:bg-warning-strong disabled:bg-zinc-700 text-white text-sm rounded-lg transition-colors flex items-center gap-2"
          >
            {create.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
            Create server token
          </button>
          {create.isError && (
            <p className="text-sm text-danger">Could not create a token. Is the server reachable?</p>
          )}
        </div>
      )}

      {status?.configured && pairingError && (
        <p className="text-sm text-danger">
          This browser does not hold the server token, so it cannot show the pairing code. Paste the
          token above first.
        </p>
      )}

      {info && !target && (
        <p className="text-sm text-zinc-300">
          This page is open on the server itself, and the server found no network address a phone
          could reach. Open the admin from another device on the same network, or check that this
          computer is connected to one.
        </p>
      )}

      {info && target && (
        <div className="flex flex-col sm:flex-row gap-4 items-start">
          {qr ? (
            <img
              src={qr}
              alt={`Pairing code for ${info.server_name}`}
              width={240}
              height={240}
              className="rounded-lg bg-white p-2"
            />
          ) : (
            <div className="w-[240px] h-[240px] flex items-center justify-center">
              <Loader2 className="w-5 h-5 animate-spin text-zinc-400" />
            </div>
          )}
          <div className="text-sm text-zinc-300 space-y-2 min-w-0">
            <p>
              <span className="text-zinc-400">Server</span> {info.server_name}
            </p>
            <p>
              <span className="text-zinc-400">Address</span> {target.host}:{target.port}
            </p>
            <p className="text-zinc-400">
              The code contains the server token. Show it only to devices you want to have full
              access.
            </p>
            <button
              onClick={() => setShowLink((v) => !v)}
              className="text-sm text-warning hover:underline"
            >
              {showLink ? 'Hide link' : 'Show link'}
            </button>
            {showLink && link && (
              <code className="block break-all text-xs bg-zinc-900 rounded p-2 select-all">{link}</code>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
