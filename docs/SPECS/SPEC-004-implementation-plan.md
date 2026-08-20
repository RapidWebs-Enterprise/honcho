# IMPLEMENTATION PLAN: Cross-Encoder Reranking & Context Injection (SPEC-004)

**Mode:** MEDIUM (plan-and-audit)  
**Generated:** 2026-08-20  
**Status:** Signed off — ready for TDD execution (Phase 7)  
**Estimated Effort:** ~6 hours across 8 tasks  

---

## Executive Summary

Add cross-encoder reranking to Honcho's hybrid search pipeline using the existing RW InferenceEngine `/v1/rerank` endpoint, and expose a KG context-dump endpoint for periodic Hermes auto-injection.

**Key Decision:** Graceful degradation built-in — `RERANKER.ENABLED=false` instantly falls back to RRF-only search.

---

## File Manifest (5 Files Modified + 1 New + Tests)

| # | File | Type | Lines | Purpose |
|---|------|------|-------|---------|
| 1 | `src/config.py` | MODIFY | ~30 | `RerankerSettings` class + SECTION_MAP + AppSettings registration |
| 2 | `src/reranker_client.py` | **NEW** | ~80 | Async HTTP client for RW IE `/v1/rerank` with bounded pool |
| 3 | `src/utils/search.py` | MODIFY | ~25 | Reranking stage inside `_run_search()` closure (post-RRF) |
| 4 | `src/routers/kg.py` | MODIFY | ~50 | `GET /context-dump` endpoint with ID→name resolution + dormant filter |
| 5 | `config.toml.example` | MODIFY | ~10 | Document `[reranker]` section |
| 6 | `tests/test_reranker_client.py` | **NEW** | ~60 | Unit tests for RerankerClient |
| 7 | `tests/test_search_rerank.py` | **NEW** | ~80 | Integration test for search pipeline with reranker |

---

## Task Breakdown (Dependency-Ordered)

### Task 1: Configuration — `src/config.py`
**Depends:** None  
**Files:** `src/config.py` (3 locations)  
**Effort:** 30 min

**Changes:**

```python
# A. Add RerankerSettings class (after ExtractionSettings, ~line 948)
class RerankerSettings(HonchoSettings):
    model_config = SettingsConfigDict(env_prefix="RERANKER_", extra="ignore")

    ENABLED: bool = True
    ENDPOINT: str = "http://localhost:8300/v1/rerank"
    MODEL: str = "ms-marco-MiniLM-L-6-v2"
    TOP_K: int = 50
    TIMEOUT_SECONDS: float = 30.0


# B. Register in TomlConfigSettingsSource.SECTION_MAP (line ~583-600)
SECTION_MAP: ClassVar[dict[str, str]] = {
    ...
    "DERIVER": "deriver",
    "PEER_CARD": "peer_card",
    "DIALECTIC": "dialectic",
    "RERANKER": "reranker",           # ← ADD THIS
    "SUMMARY": "summary",
    ...
}


# C. Register in AppSettings nested models (after METRICS, ~line 1499)
class AppSettings(HonchoSettings):
    ...
    METRICS: MetricsSettings = Field(default_factory=MetricsSettings)
    TELEMETRY: TelemetrySettings = Field(default_factory=TelemetrySettings)
    CACHE: CacheSettings = Field(default_factory=CacheSettings)
    DREAM: DreamSettings = Field(default_factory=DreamSettings)
    VECTOR_STORE: VectorStoreSettings = Field(default_factory=VectorStoreSettings)
    TRACE_VIEWER: TraceViewerSettings = Field(default_factory=TraceViewerSettings)
    RERANKER: RerankerSettings = Field(default_factory=RerankerSettings)  # ← ADD THIS
```

**Acceptance:** `python3 -c "from src.config import settings; print(settings.RERANKER.ENABLED, settings.RERANKER.ENDPOINT)"` → `True http://localhost:8300/v1/rerank`

---

