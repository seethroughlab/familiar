#!/usr/bin/env python3
"""Smoke test for PyTorch and CLAP embeddings.

Standalone script (no pytest, no app imports) designed to run inside the
Docker container to verify that the scientific stack works on the current
architecture (amd64 or arm64).

Usage:
    python scripts/smoke_test_clap.py                  # Full test (downloads ~1.5GB CLAP model)
    python scripts/smoke_test_clap.py --skip-model      # Quick torch-import-only check
"""

import argparse
import json
import math
import platform
import sys
import time


def check_torch():
    """Verify torch imports and detect device."""
    import torch

    device = "cpu"
    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available():
        device = "mps"

    # Basic tensor operation
    t = torch.randn(3, 3, device=device)
    assert t.shape == (3, 3), f"Unexpected tensor shape: {t.shape}"
    assert torch.isfinite(t).all(), "Tensor contains non-finite values"

    return {
        "torch_version": torch.__version__,
        "device": device,
    }


def check_clap():
    """Load CLAP model and produce audio + text embeddings."""
    import numpy as np
    import torch
    from transformers import ClapModel, ClapProcessor

    model_name = "laion/clap-htsat-unfused"
    print(f"Loading CLAP model: {model_name} ...", flush=True)
    t0 = time.time()

    processor = ClapProcessor.from_pretrained(model_name)
    model = ClapModel.from_pretrained(model_name)
    model.eval()

    load_time = time.time() - t0
    print(f"Model loaded in {load_time:.1f}s", flush=True)

    # Generate synthetic audio: 3-second 440Hz sine wave at 48kHz
    sr = 48000
    duration = 3.0
    t_arr = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
    audio = 0.5 * np.sin(2 * np.pi * 440 * t_arr)

    # Audio embedding
    inputs = processor(audio=audio, sampling_rate=sr, return_tensors="pt")
    with torch.no_grad():
        audio_embed = model.get_audio_features(**inputs)
    audio_embedding = audio_embed.cpu().numpy().flatten().tolist()

    assert len(audio_embedding) == 512, f"Expected 512-dim, got {len(audio_embedding)}"
    assert all(math.isfinite(v) for v in audio_embedding), "Audio embedding has non-finite values"

    # Text embedding
    text = "electronic ambient music"
    text_inputs = processor(text=[text], return_tensors="pt", padding=True)
    with torch.no_grad():
        text_embed = model.get_text_features(**text_inputs)
    text_embedding = text_embed.cpu().numpy().flatten().tolist()

    assert len(text_embedding) == 512, f"Expected 512-dim, got {len(text_embedding)}"
    assert all(math.isfinite(v) for v in text_embedding), "Text embedding has non-finite values"

    # Cosine similarity sanity check
    dot = sum(a * b for a, b in zip(audio_embedding, text_embedding))
    norm_a = math.sqrt(sum(a * a for a in audio_embedding))
    norm_b = math.sqrt(sum(b * b for b in text_embedding))
    cosine_sim = dot / (norm_a * norm_b) if norm_a > 0 and norm_b > 0 else 0.0

    return {
        "model": model_name,
        "load_time_s": round(load_time, 1),
        "audio_embedding_dim": len(audio_embedding),
        "text_embedding_dim": len(text_embedding),
        "cosine_similarity": round(cosine_sim, 4),
    }


def main():
    parser = argparse.ArgumentParser(description="Smoke test PyTorch and CLAP embeddings")
    parser.add_argument(
        "--skip-model",
        action="store_true",
        help="Only test torch import and device detection (no 1.5GB model download)",
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

        # Step 1: torch
        print("\n--- Checking PyTorch ---", flush=True)
        torch_info = check_torch()
        result.update(torch_info)
        print(f"torch {torch_info['torch_version']}, device: {torch_info['device']}", flush=True)

        if args.skip_model:
            result["status"] = "pass"
            result["note"] = "torch-only (--skip-model)"
            print("\n--- Skipping CLAP model (--skip-model) ---", flush=True)
        else:
            # Step 2: CLAP
            print("\n--- Checking CLAP ---", flush=True)
            clap_info = check_clap()
            result.update(clap_info)
            print(f"Audio embedding: {clap_info['audio_embedding_dim']}-dim", flush=True)
            print(f"Text embedding: {clap_info['text_embedding_dim']}-dim", flush=True)
            print(f"Cosine similarity: {clap_info['cosine_similarity']}", flush=True)
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
