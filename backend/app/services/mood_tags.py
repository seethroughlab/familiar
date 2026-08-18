"""CLAP-based mood, genre, instrumentation, and energy tags.

Computes tags by comparing a track's CLAP audio embedding against
pre-computed text embeddings for ~48 descriptors. Uses cosine similarity
to find the best-matching descriptors.
"""

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── Descriptor definitions ─────────────────────────────────────────────────────
# Each descriptor has a tag (short), category, and a natural language description
# for CLAP text embedding.

DESCRIPTORS: list[dict[str, str]] = [
    # Mood (16)
    {"tag": "happy", "category": "mood", "description": "happy uplifting joyful music"},
    {"tag": "sad", "category": "mood", "description": "sad melancholic sorrowful music"},
    {"tag": "angry", "category": "mood", "description": "angry aggressive intense music"},
    {"tag": "calm", "category": "mood", "description": "calm peaceful relaxing music"},
    {"tag": "dark", "category": "mood", "description": "dark brooding ominous music"},
    {"tag": "bright", "category": "mood", "description": "bright cheerful upbeat music"},
    {"tag": "dreamy", "category": "mood", "description": "dreamy ethereal atmospheric music"},
    {"tag": "energetic", "category": "mood", "description": "energetic powerful driving music"},
    {"tag": "romantic", "category": "mood", "description": "romantic tender love music"},
    {"tag": "mysterious", "category": "mood", "description": "mysterious eerie suspenseful music"},
    {"tag": "nostalgic", "category": "mood", "description": "nostalgic wistful bittersweet music"},
    {"tag": "triumphant", "category": "mood", "description": "triumphant victorious epic music"},
    {"tag": "playful", "category": "mood", "description": "playful fun lighthearted music"},
    {"tag": "anxious", "category": "mood", "description": "anxious tense nervous music"},
    {"tag": "serene", "category": "mood", "description": "serene tranquil meditative music"},
    {"tag": "rebellious", "category": "mood", "description": "rebellious defiant punk music"},
    # Genre (16)
    {"tag": "jazz", "category": "genre", "description": "jazz music with improvisation and swing"},
    {"tag": "electronic", "category": "genre", "description": "electronic synthesizer dance music"},
    {"tag": "rock", "category": "genre", "description": "rock music with electric guitars and drums"},
    {"tag": "classical", "category": "genre", "description": "classical orchestral chamber music"},
    {"tag": "hip-hop", "category": "genre", "description": "hip-hop rap beats music"},
    {"tag": "folk", "category": "genre", "description": "folk acoustic traditional music"},
    {"tag": "metal", "category": "genre", "description": "heavy metal distorted aggressive music"},
    {"tag": "ambient", "category": "genre", "description": "ambient drone atmospheric soundscape music"},
    {"tag": "blues", "category": "genre", "description": "blues music with soul and emotion"},
    {"tag": "funk", "category": "genre", "description": "funk groovy bass-driven rhythmic music"},
    {"tag": "reggae", "category": "genre", "description": "reggae ska dub rhythmic music"},
    {"tag": "soul", "category": "genre", "description": "soul rhythm and blues vocal music"},
    {"tag": "country", "category": "genre", "description": "country western americana music"},
    {"tag": "punk", "category": "genre", "description": "punk fast raw aggressive music"},
    {"tag": "world", "category": "genre", "description": "world music global ethnic traditional"},
    {"tag": "pop", "category": "genre", "description": "pop catchy melodic mainstream music"},
    # Instrumentation (8)
    {"tag": "piano", "category": "instrumentation", "description": "piano keyboard music"},
    {"tag": "acoustic guitar", "category": "instrumentation", "description": "acoustic guitar fingerpicking strumming music"},
    {"tag": "bass-heavy", "category": "instrumentation", "description": "heavy bass deep low frequency music"},
    {"tag": "strings", "category": "instrumentation", "description": "strings violin cello orchestral music"},
    {"tag": "brass/sax", "category": "instrumentation", "description": "brass saxophone trumpet horn music"},
    {"tag": "synthesizer", "category": "instrumentation", "description": "synthesizer electronic pad sound music"},
    {"tag": "drums", "category": "instrumentation", "description": "drums percussion rhythmic beat music"},
    {"tag": "vocal/choir", "category": "instrumentation", "description": "vocal choir singing harmony music"},
    # Energy (8)
    {"tag": "slow", "category": "energy", "description": "slow tempo ballad music"},
    {"tag": "mid-tempo", "category": "energy", "description": "mid-tempo moderate pace music"},
    {"tag": "fast", "category": "energy", "description": "fast tempo upbeat quick music"},
    {"tag": "building", "category": "energy", "description": "building crescendo rising intensity music"},
    {"tag": "sparse", "category": "energy", "description": "sparse minimal quiet music"},
    {"tag": "dense", "category": "energy", "description": "dense layered full wall of sound music"},
    {"tag": "danceable", "category": "energy", "description": "danceable groovy rhythmic music"},
    {"tag": "freeform", "category": "energy", "description": "freeform improvised experimental music"},
]

