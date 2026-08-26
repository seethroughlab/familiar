import { summarizeAnalysisFrame, type AnalysisFrameSummary } from './analysisMetrics';

const STORAGE_KEY = 'familiar-visualizer-debug';

export interface ProducerAnalysisMetrics extends AnalysisFrameSummary {
  emittedAtMs: number;
  cadenceHz: number;
}

export interface BridgeAnalysisMetrics extends AnalysisFrameSummary {
  receivedAtMs: number;
  eventAgeMs: number | null;
  cadenceHz: number;
}

export interface ConsumerAnalysisMetrics extends AnalysisFrameSummary {
  consumedAtMs: number;
  frameAgeMs: number | null;
  cadenceHz: number;
  source: 'native' | 'web';
}

export interface AudioAnalysisDiagnosticsSnapshot {
  enabled: boolean;
  producer: ProducerAnalysisMetrics | null;
  bridge: BridgeAnalysisMetrics | null;
  consumer: ConsumerAnalysisMetrics | null;
}

function readInitialEnabled(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

let debugEnabled = readInitialEnabled();
let producerMetrics: ProducerAnalysisMetrics | null = null;
let bridgeMetrics: BridgeAnalysisMetrics | null = null;
let consumerMetrics: ConsumerAnalysisMetrics | null = null;
let lastBridgeReceivedAt = 0;
let lastConsumerConsumedAt = 0;

function publishSnapshot(): void {
  if (typeof window === 'undefined') return;
  (window as Window & { __familiarVisualizerDiagnostics?: AudioAnalysisDiagnosticsSnapshot })
    .__familiarVisualizerDiagnostics = getAudioAnalysisDiagnosticsSnapshot();
}

function cadenceHz(nowMs: number, previousMs: number): number {
  if (previousMs <= 0 || nowMs <= previousMs) return 0;
  return 1000 / (nowMs - previousMs);
}

export function setVisualizerDebugEnabled(enabled: boolean): void {
  debugEnabled = enabled;
  if (typeof window !== 'undefined') {
    try {
      window.localStorage.setItem(STORAGE_KEY, enabled ? '1' : '0');
    } catch {
      // Ignore localStorage failures.
    }
  }
  if (!enabled) {
    producerMetrics = null;
    bridgeMetrics = null;
    consumerMetrics = null;
    lastBridgeReceivedAt = 0;
    lastConsumerConsumedAt = 0;
  }
  publishSnapshot();
}

export function isVisualizerDebugEnabled(): boolean {
  return debugEnabled;
}

export function recordProducerAnalysisMetrics(metrics: ProducerAnalysisMetrics): void {
  if (!debugEnabled) return;
  producerMetrics = metrics;
  publishSnapshot();
}

export function recordBridgeAnalysisReceipt(
  frequencyData: ArrayLike<number>,
  timeDomainData: ArrayLike<number>,
): void {
  if (!debugEnabled) return;
  const receivedAtMs = Date.now();
  const summary = summarizeAnalysisFrame(frequencyData, timeDomainData);
  bridgeMetrics = {
    ...summary,
    receivedAtMs,
    eventAgeMs: producerMetrics ? Math.max(0, receivedAtMs - producerMetrics.emittedAtMs) : null,
    cadenceHz: cadenceHz(receivedAtMs, lastBridgeReceivedAt),
  };
  lastBridgeReceivedAt = receivedAtMs;
  publishSnapshot();
}

export function recordConsumedAnalysisFrame(
  source: 'native' | 'web',
  frequencyData: ArrayLike<number>,
  timeDomainData: ArrayLike<number>,
): void {
  if (!debugEnabled) return;
  const consumedAtMs = Date.now();
  const summary = summarizeAnalysisFrame(frequencyData, timeDomainData);
  consumerMetrics = {
    ...summary,
    consumedAtMs,
    frameAgeMs: source === 'native' && producerMetrics
      ? Math.max(0, consumedAtMs - producerMetrics.emittedAtMs)
      : null,
    cadenceHz: cadenceHz(consumedAtMs, lastConsumerConsumedAt),
    source,
  };
  lastConsumerConsumedAt = consumedAtMs;
  publishSnapshot();
}

export function getAudioAnalysisDiagnosticsSnapshot(): AudioAnalysisDiagnosticsSnapshot {
  return {
    enabled: debugEnabled,
    producer: producerMetrics,
    bridge: bridgeMetrics,
    consumer: consumerMetrics,
  };
}
