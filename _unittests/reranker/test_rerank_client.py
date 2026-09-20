"""Unit tests for src.reranker_client.RerankerClient.

Pure unit tests — httpx is mocked at the network boundary.
No DB, no app runtime required. Run from repo root:

    HONCHO_CONFIG_TOML_DISABLED=1 .venv/bin/python -m pytest _unittests/reranker -q
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.reranker_client import RerankerClient, get_reranker_client


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Force RerankerSettings defaults so tests are deterministic and
    independent of any local config.toml."""
    monkeypatch.setenv("HONCHO_CONFIG_TOML_DISABLED", "1")
    yield


class TestRerankEmpty:
    """Empty documents must short-circuit without any HTTP call."""

    async def test_empty_documents_returns_empty_list(self):
        client = RerankerClient()
        assert await client.rerank("query", []) == []


class TestRerankSuccess:
    async def test_returns_scores_when_reranker_ok(self, monkeypatch):
        client = RerankerClient()
        fake = AsyncMock()
        fake.post.return_value.raise_for_status = MagicMock()
        fake.post.return_value.json = MagicMock(
            return_value={"scores": [0.9, 0.1]}
        )
        client.client = fake

        scores = await client.rerank("query", ["doc1", "doc2"])

        assert scores == [0.9, 0.1]

    async def test_posts_to_configured_endpoint(self, monkeypatch):
        client = RerankerClient()
        # Use a fixed endpoint so we can assert the URL.
        client.base_url = "http://example:8300/v1/rerank"
        fake = AsyncMock()
        fake.post.return_value.raise_for_status = MagicMock()
        fake.post.return_value.json = MagicMock(return_value={"scores": [0.5]})
        client.client = fake

        await client.rerank("q", ["d"])

        args, kwargs = fake.post.call_args
        assert args[0] == "http://example:8300/v1/rerank"
        assert kwargs["json"] == {"query": "q", "documents": ["d"]}


class TestRerankTopK:
    async def test_top_k_limits_documents_and_returns_matching_scores(self, monkeypatch):
        client = RerankerClient()
        fake = AsyncMock()
        fake.post.return_value.raise_for_status = MagicMock()
        fake.post.return_value.json = MagicMock(return_value={"scores": [0.8]})
        client.client = fake

        scores = await client.rerank("q", ["d1", "d2", "d3"], top_k=1)

        # Only the first doc should be sent.
        args, kwargs = fake.post.call_args
        assert kwargs["json"]["documents"] == ["d1"]
        assert scores == [0.8]


class TestRerankErrors:
    async def test_http_error_returns_zero_scores(self, monkeypatch):
        client = RerankerClient()
        fake = AsyncMock()
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=None, response=None
        )
        fake.post.return_value = resp
        client.client = fake

        scores = await client.rerank("q", ["d1", "d2"])

        assert scores == [0.0, 0.0]

    async def test_request_error_returns_zero_scores(self, monkeypatch):
        client = RerankerClient()
        fake = AsyncMock()
        fake.post.side_effect = httpx.RequestError("connection refused")
        client.client = fake

        scores = await client.rerank("q", ["d1"])

        assert scores == [0.0]

    async def test_score_count_mismatch_is_padded(self, monkeypatch):
        """If the reranker returns fewer scores than docs, pad with zeros —
        defensive against a malformed response."""
        client = RerankerClient()
        fake = AsyncMock()
        fake.post.return_value.raise_for_status = MagicMock()
        fake.post.return_value.json = MagicMock(return_value={"scores": [0.5]})
        client.client = fake

        scores = await client.rerank("q", ["d1", "d2"], top_k=2)

        assert scores == [0.5, 0.0]


class TestRerankerClientSingleton:
    async def test_get_reranker_client_returns_same_instance(self):
        a = await get_reranker_client()
        b = await get_reranker_client()
        assert a is b