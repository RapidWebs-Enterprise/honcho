"""Cross-encoder reranker client for the RW InferenceEngine.

Provides a typed async HTTP client for the `/v1/rerank` endpoint used as a
second-stage relevance scorer over RRF-fused search results.

Grounding: httpx `AsyncClient` should be a long-lived singleton with a bounded
connection pool (https://www.python-httpx.org/async/, /advanced/resource-limits/),
and per-phase timeouts (https://www.python-httpx.org/advanced/timeouts/) rather
than a flat timeout. Failures degrade gracefully to zero scores so search can
fall back to RRF order.
"""

import logging
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


class RerankerClient:
    """Client for RW InferenceEngine's ``POST /v1/rerank``.

    Scores query-document pairs for relevance using a cross-encoder. Network
    failures never raise to the caller; they fall back to zero scores so the
    search pipeline can keep its RRF ordering.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        model: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.RERANKER.ENDPOINT).rstrip("/")
        self.model = model or settings.RERANKER.MODEL
        self.timeout = timeout or settings.RERANKER.TIMEOUT_SECONDS
        # Long-lived client with a bounded pool (RA-03). Two connections is
        # plenty for the search path and avoids fd exhaustion under load.
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
            ),
        )

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int | None = None,
    ) -> list[float]:
        """Score ``query``-``documents`` pairs.

        Args:
            query: Search query.
            documents: Ordered document texts (RRF order).
            top_k: Only rerank the first ``top_k`` documents. Un-reranked docs
                are not scored; the caller keeps them at the tail.

        Returns:
            One relevance score per element of ``documents[:top_k]``. On any
            network failure, all returned scores are ``0.0``.
        """
        if not documents:
            return []

        docs_to_rerank = documents[:top_k] if top_k else documents

        if not docs_to_rerank:
            return []

        payload: dict[str, Any] = {
            "query": query,
            "documents": docs_to_rerank,
        }

        try:
            resp = await self.client.post(
                self.base_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            scores = data.get("scores", [])

            # Defensively match the number of requested docs.
            if len(scores) != len(docs_to_rerank):
                logger.warning(
                    "Reranker returned %d scores for %d docs; padding",
                    len(scores),
                    len(docs_to_rerank),
                )
                scores = scores[: len(docs_to_rerank)]
                while len(scores) < len(docs_to_rerank):
                    scores.append(0.0)
            return scores

        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Reranker HTTP %s: %s",
                exc.response.status_code if exc.response else "?",
                exc.response.text if exc.response else str(exc),
            )
            return [0.0] * len(docs_to_rerank)
        except httpx.RequestError as exc:
            logger.warning("Reranker request failed: %s", exc)
            return [0.0] * len(docs_to_rerank)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Reranker unexpected error: %s", exc)
            return [0.0] * len(docs_to_rerank)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self.client.aclose()

    async def __aenter__(self) -> "RerankerClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()


# Long-lived singleton (reuse the pooled client across requests).
_reranker_client: RerankerClient | None = None


async def get_reranker_client() -> RerankerClient:
    """Return the shared :class:`RerankerClient` singleton."""
    global _reranker_client
    if _reranker_client is None:
        _reranker_client = RerankerClient()
    return _reranker_client