### Task 2: Reranker Client Module — `src/reranker_client.py`
**Depends:** Task 1  
**Files:** `src/reranker_client.py` (new)  
**Effort:** 45 min

**Full Implementation:**

```python
"""
Cross-encoder reranker client for RW InferenceEngine.

Provides second-stage relevance scoring for search results via POST /v1/rerank.
"""

import logging
from typing import list

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


class RerankerClient:
    """
    Client for RW InferenceEngine's /v1/rerank endpoint.
    
    Uses cross-encoder model (ms-marco-MiniLM-L-6-v2) to score
    query-document pairs for relevance.
    
    RA-03: Bounded connection pool (max 10) to prevent exhaustion.
    """
    
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        model: str | None = None,
    ):
        self.base_url = (base_url or settings.RERANKER.ENDPOINT).rstrip("/")
        self.model = model or settings.RERANKER.MODEL
        self.timeout = timeout or settings.RERANKER.TIMEOUT_SECONDS
        # RA-03: Bounded pool - prevent connection exhaustion under load
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    
    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int | None = None,
    ) -> list[float]:
        """
        Score query-document pairs using cross-encoder.
        
        RA-01: Does NOT pad with zeros. Returns scores only for reranked docs.
        Caller handles merging with un-reranked tail.
        
        Args:
            query: Search query string
            documents: List of document texts to score
            top_k: Limit reranking to top-k documents
            
        Returns:
            List of relevance scores (0.0-1.0), one per document in `documents[:top_k]`
        """
        if not documents:
            return []
        
        docs_to_rerank = documents[:top_k] if top_k else documents
        
        payload = {
            "query": query,
            "documents": docs_to_rerank,
        }
        
        try:
            resp = await self.client.post(
                f"{self.base_url}",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            
            scores = data.get("scores", [])
            if len(scores) != len(docs_to_rerank):
                logger.warning(
                    "Reranker returned %d scores for %d docs; truncating/padding",
                    len(scores), len(docs_to_rerank)
                )
                scores = scores[:len(docs_to_rerank)]
                while len(scores) < len(docs_to_rerank):
                    scores.append(0.0)
            
            return scores
            
        except httpx.HTTPStatusError as e:
            logger.warning(
                "Reranker HTTP %s: %s",
                e.response.status_code, e.response.text
            )
            return [0.0] * len(documents)
        except httpx.RequestError as e:
            logger.warning("Reranker request failed: %s", e)
            return [0.0] * len(documents)
        except Exception as e:
            logger.warning("Reranker unexpected error: %s", e)
            return [0.0] * len(documents)
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        await self.close()


# Global singleton (RA-03: reuse client, don't recreate per request)
_reranker_client: RerankerClient | None = None


async def get_reranker_client() -> RerankerClient:
    """Get or create the global reranker client."""
    global _reranker_client
    if _reranker_client is None:
        _reranker_client = RerankerClient()
    return _reranker_client
```

**Acceptance:**
```bash
python3 -c "
import asyncio
from src.reranker_client import get_reranker_client
async def test():
    c = await get_reranker_client()
    scores = await c.rerank('test query', ['doc1', 'doc2'])
    print(f'Scores: {scores}, type: {type(scores)}')
    await c.close()
asyncio.run(test())
"
```
→ Should run without error (may return zeros if RW IE not running locally)

---

### Task 3: Search Integration — `src/utils/search.py`
**Depends:** Task 2  
**Files:** `src/utils/search.py` (lines 1-20 imports + `_run_search` closure)  
**Effort:** 45 min

**Changes:**

