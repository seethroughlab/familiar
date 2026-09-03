# ADR-0105: Familiar's CLAP Runtime Is an External Package

Status: accepted

Date: 2026-09-01

Extends [ADR-0104](ADR-0104-familiar-embeds-whole-tracks-by-chunked-mean.md), which decided *what*
Familiar embeds. This decides *what computes it*.

Relates to [ADR-0102](ADR-0102-the-community-cache-gains-a-recording-key.md), whose shared corpus is
only meaningful if independent installations compute the same function.

Implementation:
- **The GPU made each analysis worker more expensive in host RAM, and the tail of a library is where
  that bites.** Every worker now holds a CUDA context alongside its decode buffer, so three workers
  that were comfortable on the CPU path were not on the GPU one. Measured 2026-09-03: a 57-minute
  DJ mix decodes to **2.01 GB peak RSS**, and three workers on such files exhausted first a 10 GB and
  then a 12 GB container limit — `memory.events` recorded `oom_kill 2` at both. The deployment now
  runs **two** workers at 12 GB.
- **This only appeared at the end of a full re-analysis, and not by chance.** Long files are the slow
  ones, so they accumulate at the back of the queue; the last few hundred tracks of a 26,000-track
  run were almost entirely DJ mixes and extended pieces. A library re-analysis is therefore not a
  uniform workload — its tail is its worst case, and sizing from the average is sizing for the part
  that already finished.
- **`docker update` must never be used on a container with a GPU.** Raising the memory limit that way
  avoids a recreate, which is exactly why it was chosen — and it silently rewrites the cgroup device
  allowlist without the NVIDIA permissions. `/dev/nvidia0` remains present and `DeviceRequests` still
  reads correctly, while every CUDA initialisation fails with *"no CUDA-capable device is
  detected"*: a message that points at hardware when the cause is a container reconfiguration. It
  produced 294 spurious embedding failures before it was spotted. Recreate from compose instead, so
  the limit is recorded there rather than applied live.
- **Verify a provider in a spawned worker, not just the main process.** `get_analysis_capabilities()`
  reported CUDA bound in the API process while every analysis subprocess failed to initialise it.
  The check that matters is the one run where the work happens.
- **The real fix is not a worker count.** A 57-minute file should not need a gigabyte of resident
  audio to produce one 512-float vector. `clapback-embed` decodes whole-file and then windows it;
  decoding a window at a time would make the memory cost independent of track length and stop the
  worker count from depending on what music somebody owns. Recorded as a follow-up against the
  package rather than absorbed with RAM on every host that runs it.
- Accepted and implemented 2026-09-02. `extract_embedding` and `extract_text_embedding` delegate to
  `clapback-embed`; `get_device()`, `load_clap_model()` and the module-level model cache are gone,
  along with `torch` and `transformers` from the `analysis` extra.
- **The GPU path is real, and was the hard part.** Measured on the NAS's GTX 980 (Maxwell, sm_52):
  the full pipeline runs at **2.32s/track against 10.01s on CPU — 4.3x** — and CUDA and CPU vectors
  agree to **6.6e-14**, a thousand times tighter than the 6.0e-08 that `float4` storage costs.
  Unlike fp16, GPU output is corpus-safe, so point 5 does not have to exclude it.
- **Every wrong CUDA stack silently fell back to the CPU and reported success.** Four of them: ORT
  1.29 wants CUDA 13; ORT 1.20 wants CUDA 12 with cuDNN 9; a CUDA 12.6 image is refused by driver
  535, which caps at 12.2; and ORT 1.18.1's default wheel is a CUDA **11** build. Only
  `onnxruntime-gpu==1.18.1` with CUDA 11.8 and `nvidia-cudnn-cu11==8.9.6.50` runs — and the
  unpinned cuDNN wheel now ships 9.x, so that pin is load-bearing. **A check that does not assert
  `get_providers()` contains `CUDAExecutionProvider` proves nothing**, which is why
  `get_analysis_capabilities()` now reports requested and active providers separately.
