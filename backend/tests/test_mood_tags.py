"""The descriptor vectors are committed, not recomputed.

`compute_mood_tags` used to embed 48 fixed strings through CLAP and cache the result in Redis under
a 24-hour TTL that is only written while analysis runs. Measured on the real library with analysis
complete and nothing pending, the key was simply **absent** — so the cache this file was built
around essentially never existed in a settled library, and every caller silently paid a ~1.5 GB
model load or took a fallback.

They are a pure function of `DESCRIPTORS` and the text encoder, so they are computed once by
`scripts/build_mood_descriptors.py` and committed.
"""

import numpy as np

from app.services.mood_tags import (
    DESCRIPTORS,
    compute_mood_tags,
    descriptor_embeddings_if_warm,
)


class TestCommittedDescriptors:
    def test_they_load_without_redis_or_clap(self):
        matrix = descriptor_embeddings_if_warm()
        assert matrix is not None, "committed descriptors should load with no cache and no model"
        assert matrix.shape == (len(DESCRIPTORS), 512)
        assert np.isfinite(matrix).all()

    def test_redis_being_absent_does_not_matter(self, monkeypatch):
        """The old path returned nothing whenever Redis lacked a 24-hour key; this one must not."""
        monkeypatch.setattr("app.services.tasks.common.get_redis", lambda: None, raising=False)
        from app.services import mood_tags

        monkeypatch.setattr(mood_tags, "_committed_embeddings", None)
        monkeypatch.setattr(mood_tags, "_committed_failed", False)
        assert mood_tags.descriptor_embeddings_if_warm() is not None

    def test_row_order_matches_the_descriptor_list(self):
        """Order is the contract, not just the row count.

        `compute_mood_tags` maps a winning row index back onto `DESCRIPTORS`, so a file whose rows
        have drifted returns confident, wrong words — the failure mode that looks like working
        software. Regenerate with `scripts/build_mood_descriptors.py`.
        """
        matrix = descriptor_embeddings_if_warm()
        assert matrix is not None
        for index in (0, len(DESCRIPTORS) // 2, len(DESCRIPTORS) - 1):
            tags = compute_mood_tags(
                matrix[index].tolist(), top_k=1, min_confidence=0.0, desc_embeddings=matrix
            )
            assert tags and tags[0]["tag"] == DESCRIPTORS[index]["tag"]

    def test_a_supplied_matrix_is_used_instead_of_loading_one(self, monkeypatch):
        """The `desc_embeddings` argument exists so a caller can guarantee no model load.

        If `compute_mood_tags` ignored it and fell through to `_get_descriptor_embeddings`, the
        guarantee would be silently void — so this asserts the fallback is not reached.
        """
        from app.services import mood_tags

        def _explode():
            raise AssertionError("should not fall through to the CLAP path")

        monkeypatch.setattr(mood_tags, "_get_descriptor_embeddings", _explode)
        supplied = np.zeros((len(DESCRIPTORS), 512), dtype=np.float32)
        supplied[3, 0] = 1.0

        tags = compute_mood_tags([1.0] + [0.0] * 511, top_k=1, min_confidence=0.0, desc_embeddings=supplied)
        assert tags and tags[0]["tag"] == DESCRIPTORS[3]["tag"]
