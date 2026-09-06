"""Community cache for sharing CLAP embeddings and audio features.

Allows Familiar users to share pre-computed CLAP embeddings and audio
features, keyed by AcoustID fingerprint hash. This dramatically speeds
up analysis for tracks that other users have already processed.

Privacy:
- Fingerprints are hashed (SHA256) before transmission - one-way, anonymous
- Only embeddings/features are shared, no track metadata or file information
- Contribution is opt-in

Versioning:
- Embeddings are versioned by EMBEDDING_VERSION and CLAP model version
- Features are versioned by FEATURES_VERSION
- Prevents mixing data from incompatible analysis pipelines

Neither of those two actually establishes that two vectors are comparable, which is
what clapback's `ADR-0006` is about: EMBEDDING_VERSION is this application's own
counter, and CLAP_MODEL_VERSION is the checkpoint, which a change to windowing or
pooling moves every vector without touching. `clapback_embed.PIPELINE_VERSION` is
composed from all five things that can move a vector, and contributions now carry it
when the caller knows it — see `contribute`.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Rate limit handling
MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 5.0  # seconds

# CLAP model identifier for versioning
CLAP_MODEL_VERSION = "laion/clap-htsat-unfused:v1"
EMBEDDING_DIM = 512

# Default community cache server
DEFAULT_CACHE_URL = "https://familiar-cache.fly.dev"


@dataclass
class CachedEmbedding:
    """A CLAP embedding retrieved from the community cache."""

    fingerprint_hash: str  # SHA256 hash of AcoustID fingerprint
    embedding: list[float]  # 512-dimensional CLAP embedding
    analysis_version: int
    clap_model_version: str
    contributor_count: int = 1  # How many users have contributed this embedding


@dataclass
class CachedFeatures:
    """Audio features retrieved from the community cache."""

    fingerprint_hash: str  # SHA256 hash of AcoustID fingerprint
    analysis_version: int
    features: dict[str, Any] = field(default_factory=dict)  # All features as a flat dict
    contributor_count: int = 1


@dataclass
class CachedAnalysisDetail:
    """Full structured analysis data retrieved from the community cache."""

    fingerprint_hash: str
    analysis_version: int
    detail: dict
    contributor_count: int = 1


class CommunityCacheService:
    """Client for the community CLAP embedding and features cache.

    Usage:
        cache = CommunityCacheService()

        # Check cache before computing locally (embeddings)
        cached = await cache.lookup_embedding(acoustid_fingerprint, EMBEDDING_VERSION)
        if cached:
            embedding = cached.embedding
        else:
            embedding = compute_clap_embedding(audio_file)
            await cache.contribute_embedding(acoustid_fingerprint, embedding, EMBEDDING_VERSION)

        # Check cache for features
        cached_feat = await cache.lookup_features(acoustid_fingerprint, FEATURES_VERSION)
        if cached_feat:
            features = cached_feat
        else:
            features = extract_features(audio_file)
            await cache.contribute_features(acoustid_fingerprint, features, FEATURES_VERSION)
    """

    def __init__(
        self,
        cache_url: str = DEFAULT_CACHE_URL,
        timeout: float = 10.0,
        embedding_version: int | None = None,
        features_version: int | None = None,
        client_id: str | None = None,
    ):
        self.cache_url = cache_url.rstrip("/")
        self.client_id = client_id or None
        self._client: httpx.AsyncClient | None = None
        self._timeout = timeout
        # Lazy-import defaults from config only when not explicitly provided
        if embedding_version is None or features_version is None:
            from app.config import EMBEDDING_VERSION, FEATURES_VERSION
            self._embedding_version = embedding_version if embedding_version is not None else EMBEDDING_VERSION
            self._features_version = features_version if features_version is not None else FEATURES_VERSION
        else:
            self._embedding_version = embedding_version
            self._features_version = features_version

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": "Familiar/0.1.0"},
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response | None:
        """Make an HTTP request with automatic retry on rate limiting.

        Respects Retry-After header from 429 responses.

        Returns:
            Response object, or None if all retries exhausted
        """
        client = await self._get_client()

        for attempt in range(MAX_RETRIES):
            try:
                response = await client.request(method, url, **kwargs)

                # Success or expected error (like 404)
                if response.status_code != 429:
                    return response

                # Rate limited - check Retry-After header
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = DEFAULT_RETRY_DELAY
                else:
                    delay = DEFAULT_RETRY_DELAY

                logger.warning(
                    f"Rate limited by community cache, waiting {delay}s "
                    f"(attempt {attempt + 1}/{MAX_RETRIES})"
                )
                await asyncio.sleep(delay)

            except httpx.ConnectError:
                logger.debug("Community cache server unavailable")
                return None
            except httpx.TimeoutException:
                logger.debug("Community cache request timed out")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(1.0)  # Brief delay before retry
                continue
            except Exception as e:
                logger.warning(f"Community cache request failed: {e}")
                return None

        logger.warning("Community cache: max retries exceeded due to rate limiting")
        return None

    @staticmethod
    def hash_fingerprint(acoustid_fingerprint: str | bytes) -> str:
        """Hash an AcoustID fingerprint for privacy.

        Uses SHA256 to create a one-way hash. The original fingerprint
        cannot be recovered, preserving user privacy while still
        allowing cache lookups.
        """
        if isinstance(acoustid_fingerprint, bytes):
            return hashlib.sha256(acoustid_fingerprint).hexdigest()
        return hashlib.sha256(acoustid_fingerprint.encode()).hexdigest()

    async def lookup(
        self,
        acoustid_fingerprint: str | bytes,
        analysis_version: int | None = None,
    ) -> CachedEmbedding | None:
        """Look up an embedding from the community cache.

        Args:
            acoustid_fingerprint: The raw AcoustID fingerprint string
            analysis_version: Version to match (defaults to current EMBEDDING_VERSION)

        Returns:
            CachedEmbedding if found, None otherwise
        """
        if analysis_version is None:
            analysis_version = self._embedding_version

        fp_hash = self.hash_fingerprint(acoustid_fingerprint)

        response = await self._request_with_retry(
            "GET",
            f"{self.cache_url}/v1/embeddings/{fp_hash}",
            params={
                "analysis_version": analysis_version,
                "clap_model_version": CLAP_MODEL_VERSION,
            },
        )

        if response is None:
            return None

        if response.status_code == 404:
            logger.debug(f"Community cache miss for {fp_hash[:16]}...")
            return None

        if response.status_code != 200:
            logger.warning(f"Community cache lookup error: HTTP {response.status_code}")
            return None

        try:
            data = response.json()

            # Validate embedding dimension
            embedding = data.get("embedding", [])
            if len(embedding) != EMBEDDING_DIM:
                logger.warning(
                    f"Invalid embedding dimension from cache: {len(embedding)} != {EMBEDDING_DIM}"
                )
                return None

            logger.info(
                f"Community cache hit for {fp_hash[:16]}... "
                f"(contributed by {data.get('contributor_count', 1)} users)"
            )

            return CachedEmbedding(
                fingerprint_hash=fp_hash,
                embedding=embedding,
                analysis_version=data.get("analysis_version", analysis_version),
                clap_model_version=data.get("clap_model_version", CLAP_MODEL_VERSION),
                contributor_count=data.get("contributor_count", 1),
            )
        except Exception as e:
            logger.warning(f"Community cache lookup failed to parse response: {e}")
            return None

    async def contribute(
        self,
        acoustid_fingerprint: str | bytes,
        embedding: list[float],
        analysis_version: int | None = None,
        pipeline_version: str | None = None,
    ) -> bool:
        """Contribute an embedding to the community cache.

        Args:
            acoustid_fingerprint: The raw AcoustID fingerprint string
            embedding: 512-dimensional CLAP embedding
            analysis_version: Version of the analysis (defaults to current)
            pipeline_version: The identity of the pipeline that computed this
                vector — `clapback_embed.PIPELINE_VERSION`. **Explicit, and never
                defaulted from the installed library**, because this method is
                handed a vector and does not know what produced it. Filling it in
                from whatever `clapback-embed` happens to be installed now would
                declare today's pipeline for a vector computed months ago by a
                different one, which is precisely the false assertion clapback's
                `ADR-0006` exists to prevent. A caller that did not just compute
                the vector passes nothing, and the corpus records "unknown".

        Returns:
            True if contribution was accepted, False otherwise
        """
        if analysis_version is None:
            analysis_version = self._embedding_version

        if len(embedding) != EMBEDDING_DIM:
            logger.warning(f"Cannot contribute embedding with wrong dimension: {len(embedding)}")
            return False

        fp_hash = self.hash_fingerprint(acoustid_fingerprint)

        # **Contribute the vector as computed.** This used to round to float16 to halve the
        # request body, which cost 2.1e-08 of cosine distance — inside the corpus's `identical`
        # band (1e-06), so nothing was broken, but roughly a hundred million times the 3.3e-16
        # that float4 storage costs, and recorded nowhere. clapback's `ADR-0002` point 3 makes
        # stored precision part of the corpus contract; there is no reason for the contributed
        # precision to be quietly worse than what the corpus can hold. A few kilobytes per track,
        # once per track, is not a trade worth making against that.
        payload = {
            "fingerprint_hash": fp_hash,
            "embedding": [float(x) for x in embedding],
            "analysis_version": analysis_version,
            "clap_model_version": CLAP_MODEL_VERSION,
        }
        # Optional on the wire: the server accepts contributions without one, and older
        # deployments predate the field entirely. Sending it is what lets this installation's
        # submissions count toward independent agreement (`ADR-0004` point 3).
        if self.client_id:
            payload["client_id"] = self.client_id
        # Phase 2 of clapback's `ADR-0006` point 6. The corpus keys on
        # `analysis_version` and `clap_model_version` today, and neither says whether
        # two vectors are comparable: the first is this application's own counter, and
        # the second is the checkpoint, which windowing or pooling can move every vector
        # without changing. `pipeline_version` is the one field that does.
        #
        # Omitted rather than sent as null when unknown, and optional on the wire for
        # the same reason `client_id` is: a corpus that predates the field must keep
        # accepting these. It becomes required when clapback reaches phase 4, and
        # nothing here breaks before then.
        if pipeline_version:
            payload["pipeline_version"] = pipeline_version

        response = await self._request_with_retry(
            "POST",
            f"{self.cache_url}/v1/embeddings",
            json=payload,
        )

        if response is None:
            return False

        if response.status_code == 201:
            logger.info(f"Contributed embedding to community cache: {fp_hash[:16]}...")
            return True
        elif response.status_code == 200:
            # Already exists, incremented contributor count
            logger.debug(f"Embedding already in cache, confirmed: {fp_hash[:16]}...")
            return True
        else:
            logger.warning(f"Community cache contribution rejected: {response.status_code}")
            return False

    async def lookup_features(
        self,
        acoustid_fingerprint: str | bytes,
        analysis_version: int | None = None,
    ) -> CachedFeatures | None:
        """Look up audio features from the community cache.

        Args:
            acoustid_fingerprint: The raw AcoustID fingerprint string
            analysis_version: Version to match (defaults to current FEATURES_VERSION)

        Returns:
            CachedFeatures if found, None otherwise
        """
        if analysis_version is None:
            analysis_version = self._features_version

        fp_hash = self.hash_fingerprint(acoustid_fingerprint)

        response = await self._request_with_retry(
            "GET",
            f"{self.cache_url}/v1/features/{fp_hash}",
            params={"analysis_version": analysis_version},
        )

        if response is None:
            return None

        if response.status_code == 404:
            logger.debug(f"Community cache features miss for {fp_hash[:16]}...")
            return None

        if response.status_code != 200:
            logger.warning(f"Community cache features lookup error: HTTP {response.status_code}")
            return None

        try:
            data = response.json()

            logger.info(
                f"Community cache features hit for {fp_hash[:16]}... "
                f"(contributed by {data.get('contributor_count', 1)} users)"
            )

            return CachedFeatures(
                fingerprint_hash=fp_hash,
                analysis_version=data.get("analysis_version", analysis_version),
                features=data.get("features", {}),
                contributor_count=data.get("contributor_count", 1),
            )
        except Exception as e:
            logger.warning(f"Community cache features lookup failed to parse response: {e}")
            return None

    async def contribute_features(
        self,
        acoustid_fingerprint: str | bytes,
        features: dict[str, float | str | int | None],
        analysis_version: int | None = None,
    ) -> bool:
        """Contribute audio features to the community cache.

        Args:
            acoustid_fingerprint: The raw AcoustID fingerprint string
            features: Dict of feature key-value pairs (server accepts anything)
            analysis_version: Version of the analysis (defaults to current)

        Returns:
            True if contribution was accepted, False otherwise
        """
        if analysis_version is None:
            analysis_version = self._features_version

        fp_hash = self.hash_fingerprint(acoustid_fingerprint)

        # Strip None values and send everything — server is schema-agnostic
        features_payload = {k: v for k, v in features.items() if v is not None}

        response = await self._request_with_retry(
            "POST",
            f"{self.cache_url}/v1/features",
            json={
                "fingerprint_hash": fp_hash,
                "analysis_version": analysis_version,
                "features": features_payload,
            },
        )

        if response is None:
            return False

        if response.status_code == 201:
            logger.info(f"Contributed features to community cache: {fp_hash[:16]}...")
            return True
        elif response.status_code == 200:
            logger.debug(f"Features already in cache, confirmed: {fp_hash[:16]}...")
            return True
        else:
            logger.warning(f"Community cache features contribution rejected: {response.status_code}")
            return False

    async def lookup_analysis_detail(
        self,
        acoustid_fingerprint: str | bytes,
        analysis_version: int | None = None,
    ) -> CachedAnalysisDetail | None:
        """Look up full analysis detail from the community cache.

        Args:
            acoustid_fingerprint: The raw AcoustID fingerprint string
            analysis_version: Version to match (defaults to current FEATURES_VERSION)

        Returns:
            CachedAnalysisDetail if found, None otherwise
        """
        if analysis_version is None:
            analysis_version = self._features_version

        fp_hash = self.hash_fingerprint(acoustid_fingerprint)

        response = await self._request_with_retry(
            "GET",
            f"{self.cache_url}/v1/analysis-detail/{fp_hash}",
            params={"analysis_version": analysis_version},
        )

        if response is None:
            return None

        if response.status_code == 404:
            logger.debug(f"Community cache analysis detail miss for {fp_hash[:16]}...")
            return None

        if response.status_code != 200:
            logger.warning(
                f"Community cache analysis detail lookup error: HTTP {response.status_code}"
            )
            return None

        try:
            data = response.json()
            detail = data.get("detail")
            if not detail or not isinstance(detail, dict):
                logger.warning("Community cache returned invalid analysis detail")
                return None

            logger.info(
                f"Community cache analysis detail hit for {fp_hash[:16]}... "
                f"(contributed by {data.get('contributor_count', 1)} users)"
            )

            return CachedAnalysisDetail(
                fingerprint_hash=fp_hash,
                analysis_version=data.get("analysis_version", analysis_version),
                detail=detail,
                contributor_count=data.get("contributor_count", 1),
            )
        except Exception as e:
            logger.warning(
                f"Community cache analysis detail lookup failed to parse response: {e}"
            )
            return None

    async def contribute_analysis_detail(
        self,
        acoustid_fingerprint: str | bytes,
        detail: dict,
        analysis_version: int | None = None,
    ) -> bool:
        """Contribute full analysis detail to the community cache.

        Args:
            acoustid_fingerprint: The raw AcoustID fingerprint string
            detail: Full structured analysis data dict
            analysis_version: Version of the analysis (defaults to current)

        Returns:
            True if contribution was accepted, False otherwise
        """
        if analysis_version is None:
            analysis_version = self._features_version

        if not detail:
            return False

        fp_hash = self.hash_fingerprint(acoustid_fingerprint)

        response = await self._request_with_retry(
            "POST",
            f"{self.cache_url}/v1/analysis-detail",
            json={
                "fingerprint_hash": fp_hash,
                "analysis_version": analysis_version,
                "detail": detail,
            },
        )

        if response is None:
            return False

        if response.status_code == 201:
            logger.info(
                f"Contributed analysis detail to community cache: {fp_hash[:16]}..."
            )
            return True
        elif response.status_code == 200:
            logger.debug(
                f"Analysis detail already in cache, confirmed: {fp_hash[:16]}..."
            )
            return True
        else:
            logger.warning(
                f"Community cache analysis detail contribution rejected: "
                f"{response.status_code}"
            )
            return False

    async def health_check(self) -> dict:
        """Check if the community cache server is available.

        Returns:
            Dict with 'available' bool and optional 'stats' dict
        """
        try:
            client = await self._get_client()
            response = await client.get(f"{self.cache_url}/health", timeout=5.0)

            if response.status_code == 200:
                data = response.json()
                return {
                    "available": True,
                    "stats": data.get("stats", {}),
                }

            return {"available": False, "error": f"HTTP {response.status_code}"}

        except Exception as e:
            return {"available": False, "error": str(e)}


# Singleton instance
_community_cache_service: CommunityCacheService | None = None


def get_community_cache_service(
    cache_url: str | None = None, client_id: str | None = None
) -> CommunityCacheService:
    """Get or create the community cache service singleton.

    Args:
        cache_url: Optional custom cache URL. If provided and different
            from current, creates a new instance.
        client_id: This installation's opaque identifier (`ADR-0004`). A change here
            rebuilds the instance for the same reason a URL change does — the singleton
            would otherwise keep contributing under a stale identity.
    """
    global _community_cache_service

    if _community_cache_service is None:
        _community_cache_service = CommunityCacheService(
            cache_url=cache_url or DEFAULT_CACHE_URL, client_id=client_id
        )
    elif (cache_url and cache_url != _community_cache_service.cache_url) or (
        client_id and client_id != _community_cache_service.client_id
    ):
        _community_cache_service = CommunityCacheService(
            cache_url=cache_url or _community_cache_service.cache_url,
            client_id=client_id or _community_cache_service.client_id,
        )

    return _community_cache_service