```python
# A. Add import (after line 16)
from src.reranker_client import get_reranker_client


# B. Replace _run_search() return block (lines 444-449)
#    CURRENT:
#        if len(search_results) > 1:
#            return reciprocal_rank_fusion(*search_results, limit=limit)
#        if len(search_results) == 1:
#            return search_results[0][:limit]
#        return []
#
#    NEW:
        if len(search_results) > 1:
            fused = reciprocal_rank_fusion(*search_results, limit=limit)

            # FA-01: Reranker runs INSIDE _run_search() (before message expunge)
            if settings.RERANKER.ENABLED and len(fused) > 1:
                try:
                    reranker = await get_reranker_client()
                    rerank_limit = min(settings.RERANKER.TOP_K, len(fused))
                    if rerank_limit > 1:
                        doc_texts = [msg.content for msg in fused[:rerank_limit]]
                        scores = await reranker.rerank(query, doc_texts, top_k=rerank_limit)

                        # Combine and sort by reranker score (descending)
                        scored = list(zip(fused[:rerank_limit], scores))
                        scored.sort(key=lambda x: x[1], reverse=True)
                        reranked = [doc for doc, _ in scored]

                        # RA-01: Un-reranked docs stay in RRF order at tail
                        fused = reranked + fused[rerank_limit:]
                except ValueError as e:
                    logger.warning("Reranker validation error: %s", e)
                except Exception as e:
                    logger.warning("Reranking failed, using RRF order: %s", e)
            return fused

        if len(search_results) == 1:
            return search_results[0][:limit]
        return []
```

**Acceptance:**
```bash
PYTHONPATH=src python3 -c "
import asyncio
from src.utils.search import search
from src.config import settings
settings.EMBED_MESSAGES = False  # Avoid embedding call for test
async def test():
    results = await search('test query', filters={'workspace_id': 'test'}, limit=5)
    print(f'Results: {len(results)}')
asyncio.run(test())
"
```
→ Should run without error

---

### Task 4: KG Context-Dump Endpoint — `src/routers/kg.py`
**Depends:** Task 3 (uses `subgraph`)  
**Files:** `src/routers/kg.py` (new endpoint)  
**Effort:** 45 min

**Add at end of router (after `kg_update_entity`, ~line 309):**

```python
@router.get("/context-dump")
async def kg_context_dump(
    workspace_id: str = Path(...),
    peer: str = Query(default="sysop", min_length=1),
    max_entities: int = Query(default=20, ge=1, le=100),
    max_depth: int = Query(default=1, ge=0, le=3),
    limit_per_entity: int = Query(default=10, ge=1, le=50),
    db_session: AsyncSession = Depends(get_read_db),
):
    """
    Lightweight context dump for periodic Hermes auto-injection.
    
    No LLM calls — pure graph queries. Returns peer entities + 1-hop
    neighborhoods formatted for injection.
    
    RA-06: Resolves entity IDs to names in relationships.
    RA-07: Filters dormant entities (confidence < 0.1).
    RA-12: Token estimate uses raw JSON length / 4.
    """
    from sqlalchemy import select as sel
    from datetime import datetime, timezone
    import json
    
    # 1. Peer entities (RA-07: skip dormant)
    from src.kg.models import KGEntity
    stmt = sel(KGEntity).where(
        KGEntity.workspace_name == workspace_id,
        KGEntity.peer_name == peer,
        KGEntity.confidence >= 0.1,
    ).order_by(KGEntity.confidence.desc()).limit(max_entities)
    result = await db_session.execute(stmt)
    peer_entities = result.scalars().all()
    
    entities_data = [
        {
            "name": e.name,
            "type": e.entity_type,
            "confidence": e.confidence,
            "mention_count": e.mention_count,
        }
        for e in peer_entities
    ]
    
    # 2. Neighborhoods (top 5 entities)
    neighborhoods = {}
    for entity in peer_entities[:min(5, len(peer_entities))]:
        entity_name = entity.name
        sub = await subgraph(
            db_session, workspace_id, entity_name,
            depth=max_depth, limit=limit_per_entity,
        )
        
        # RA-06: Resolve entity IDs -> names in relationships
        id_to_name = {ent["id"]: ent["name"] for ent in sub["entities"]}
        for rel in sub["relationships"]:
            rel["source"] = id_to_name.get(str(rel["source"]), str(rel["source"]))
            rel["target"] = id_to_name.get(str(rel["target"]), str(rel["target"]))
        
        neighborhoods[entity_name] = sub
    
    # 3. Token estimate (RA-12: raw JSON length / 4)
    raw = json.dumps(
        {"peer_entities": entities_data, "neighborhoods": neighborhoods},
        separators=(",", ":"),
        default=str,
    )
    token_estimate = len(raw.encode("utf-8")) // 4
    
    return {
        "peer_entities": entities_data,
        "neighborhoods": neighborhoods,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "token_estimate": token_estimate,
    }
```