# The vocabulary as a membership test. Added for ADR-0064, where a visualizer declares the tags it
# suits and the server has to decide whether it recognises one — several of these are not
# identifiers (`acoustic guitar`, `brass/sax`, `hip-hop`, `mid-tempo`, `bass-heavy`, `vocal/choir`),
# so anything matching against them has to use these strings verbatim rather than a normalised form.
KNOWN_TAGS: frozenset[str] = frozenset(d["tag"] for d in DESCRIPTORS)

# Cache for descriptor text embeddings (computed once, kept in memory)
_descriptor_embeddings: np.ndarray | None = None
_descriptor_embeddings_failed = False


def _get_descriptor_embeddings() -> np.ndarray | None:
    """Get or compute descriptor text embeddings.

    Returns (N, 512) array of CLAP text embeddings for all descriptors,
    or None if CLAP is not available.
    """
    global _descriptor_embeddings, _descriptor_embeddings_failed

    if _descriptor_embeddings is not None:
        return _descriptor_embeddings

    if _descriptor_embeddings_failed:
        return None

    # Try Redis cache first
    try:
        import json

        from app.services.tasks.common import get_redis

        redis = get_redis()
        if redis:
            cached = redis.get("mood_tags:descriptor_embeddings")
            if cached:
                data = json.loads(cached)
                _descriptor_embeddings = np.array(data, dtype=np.float32)
                logger.info("Loaded descriptor embeddings from Redis cache")
                return _descriptor_embeddings
    except Exception as e:
        logger.debug(f"Redis cache miss for descriptor embeddings: {e}")

    # Compute text embeddings via CLAP
    try:
        from app.services.analysis import extract_text_embedding

        embeddings = []
        for desc in DESCRIPTORS:
            emb = extract_text_embedding(desc["description"])
            if emb is None:
                logger.warning("CLAP not available for descriptor embeddings")
                _descriptor_embeddings_failed = True
                return None
            embeddings.append(emb)

        _descriptor_embeddings = np.array(embeddings, dtype=np.float32)

        # Cache in Redis (24h TTL)
        try:
            redis = get_redis()
            if redis:
                import json
                redis.setex(
                    "mood_tags:descriptor_embeddings",
                    86400,  # 24h
                    json.dumps(_descriptor_embeddings.tolist()),
                )
                logger.info("Cached descriptor embeddings in Redis")
        except Exception as e:
            logger.debug(f"Failed to cache descriptor embeddings in Redis: {e}")

        logger.info(f"Computed {len(embeddings)} descriptor text embeddings")
        return _descriptor_embeddings

    except Exception as e:
        logger.warning(f"Failed to compute descriptor embeddings: {e}")
        _descriptor_embeddings_failed = True
        return None


def compute_mood_tags(
    audio_embedding: list[float],
    top_k: int = 5,
    min_confidence: float = 0.15,
) -> list[dict[str, Any]]:
    """Compute mood/genre/instrumentation tags for a track.

    Args:
        audio_embedding: 512-dim CLAP audio embedding
        top_k: Maximum number of tags to return
        min_confidence: Minimum cosine similarity threshold

    Returns:
        List of {"tag", "category", "confidence"} dicts, sorted by confidence descending.
    """
    desc_embeddings = _get_descriptor_embeddings()
    if desc_embeddings is None:
        return []

    # Normalize audio embedding
    audio_vec = np.array(audio_embedding, dtype=np.float32)
    audio_norm = np.linalg.norm(audio_vec)
    if audio_norm < 1e-8:
        return []
    audio_vec = audio_vec / audio_norm

    # Normalize descriptor embeddings (should already be ~unit norm, but ensure)
    desc_norms = np.linalg.norm(desc_embeddings, axis=1, keepdims=True)
    desc_normalized = desc_embeddings / (desc_norms + 1e-8)

    # Cosine similarity: dot product of normalized vectors
    similarities = desc_normalized @ audio_vec

    # Get top-K above threshold
    results: list[dict[str, Any]] = []
    for idx in np.argsort(similarities)[::-1]:
        sim = float(similarities[idx])
        if sim < min_confidence:
            break
        if len(results) >= top_k:
            break
        results.append({
            "tag": DESCRIPTORS[idx]["tag"],
            "category": DESCRIPTORS[idx]["category"],
            "confidence": round(sim, 3),
        })

    return results


def get_all_tags() -> list[dict[str, str]]:
    """Get all available descriptor tags with their categories.

    Returns list of {"tag", "category"} dicts.
    """
    return [{"tag": d["tag"], "category": d["category"]} for d in DESCRIPTORS]
