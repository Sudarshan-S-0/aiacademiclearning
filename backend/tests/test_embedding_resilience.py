import sys
from types import ModuleType

import pytest

from app.services import qdrant


def test_embedding_failure_does_not_return_fake_semantic_vectors(monkeypatch):
    class BrokenSentenceTransformer:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr(qdrant, "_model", None)
    fake_module = ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = BrokenSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    with pytest.raises(RuntimeError, match="model unavailable"):
        qdrant.embed("A sentence that needs a semantic embedding")

def test_ensure_collection_rejects_qdrant_server_errors(monkeypatch):
    class Response:
        status_code = 503

        def raise_for_status(self):
            raise RuntimeError("Qdrant unavailable")

    monkeypatch.setattr(qdrant.httpx, "get", lambda *a, **k: Response())
    assert qdrant.ensure_collection() is False


def test_search_chunks_reads_new_qdrant_query_response_shape(monkeypatch):
    class Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self.payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("HTTP error")

        def json(self):
            return self.payload

    responses = iter([
        Response(404, {}),
        Response(200, {
            "result": {
                "points": [
                    {"id": 1, "payload": {"subject_id": 7, "text": "approved excerpt"}}
                ]
            }
        }),
    ])
    monkeypatch.setattr(qdrant, "ensure_collection", lambda: True)
    monkeypatch.setattr(qdrant, "embed", lambda text: [0.0] * 384)
    monkeypatch.setattr(qdrant.httpx, "post", lambda *a, **k: next(responses))

    result = qdrant.search_chunks(7, "approved excerpt")

    assert result == [{"subject_id": 7, "text": "approved excerpt"}]