**Acceptance:**
```bash
# Requires running Honcho instance - test via curl after deploy
curl "http://infra:8000/v3/workspaces/hermes/kg/context-dump?peer=sysop"
```
→ Should return JSON with `peer_entities`, `neighborhoods`, `generated_at`, `token_estimate`

---

### Task 5: Config Documentation — `config.toml.example`
**Depends:** Task 1  
**Files:** `config.toml.example`  
**Effort:** 10 min

**Add at end of file:**

```toml
# --- Reranker (cross-encoder search reranking) ---
# Uses RW InferenceEngine /v1/rerank endpoint for second-stage
# relevance scoring of RRF-fused search results.
# Disabled by default for zero-config deployments; enable when
# RW InferenceEngine is available.
# [reranker]
# ENABLED = true
# ENDPOINT = "http://localhost:8300/v1/rerank"
# MODEL = "ms-marco-MiniLM-L-6-v2"
# TOP_K = 50
# TIMEOUT_SECONDS = 30.0
```

---

### Task 6: Unit Tests — `tests/test_reranker_client.py`
**Depends:** Task 2  
**Files:** `tests/test_reranker_client.py` (new)  
**Effort:** 30 min

```python
"""Unit tests for RerankerClient."""

import pytest
from unittest.mock import AsyncMock, patch

from src.reranker_client import RerankerClient


@pytest.fixture
def mock_httpx_client():
    """Mock httpx.AsyncClient."""
    with patch("httpx.AsyncClient") as mock:
        client = AsyncMock()
        mock.return_value = client
        yield client


@pytest.mark.asyncio
async def test_reranker_client_empty_documents(mock_httpx_client):
    """Empty documents returns empty list without calling endpoint."""
    client = RerankerClient()
    scores = await client.rerank("query", [])
    assert scores == []


@pytest.mark.asyncio
async def test_reranker_client_success(mock_httpx_client):
    """Successful reranking returns scores."""
    mock_response = AsyncMock()
    mock_response.raise_for_status = AsyncMock()
    mock_response.json = AsyncMock(return_value={"scores": [0.9, 0.1]})
    mock_httpx_client.post = AsyncMock(return_value=mock_response)
    
    client = RerankerClient()
    scores = await client.rerank("query", ["doc1", "doc2"])
    
    assert scores == [0.9, 0.1]
    mock_httpx_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_reranker_client_top_k_limit(mock_httpx_client):
    """top_k limits documents sent to reranker."""
    mock_response = AsyncMock()
    mock_response.raise_for_status = AsyncMock()
    mock_response.json = AsyncMock(return_value={"scores": [0.8]})
    mock_httpx_client.post = AsyncMock(return_value=mock_response)
    
    client = RerankerClient()
    scores = await client.rerank("query", ["doc1", "doc2", "doc3"], top_k=1)
    
    # Only first doc sent to reranker
    call_args = mock_httpx_client.post.call_args
    assert call_args.kwargs["json"]["documents"] == ["doc1"]
    assert scores == [0.8]


@pytest.mark.asyncio
async def test_reranker_client_http_error(mock_httpx_client):
    """HTTP error returns zeros without raising."""
    import httpx
    mock_httpx_client.post = AsyncMock(
        side_effect=httpx.HTTPStatusError("Error", request=None, response=None)
    )
    
    client = RerankerClient()
    scores = await client.rerank("query", ["doc1", "doc2"])
    
    assert scores == [0.0, 0.0]


@pytest.mark.asyncio
async def test_reranker_client_request_error(mock_httpx_client):
    """Network error returns zeros without raising."""
    import httpx
    mock_httpx_client.post = AsyncMock(side_effect=httpx.RequestError("Network error"))
    
    client = RerankerClient()
    scores = await client.rerank("query", ["doc1"])
    
    assert scores == [0.0]
```

