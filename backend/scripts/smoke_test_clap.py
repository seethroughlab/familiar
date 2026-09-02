#!/usr/bin/env python3
"""Smoke test for the CLAP embedder, inside the shipped image.

Standalone (no pytest, no app imports) so it can run against a pulled image on
either architecture and prove the scientific stack actually works there.

**This used to test PyTorch.** ADR-0105 removed torch and transformers entirely;
CLAP now runs through `clapback-embed` on ONNX Runtime. The old version asserted
`import torch` and so failed the first release after that change — a check whose
subject no longer existed, passing for years and then failing for the right
reason at the wrong time.

What it verifies now is stronger than the import it replaced:

- the embedder imports and the ONNX encoders are present in the image
- **which execution providers actually bound**, not which were requested — ONNX
  Runtime falls back to CPU silently when CUDA fails to load, so a GPU image with
  a broken CUDA stack is indistinguishable from a working one without this
- a real audio embedding comes out 512-dimensional, finite and unit length
- a real text embedding does too, from the same 512-d space

Usage:
    python scripts/smoke_test_clap.py               # full: runs real embeddings
    python scripts/smoke_test_clap.py --skip-model  # imports and artifacts only
"""

import argparse
import json
import math
import platform
import sys
import time


def check_embedder() -> dict:
    """Import the embedder and report what it will actually run on."""
    import clapback_embed
    import onnxruntime as ort
    from clapback_embed.artifacts import model_dir, providers

    return {
        "pipeline_version": clapback_embed.PIPELINE_VERSION,
        "onnxruntime": ort.__version__,
        "model_dir": str(model_dir()),
        # Requested. Not the same thing as bound — see check_providers.
        "providers_requested": providers(),
        "providers_available": ort.get_available_providers(),
    }


def check_providers() -> dict:
    """Load the audio encoder and report the providers actually bound to it.

    The distinction matters more than it looks. Requesting
    `CUDAExecutionProvider` and getting it are different facts: when the CUDA
    libraries are missing or mismatched, ONNX Runtime logs a warning, falls back
    to CPU, and returns correct vectors — so nothing downstream fails, and the
    GPU quietly does nothing forever.
    """
    from clapback_embed.artifacts import audio_session

    t0 = time.time()
    session = audio_session()
    return {
        "providers_active": list(session.get_providers()),
        "session_load_s": round(time.time() - t0, 2),
    }


def check_embeddings() -> dict:
    """Produce a real audio and text embedding from synthetic input."""
    import numpy as np
    from clapback_embed import embed_audio, embed_text
    from clapback_embed.mel import SAMPLE_RATE

    # 25 seconds, so the whole-track path runs two windows and drops a tail —
    # a single-window clip would not exercise the pooling at all.
    duration = 25.0
    t_arr = np.arange(int(SAMPLE_RATE * duration), dtype=np.float64) / SAMPLE_RATE
    audio = (0.5 * np.sin(2 * np.pi * 440 * t_arr)).astype(np.float32)

    t0 = time.time()
    audio_embedding = embed_audio(audio)
    audio_s = time.time() - t0

    assert len(audio_embedding) == 512, f"Expected 512-dim, got {len(audio_embedding)}"
    assert all(math.isfinite(v) for v in audio_embedding), "Audio embedding is not finite"
    norm_a = math.sqrt(sum(v * v for v in audio_embedding))
    assert abs(norm_a - 1.0) < 1e-5, f"Audio embedding is not unit length: {norm_a}"

    text = "electronic ambient music"
    t0 = time.time()
    text_embedding = embed_text(text)
    text_s = time.time() - t0

    assert len(text_embedding) == 512, f"Expected 512-dim, got {len(text_embedding)}"
    assert all(math.isfinite(v) for v in text_embedding), "Text embedding is not finite"

    # Audio and text share one space, so a similarity is defined. Not asserted
    # against a threshold: a 440 Hz sine is not "ambient music", and pinning a
    # number here would be asserting something about the model rather than the
    # image.
    dot = sum(a * b for a, b in zip(audio_embedding, text_embedding))
    norm_b = math.sqrt(sum(v * v for v in text_embedding))
    cosine_sim = dot / (norm_a * norm_b) if norm_a > 0 and norm_b > 0 else 0.0

    return {
        "audio_embedding_dim": len(audio_embedding),
        "text_embedding_dim": len(text_embedding),
        "audio_embed_s": round(audio_s, 2),
        "text_embed_s": round(text_s, 2),
        "cosine_similarity": round(cosine_sim, 4),
    }


def main():
    parser = argparse.ArgumentParser(description="Smoke test the CLAP embedder")
    parser.add_argument(
        "--skip-model",
        action="store_true",
        help="Only check imports, artifacts and providers (no inference)",
    )
    args = parser.parse_args()

    result = {
        "arch": platform.machine(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "status": "fail",
    }

    try:
        print(f"Architecture: {platform.machine()}", flush=True)
        print(f"Python: {platform.python_version()}", flush=True)

        print("\n--- Checking embedder ---", flush=True)
        info = check_embedder()
        result.update(info)
        print(f"pipeline: {info['pipeline_version']}", flush=True)
        print(f"onnxruntime {info['onnxruntime']}", flush=True)
        print(f"requested: {info['providers_requested']}", flush=True)

        print("\n--- Loading encoder ---", flush=True)
        prov = check_providers()
        result.update(prov)
        print(f"active:    {prov['providers_active']}  ({prov['session_load_s']}s)", flush=True)
        if "CUDAExecutionProvider" in info["providers_requested"]:
            if "CUDAExecutionProvider" in prov["providers_active"]:
                print("CUDA requested and bound", flush=True)
            else:
                # Not a failure: images are built with CUDA for hosts that have a
                # GPU and run unchanged on hosts that do not. Saying so out loud
                # is the point — this is the state that otherwise hides.
                print("CUDA requested but NOT bound — running on CPU", flush=True)

        if args.skip_model:
            result["status"] = "pass"
            result["note"] = "imports, artifacts and providers only (--skip-model)"
            print("\n--- Skipping inference (--skip-model) ---", flush=True)
        else:
            print("\n--- Embedding ---", flush=True)
            emb = check_embeddings()
            result.update(emb)
            print(f"audio: {emb['audio_embedding_dim']}-dim in {emb['audio_embed_s']}s", flush=True)
            print(f"text:  {emb['text_embedding_dim']}-dim in {emb['text_embed_s']}s", flush=True)
            print(f"cosine similarity: {emb['cosine_similarity']}", flush=True)
            result["status"] = "pass"

        print(f"\n{json.dumps(result, indent=2)}")
        sys.exit(0)

    except Exception as e:
        result["error"] = str(e)
        print(f"\nFAILED: {e}", file=sys.stderr, flush=True)
        print(f"\n{json.dumps(result, indent=2)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