- **No base-image change was needed.** The CUDA userspace arrives as pip packages onto the existing
  `python:3.11-slim`, with `LD_LIBRARY_PATH` pointing at `site-packages/nvidia/*/lib` — without
  which the provider fails to load and, again, the CPU is used silently.
- **Point 7 became a build stage rather than a download.** An `onnx-export` stage installs torch and
  transformers, runs `export_models.py`, and is not copied from; the final image takes only the
  artifacts. The runtime stays ONNX-only while the artifacts remain reproducible from the pinned
  checkpoint rather than trusted from a URL, and point 7's hosting question never has to be answered.
- **The real prerequisite was not in this repository.** The NAS had an NVIDIA display driver and no
  compute stack: `libcuda.so` was absent entirely, `nvidia-smi` was not installed, and a driver
  upgrade to 535.309.01 had left the 535.261.03 kernel module loaded — which broke
  `nvidia-container-cli` for *every* container on the host, not just Familiar's. A reboot plus
  `nvidia-smi` and `libcuda1` fixed it. Familiar had never used a GPU in production, and the reason
  was three layers below the Dockerfile.

## Context

`ADR-0104` established that an embedding must be reproducible across machines for a shared corpus to
mean anything. That is a property of the *implementation*, not of the format — and Familiar's
implementation is currently a private one.

### The dependency is smaller than it looks, and larger than it costs

`torch` and `transformers` appear in exactly one file. `app/services/analysis.py` holds all of it:
`get_device()` (line 48), `load_clap_model()` (line 72), the audio path (line 189) and the text path
(line 239). Nothing else in the backend imports either package.

What that one file costs, measured 2026-09-01:

| | installed size |
|---|---|
| `torch` | 514 MB |
| `transformers` | 61 MB |
| `tokenizers`, `safetensors`, `huggingface_hub` | 18 MB |
| **packages** | **593 MB** |
| `laion/clap-htsat-unfused` checkpoint cache | 1.1 GB |

`docker/Dockerfile:79` installs `torch` from the CPU-only index specifically to avoid the CUDA build,
and the resulting venv is large enough that a recursive `chown` over it took **9m12s of a 17m30s CI
build** — the incident recorded at `docker/Dockerfile:142`.

### Both halves run without either package

Verified 2026-09-01 against `transformers` + `torch` as the reference:

- **Audio.** A hand-rolled librosa mel feeding the ONNX audio encoder reproduces the full chunked
  mean at cosine 1.0000000000 on four of five tracks, worst 0.9999998808.
- **Text.** `extract_text_embedding` (line 202, called by `llm/handlers/search.py:122` and
  `mood_tags.py:129`) runs on HuggingFace's `tokenizers` package alone — no `transformers` — feeding
  the ONNX text encoder at **cosine 1.0000000000** across three prompts.

The text half was the open question, because a tokenizer is not obviously separable from the library
that ships it. It is: `tokenizer.json` loads into `tokenizers.Tokenizer` directly.

### The precision hierarchy this exposes

Measuring the equivalences produced a scale that the corpus design depends on. All figures are
cosine distance from 1.0, measured 2026-09-01:

| difference | distance from 1.0 |
|---|---|
| `float4` storage round-trip (`pgvector`) | 6.0e-8 |
| mel implementation (librosa vs `transformers`) | 1.2e-7 |
| runtime (`torch` vs ONNX, both fp32) | 1.2e-7 |
| **precision (fp32 vs fp16)** | **1.5e-6** |
| different rip of the same recording, chunked mean | 3e-4 – 3e-3 |
| different rip of the same recording, middle-10s | 5e-3 – 5e-2 |

**fp16 is the first thing on this list that changes the answer.** The community cache's `identical`
bucket begins at 0.999999; fp32-vs-fp16 lands at 0.9999984, outside it. Implementation and runtime
differences sit an order of magnitude tighter and stay inside. So reduced precision is a local
optimisation and not a free one, while a different runtime genuinely is free.