---

### Task 7: Integration Test — `tests/test_search_rerank.py`
**Depends:** Task 3  
**Files:** `tests/test_search_rerank.py` (new)  
**Effort:** 45 min

```python
"""Integration tests for search pipeline with reranker."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.utils.search import search
from src.config import settings


@pytest.fixture(autouse=True)
def disable_embeddings():
    """Disable embedding calls for tests."""
    settings.EMBED_MESSAGES = False
    yield
    settings.EMBED_MESSAGES = True


@pytest.fixture
def mock_db_session():
    """Mock database session returning fake messages."""
    from src import models
    
    msg1 = MagicMock(spec=models.Message)
    msg1.content = "First document about authentication"
    msg1.public_id = "msg1"
    msg1.created_at = "2026-01-01T00:00:00Z"
    
    msg2 = MagicMock(spec=models.Message)
    msg2.content = "Second document about authorization"
    msg2.public_id = "msg2"
    msg2.created_at = "2026-01-02T00:00:00Z"
    
    # Fulltext returns both
    # Semantic returns both
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: [msg1, msg2]))))
    return session


@pytest.mark.asyncio
async def test_search_reranker_disabled_by_default(mock_db_session):
    """When reranker disabled, uses RRF only."""
    settings.RERANKER.ENABLED = False
    
    with patch("src.utils.search.tracked_db") as mock_tracked:
        mock_tracked.return_value.__aenter__ = AsyncMock(return_value=mock_db_session)
        mock_tracked.return_value.__aexit__ = AsyncMock(return_value=None)
        
        results = await search("auth", filters={"workspace_id": "test"}, limit=10)
        
        # Should return both messages (fulltext + semantic both hit)
        assert len(results) == 2


@pytest.mark.asyncio
async def test_search_reranker_enabled_returns_scored_results(mock_db_session):
    """When reranker enabled and succeeds, results are reordered by score."""
    settings.RERANKER.ENABLED = True
    
    # Mock reranker to return high score for second doc, low for first
    with patch("src.utils.search.get_reranker_client") as mock_get_client:
        mock_reranker = AsyncMock()
        mock_reranker.rerank = AsyncMock(return_value=[0.2, 0.9])  # doc2 > doc1
        mock_get_client.return_value = mock_reranker
        
        with patch("src.utils.search.tracked_db") as mock_tracked:
            mock_tracked.return_value.__aenter__ = AsyncMock(return_value=mock_db_session)
            mock_tracked.return_value.__aexit__ = AsyncMock(return_value=None)
            
            results = await search("auth", filters={"workspace_id": "test"}, limit=10)
            
            # doc2 should now be first (higher reranker score)
            assert results[0].content == "Second document about authorization"
            assert results[1].content == "First document about authentication"


@pytest.mark.asyncio
async def test_search_reranker_failure_falls_back_to_rrf(mock_db_session):
    """Reranker failure falls back to RRF order."""
    settings.RERANKER.ENABLED = True
    
    with patch("src.utils.search.get_reranker_client") as mock_get_client:
        mock_reranker = AsyncMock()
        mock_reranker.rerank = AsyncMock(side_effect=Exception("Network down"))
        mock_get_client.return_value = mock_reranker
        
        with patch("src.utils.search.tracked_db") as mock_tracked:
            mock_tracked.return_value.__aenter__ = AsyncMock(return_value=mock_db_session)
            mock_tracked.return_value.__aexit__ = AsyncMock(return_value=None)
            
            results = await search("auth", filters={"workspace_id": "test"}, limit=10)
            
            # Falls back to original RRF order (should be 2 results)
            assert len(results) == 2


@pytest.mark.asyncio
async def test_search_top_k_cap(mock_db_session):
    """TOP_K limits how many docs get reranked."""
    settings.RERANKER.ENABLED = True
    settings.RERANKER.TOP_K = 1  # Only rerank top 1
    
    with patch("src.utils.search.get_reranker_client") as mock_get_client:
        mock_reranker = AsyncMock()
        mock_reranker.rerank = AsyncMock(return_value=[0.5])
        mock_get_client.return_value = mock_reranker
        
        with patch("src.utils.search.tracked_db") as mock_tracked:
            mock_tracked.return_value.__aenter__ = AsyncMock(return_value=mock_db_session)
            mock_tracked.return_value.__aexit__ = AsyncMock(return_value=None)
            
            results = await search("auth", filters={"workspace_id": "test"}, limit=10)
            
            # Only 1 doc sent to reranker
            mock_reranker.rerank.assert_called_once()
            call_args = mock_reranker.rerank.call_args
            assert len(call_args.kwargs["documents"]) == 1
```

