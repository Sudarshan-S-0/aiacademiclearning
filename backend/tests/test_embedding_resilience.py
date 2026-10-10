import sys
from types import SimpleNamespace

import pytest

from app.services import qdrant


def test_embedding_failure_does_not_return_fake_semantic_vectors(monkeypatch):
    class BrokenSentenceTransformer:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr(qdrant, "_model", None)
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=BrokenSentenceTransformer),
    )

    with pytest.raises(RuntimeError, match="model unavailable"):
        qdrant.embed("A sentence that needs a semantic embedding")
