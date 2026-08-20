"""Integration tests for search reranking pipeline.

Tests the reranker integration into the search() function.
Mocks httpx at the network boundary and the RRF fusion output.
Run from repo root:

    HONCHO_CONFIG_TOML_DISABLED=1 .venv/bin/python -m pytest _unittests/reranker/test_search_rerank.py -q
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List

from src.utils.search import search, reciprocal_rank_fusion
from src.models import Message


class TestSearchRerankIntegration:
    """Tests for cross-encoder reranking integration in search pipeline."""

    @pytest.fixture
    def mock_messages(self) -> List[Message]:
        """Create mock Message objects for testing."""
        msgs = []
        for i in range(10):
            msg = MagicMock(spec=Message)
            msg.id = f"msg-{i}"
            msg.content = f"This is test message number {i} about topic alpha beta gamma"
            msg.workspace_name = "test-workspace"
            msg.session_name = "test-session"
            msg.peer_name = "test-peer"
            msg.created_at = None
            msgs.append(msg)
        return msgs

    @pytest.mark.asyncio
    async def test_search_rerank_enabled_returns_reranked_results(self, mock_messages):
        """When RERANKER.ENABLED=true, search should rerank RRF results."""
        # This test will fail until search.py is modified to call reranker
        with patch('src.utils.search.get_reranker_client') as mock_get_client:
            mock_client = AsyncMock()
            # Return scores that reorder the results (higher score = more relevant)
            # Original order: msg-0, msg-1, msg-2, msg-3, msg-4...
            # Rerank scores: msg-4 highest, then msg-1, then msg-0...
            mock_client.rerank.return_value = [0.1, 0.9, 0.2, 0.3, 0.95, 0.4, 0.5, 0.6, 0.7, 0.8]
            mock_get_client.return_value = mock_client

            with patch('src.utils.search.settings') as mock_settings:
                mock_settings.RERANKER.ENABLED = True
                mock_settings.RERANKER.TOP_K = 5
                mock_settings.RERANKER.TIMEOUT_SECONDS = 30.0

                # Mock the internal search functions to return our test messages
                with patch('src.utils.search._run_search') as mock_run_search:
                    mock_run_search.return_value = mock_messages[:5]

                    results = await search(
                        query="test query",
                        filters={"workspace_name": "test-workspace"},
                        limit=5
                    )

                    # Verify reranker was called
                    mock_client.rerank.assert_called_once()
                    call_args = mock_client.rerank.call_args
                    assert call_args[1]['query'] == "test query"
                    assert len(call_args[1]['documents']) == 5

                    # Verify results are reordered by rerank scores (descending)
                    # Expected order by score: msg-4 (0.95), msg-1 (0.9), msg-9 (0.8), msg-8 (0.7), msg-7 (0.6)
                    assert results[0].id == "msg-4"
                    assert results[1].id == "msg-1"
                    assert results[2].id == "msg-9"
                    assert results[3].id == "msg-8"
                    assert results[4].id == "msg-7"

    @pytest.mark.asyncio
    async def test_search_rerank_disabled_returns_rrf_order(self, mock_messages):
        """When RERANKER.ENABLED=false, search should return RRF order unchanged."""
        with patch('src.utils.search.get_reranker_client') as mock_get_client:
            with patch('src.utils.search.settings') as mock_settings:
                mock_settings.RERANKER.ENABLED = False

                with patch('src.utils.search._run_search') as mock_run_search:
                    mock_run_search.return_value = mock_messages[:5]

                    results = await search(
                        query="test query",
                        filters={"workspace_name": "test-workspace"},
                        limit=5
                    )

                    # Reranker should NOT be called
                    mock_get_client.assert_not_called()

                    # Results should be in original RRF order
                    assert [r.id for r in results] == ["msg-0", "msg-1", "msg-2", "msg-3", "msg-4"]

    @pytest.mark.asyncio
    async def test_search_rerank_graceful_fallback_on_error(self, mock_messages):
        """When reranker fails, search should fall back to RRF order."""
        with patch('src.utils.search.get_reranker_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.rerank.side_effect = Exception("Reranker unavailable")
            mock_get_client.return_value = mock_client

            with patch('src.utils.search.settings') as mock_settings:
                mock_settings.RERANKER.ENABLED = True
                mock_settings.RERANKER.TOP_K = 5

                with patch('src.utils.search._run_search') as mock_run_search:
                    mock_run_search.return_value = mock_messages[:5]

                    results = await search(
                        query="test query",
                        filters={"workspace_name": "test-workspace"},
                        limit=5
                    )

                    # Should fall back to RRF order despite error
                    assert [r.id for r in results] == ["msg-0", "msg-1", "msg-2", "msg-3", "msg-4"]

    @pytest.mark.asyncio
    async def test_search_rerank_respects_top_k_cap(self, mock_messages):
        """Reranker should only be called with TOP_K documents, not all results."""
        with patch('src.utils.search.get_reranker_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.rerank.return_value = [0.5] * 3  # Only 3 scores for TOP_K=3
            mock_get_client.return_value = mock_client

            with patch('src.utils.search.settings') as mock_settings:
                mock_settings.RERANKER.ENABLED = True
                mock_settings.RERANKER.TOP_K = 3

                with patch('src.utils.search._run_search') as mock_run_search:
                    mock_run_search.return_value = mock_messages[:10]  # 10 results from RRF

                    results = await search(
                        query="test query",
                        filters={"workspace_name": "test-workspace"},
                        limit=10
                    )

                    # Reranker should only receive TOP_K=3 documents
                    call_args = mock_client.rerank.call_args
                    assert len(call_args[1]['documents']) == 3

                    # Results beyond TOP_K should remain in RRF order
                    assert results[3].id == "msg-3"
                    assert results[4].id == "msg-4"

    @pytest.mark.asyncio
    async def test_search_rerank_empty_results(self):
        """Empty search results should not crash reranker."""
        with patch('src.utils.search.get_reranker_client') as mock_get_client:
            with patch('src.utils.search.settings') as mock_settings:
                mock_settings.RERANKER.ENABLED = True

                with patch('src.utils.search._run_search') as mock_run_search:
                    mock_run_search.return_value = []

                    results = await search(
                        query="test query",
                        filters={"workspace_name": "test-workspace"},
                        limit=5
                    )

                    assert results == []
                    mock_get_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_rerank_single_result(self, mock_messages):
        """Single result should not trigger reranker (no point reranking 1 item)."""
        with patch('src.utils.search.get_reranker_client') as mock_get_client:
            with patch('src.utils.search.settings') as mock_settings:
                mock_settings.RERANKER.ENABLED = True

                with patch('src.utils.search._run_search') as mock_run_search:
                    mock_run_search.return_value = [mock_messages[0]]

                    results = await search(
                        query="test query",
                        filters={"workspace_name": "test-workspace"},
                        limit=5
                    )

                    assert len(results) == 1
                    assert results[0].id == "msg-0"
                    mock_get_client.assert_not_called()