### The dependency is also unpinned

`pyproject.toml:78` declares `transformers>=4.30.0` with no upper bound, and the call at line 239
depends on `get_text_features` returning a tensor. A major release that changes that return type
breaks text embeddings at runtime, in a code path with no test coverage and two callers. Removing the
dependency removes the exposure; pinning it would only defer it.

### What is already present

`basic-pitch[onnx]` (`pyproject.toml:82`) already puts `onnxruntime` in the image, and
`docker/Dockerfile:131` already downloads a runtime `.onnx` model over plain HTTPS
(`silero_vad.onnx`). Both mechanisms this needs exist and are in production.

## Decision

1. **Familiar consumes an external embedder package rather than implementing CLAP itself.** The
   package is `clapback-embed`, published from the commons repository, and Familiar becomes one of
   its consumers rather than the owner of the reference implementation.

2. **`torch` and `transformers` are removed from Familiar.** Both exist only for CLAP, and
   `ADR-0104`'s measurements show the ONNX path reproduces both the audio and text outputs within
   storage precision.

3. **The package owns the front-end, and the front-end is part of the contract.** 48 kHz mono,
   480,000-sample windows, `n_fft` 1024, hop 480, 64 mels, `fmin` 50, `fmax` 14000, slaney-normalised
   filters, Hann periodic, `center=True`, `pad_mode="reflect"`, `power=2.0`, `mel_floor` 1e-10, dB
   with no range clamp. These are not tuning parameters; changing any of them changes every vector.

4. **`truncation="fusion"` is rejected explicitly, not merely unused.** `ClapFeatureExtractor`
   silently selects a *different filter bank* — torchaudio/HTK rather than slaney — when truncation is
   `fusion`. Nothing about the resulting vectors looks wrong, and they are not comparable with
   anything else in the corpus. The package asserts the mode rather than relying on a default.

5. **Anything contributed to a shared corpus is computed at fp32.** Per the hierarchy above, fp16
   moves a vector outside the `identical` bucket. Reduced precision remains available for local-only
   work, and the choice is recorded with the vector rather than assumed.

6. **`EMBEDDING_VERSION` does not bump for this change, and the rule is a threshold rather than a
   judgement.** A pipeline change that moves vectors by less than 1e-6 — the band containing storage
   precision, mel implementation and runtime — does not partition the corpus. Anything above it,
   including any precision change, does. Adopting this package is a 1.2e-7 change.

7. **Model artifacts are downloaded at build time, not vendored.** The audio encoder is 112 MB and
   the text encoder 502 MB, which do not belong in a git repository. This follows the existing
   `silero_vad.onnx` pattern at `docker/Dockerfile:131`.

8. **This is sequenced after `ADR-0104` and does not re-trigger analysis.** The re-analysis
   `ADR-0104` requires is paid once; because the runtime difference is 1.2e-7, adopting the package
   afterwards costs nothing further. The reverse order would work equally well and pay the same once.

## Alternatives Considered

- **Keep `torch` and publish Familiar's implementation as the reference.** No migration, no new
  dependency, and the code already works. Rejected because it makes a music player's internals the
  specification other applications must match, and because it keeps a 593 MB dependency and a 1.1 GB
  checkpoint for four call sites.

- **Extract the embedder into Familiar's own repository as a package.** Cheaper than a cross-repo
  dependency and keeps changes atomic. Rejected because a third-party application cannot reasonably
  depend on a music player's repository, and because the package would drift toward Familiar's
  dependency set — `matplotlib`, `umap-learn`, `basic-pitch` — by proximity.

- **Keep `transformers` for the tokenizer only, and use ONNX for inference.** A plausible middle
  ground, and it was the expected outcome. Rejected because it was measured and proved unnecessary:
  `tokenizers` alone reproduces the text embedding at cosine 1.0, so the 61 MB and the unpinned major
  version buy nothing.