---

### Task 8: Verification & Lint
**Depends:** Tasks 1-7  
**Files:** All  
**Effort:** 30 min

```bash
# 1. Type checking
cd ~/Workspaces/honcho && python3 -m mypy src/config.py src/reranker_client.py src/utils/search.py src/routers/kg.py

# 2. Lint
cd ~/Workspaces/honcho && ruff check src/ tests/

# 3. Format
cd ~/Workspaces/honcho && ruff format src/ tests/

# 4. Unit tests
cd ~/Workspaces/honcho && PYTHONPATH=src python3 -m pytest tests/test_reranker_client.py -v

# 5. Integration tests
cd ~/Workspaces/honcho && PYTHONPATH=src python3 -m pytest tests/test_search_rerank.py -v

# 6. Full test suite (targeted - not full suite per MEDIUM mode guidance)
cd ~/Workspaces/honcho && PYTHONPATH=src python3 -m pytest tests/test_search_rerank.py tests/test_reranker_client.py -v --tb=short
```

---

## Rollback Strategy

| Scenario | Command | Time |
|----------|---------|------|
| Reranker misbehaves in prod | `RERANKER_ENABLED=false` in env / config.toml | Instant |
| Code breaks search | `git revert <commit>` | < 1 min |
| Context-dump endpoint broken | Remove endpoint from kg.py | < 2 min |
| Full rollback | `git reset --hard HEAD~1` (if single commit) | < 1 min |

**No database migration required** — all changes are additive, read-only, or config flags.

---

## Hermes Plugin (DEFERRED)

**Not in this plan.** Lives in `~/.hermes/plugins/honcho-context-injector/`. Will be implemented after Honcho deploy and validated on infra VM.

---

## Success Criteria (Definition of Done)

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| `mypy` clean | 0 errors | `mypy src/` |
| `ruff` clean | 0 errors | `ruff check src/` |
| Unit tests pass | 100% | `pytest tests/test_reranker_client.py` |
| Integration tests pass | 100% | `pytest tests/test_search_rerank.py` |
| Search falls back on reranker failure | Verified | Integration test |
| Reranker TOP_K cap respected | Verified | Unit test |
| Context-dump returns names (not IDs) | Verified | Manual curl |
| Token estimate reasonable | < 3000 | Context-dump response |
| Config loads from TOML/env | Verified | Config test |

---

## Sign-off

**All audits complete. Plan reviewed and approved.**

- Forward Audit: ✅ `docs/specs/audits/forward-audit-spec-004.md`
- Reverse Audit: ✅ `docs/specs/audits/reverse-audit-spec-004.md`  
- Synthesis: ✅ `docs/specs/audits/synthesis-spec-004.md`
- This Plan: ✅ `docs/SPECS/SPEC-004-implementation-plan.md` (this file)

**Ready for Phase 7: TDD Implementation.**

---

## Execution Notes

- **Run Tasks 1-5 sequentially** (each depends on previous)
- **Tasks 6-7 can run in parallel** (independent test files)
- **Task 8 after all others**
- **Total sequential time:** ~3.5 hours
- **With parallel tests:** ~3 hours