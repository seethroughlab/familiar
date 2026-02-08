import React, { createContext, useContext, useRef, useEffect, useState, type ReactNode } from 'react';
import { createLogger } from '../utils/logger';
import { EffectsChain, initEffectsChain } from '../services/audioEffects';
// Imports removed

const log = createLogger('AudioContext');

// Platform detection
const isMobilePlatform = /iPad|iPhone|iPod|Android/i.test(navigator.userAgent);
const useDirectPlayback = isMobilePlatform;
const useWebAudio = !isMobilePlatform;

interface AudioGraph {
  // Web Audio Context
  audioContext: AudioContext | null;
  analyser: AnalyserNode | null;
  masterGain: GainNode | null;
  effectsChain: EffectsChain | null;

  // Web Audio Elements & Nodes
  webAudioElementA: HTMLAudioElement | null;
  webAudioElementB: HTMLAudioElement | null;
  mediaSourceA: MediaElementAudioSourceNode | null;
  mediaSourceB: MediaElementAudioSourceNode | null;
  gainA: GainNode | null;
  gainB: GainNode | null;
  normGainA: GainNode | null;
  normGainB: GainNode | null;

  // Direct Playback Elements (Mobile)
  directElementA: HTMLAudioElement | null;
  directElementB: HTMLAudioElement | null;
}

interface AudioEngineContextType {
  isInitialized: boolean;
  audioGraph: React.MutableRefObject<AudioGraph>;
  initializeAudioGraph: () => boolean;
  platform: {
    isMobile: boolean;
    useWebAudio: boolean;
    useDirectPlayback: boolean;
  };
}

const AudioEngineContext = createContext<AudioEngineContextType | null>(null);

export function useAudioEngineContext() {
  const context = useContext(AudioEngineContext);
  if (!context) {
    throw new Error('useAudioEngineContext must be used within an AudioEngineProvider');
  }
  return context;
}

interface AudioEngineProviderProps {
  children: ReactNode;
}

export function AudioEngineProvider({ children }: AudioEngineProviderProps) {
  const [isInitialized, setIsInitialized] = useState(false);
  const audioGraph = useRef<AudioGraph>({
    audioContext: null,
    analyser: null,
    masterGain: null,
    effectsChain: null,
    webAudioElementA: null,
    webAudioElementB: null,
    mediaSourceA: null,
    mediaSourceB: null,
    gainA: null,
    gainB: null,
    normGainA: null,
    normGainB: null,
    directElementA: null,
    directElementB: null,
  });

  const createAudioElement = () => {
    const el = new Audio();
    el.preload = 'auto';
    el.crossOrigin = 'anonymous';
    el.style.display = 'none';
    document.body.appendChild(el);
    return el;
  };

  const initializeAudioGraph = () => {
    if (isInitialized) return true;

    try {
      const graph = audioGraph.current;

      if (useDirectPlayback) {
        // Mobile initialization
        if (!graph.directElementA) graph.directElementA = createAudioElement();
        if (!graph.directElementB) graph.directElementB = createAudioElement();
        log.info('Initialized in direct playback mode (mobile)');
      } else {
        // Desktop initialization
        if (!graph.audioContext) graph.audioContext = new AudioContext();
        const ctx = graph.audioContext;

        if (!graph.analyser) {
          graph.analyser = ctx.createAnalyser();
          graph.analyser.fftSize = 256;
          graph.analyser.smoothingTimeConstant = 0.8;
        }

        if (!graph.webAudioElementA) {
          graph.webAudioElementA = createAudioElement();
          graph.mediaSourceA = ctx.createMediaElementSource(graph.webAudioElementA);
        }
        if (!graph.webAudioElementB) {
          graph.webAudioElementB = createAudioElement();
          graph.mediaSourceB = ctx.createMediaElementSource(graph.webAudioElementB);
        }

        if (!graph.normGainA) {
          graph.normGainA = ctx.createGain();
          graph.normGainA.gain.value = 1;
        }
        if (!graph.normGainB) {
          graph.normGainB = ctx.createGain();
          graph.normGainB.gain.value = 1;
        }

        if (!graph.gainA) {
          graph.gainA = ctx.createGain();
          graph.gainA.gain.value = 1;
        }
        if (!graph.gainB) {
          graph.gainB = ctx.createGain();
          graph.gainB.gain.value = 0;
        }

        if (!graph.masterGain) {
          graph.masterGain = ctx.createGain();
        }

        if (!graph.effectsChain) {
          graph.effectsChain = initEffectsChain(ctx);
        }

        // Connect graph
        // Source -> NormGain -> CrossfadeGain -> MasterGain -> Effects -> Analyser -> Destination
        graph.mediaSourceA!.connect(graph.normGainA!);
        graph.mediaSourceB!.connect(graph.normGainB!);

        graph.normGainA!.connect(graph.gainA!);
        graph.normGainB!.connect(graph.gainB!);

        graph.gainA!.connect(graph.masterGain!);
        graph.gainB!.connect(graph.masterGain!);

        if (graph.effectsChain) {
          graph.masterGain!.connect(graph.effectsChain.input);
          graph.effectsChain.output.connect(graph.analyser!);
        } else {
          graph.masterGain!.connect(graph.analyser!);
        }

        graph.analyser!.connect(ctx.destination);
        log.info('Initialized in Web Audio mode (desktop)');
      }

      setIsInitialized(true);
      return true;
    } catch (e) {
      log.error('Failed to initialize audio graph:', e);
      return false;
    }
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      const graph = audioGraph.current;
      if (graph.audioContext) {
        graph.audioContext.close().catch(console.error);
      }

      // Remove elements from DOM
      [graph.webAudioElementA, graph.webAudioElementB, graph.directElementA, graph.directElementB].forEach(el => {
        if (el && el.parentNode) {
          el.parentNode.removeChild(el);
        }
      });
    };
  }, []);

  return (
    <AudioEngineContext.Provider
      value={{
        isInitialized,
        audioGraph,
        initializeAudioGraph,
        platform: {
          isMobile: isMobilePlatform,
          useWebAudio,
          useDirectPlayback
        }
      }}
    >
      {children}
    </AudioEngineContext.Provider>
  );
}