- **Ship fp16 or int8 models to cut the 614 MB of artifacts.** The audio encoder halves to 57 MB and
  the text encoder falls from 502 MB to 120 MB at int8. Rejected as the *default* because fp16
  already exceeds the corpus's identical threshold by an order of magnitude, and int8 was not
  measured at all. Point 5 leaves it available where the vector stays local.

- **Pin `transformers` to a known-good major version instead of removing it.** Addresses the
  unpinned-range risk at almost no cost. Rejected as insufficient rather than wrong: it leaves the
  size, the private implementation, and the reference-implementation problem untouched, and this ADR
  removes the dependency that the pin would protect.

## Consequences

- **Positive** — one implementation of the embedding function, shared between Familiar and every
  other contributor, so a disagreement between two installations is about the audio rather than about
  whose code ran. This is what makes `ADR-0102`'s corpus verifiable rather than merely populated.
- **Positive** — 593 MB of packages and a 1.1 GB checkpoint download leave the image, against 614 MB
  of model artifacts and roughly 15 MB of packages beyond what `basic-pitch[onnx]` already installs.
- **Positive** — removes an unbounded dependency range on a package whose return types Familiar
  depends on, in an untested code path.
- **Positive** — the `fusion` filter-bank trap becomes an assertion. It is currently avoided by
  default values that nothing guards.
- **Tradeoff** — Familiar gains a dependency on a repository it does not solely control, and a
  release of that package can break analysis. The surface is small and the contract is pinned in
  point 3, but the coupling is real and is the price of not being the reference implementation.
- **Positive** — **GPU acceleration becomes cheaper to adopt, not unavailable.** An earlier draft of
  this ADR said CUDA and MPS "go away", which was wrong twice over. ONNX Runtime runs this graph on
  CUDA, DirectML or ROCm, and `onnxruntime-gpu` is roughly 200 MB against the ~5 GB of a CUDA-enabled
  torch build — which is precisely why `docker/Dockerfile:79` installs torch from the CPU-only index
  today. Measured on the NAS on 2026-09-01: `torch 2.13.0+cpu`, `cuda available: False`,
  `mps available: False`, `get_device() -> cpu`. **Familiar has never used a GPU in production**, and
  the 31.6s per track measured under `ADR-0104` is the CPU path. Nothing is lost, and the cheaper
  runtime makes the GTX 980 sitting in that machine a realistic option for the first time.
- **Tradeoff** — an accelerated provider is not known to produce vectors comparable with CPU ones, so
  `clapback-embed` defaults to `CPUExecutionProvider` and takes `CLAPBACK_PROVIDERS` as an opt-in
  override. Treat a non-CPU provider the way point 5 treats fp16 — useful locally, not safe to
  contribute until measured with `scripts/compare_vectors.py`.
- **Tradeoff** — **CoreML does not work at all** for this graph, so Apple silicon gets no
  acceleration by this route. Measured: it supports 735 of 3086 nodes, warns that it "does not
  support shapes with dimension values of 0" across HTSAT's Swin attention slices, and the partition
  it does accept fails at runtime with "Unable to compute the prediction using a neural network
  model". This is recorded so nobody spends an afternoon rediscovering it.
- **Tradeoff** — 614 MB of model artifacts must be fetched at build time from somewhere that stays
  available. `silero_vad.onnx` already carries this risk; this raises the stakes.
- **Follow-up** — whether the text encoder can ship at int8, which would take 502 MB to 120 MB. It
  is never contributed, so point 5 permits it, but the quality effect on `mood_tags` and LLM search
  is unmeasured.
- **Follow-up** — `get_device()`, `load_clap_model()` and `_torch_available` become dead once the
  package lands, along with the `analysis` extra's `transformers` entry and the separate `torch`
  install at `docker/Dockerfile:79`. Removing them is part of this work, not a later cleanup.
