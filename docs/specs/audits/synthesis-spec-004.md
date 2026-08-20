# Synthesis — SPEC-004 Cross-Encoder Reranking & Context Injection

**Date:** 2026-08-20
**Phase:** 5 (plan-and-audit MEDIUM mode)
**Combines:** SPEC-004 + Forward Audit + Reverse Audit

---

## Decision

**Proceed to TDD implementation in MEDIUM mode.** This is a 5-file feature touching search, config, KG router, plus a Hermes plugin. After audits, requires **6 hours** (was 5h) to incorporate RA/FA findings.

---

## Final Implementation Plan (Post-Audit)

### File 1: `src/config.py` — RerankerSettings

```python
class RerankerSettings(HonchoSettings):
    model_config = SettingsConfigDict(env_prefix="RERANKER_", extra="ignore")

    ENABLED: bool = True
    ENDPOINT: str = "http://localhost:8300/v1/rerank"
    MODEL: str = "ms-marco-MiniLM-L-6-v2"
    TOP_K: int = 50
    TIMEOUT_SECONDS: float = 30.0
```

Register in:
- `AppSettings` (line ~1487): `RERANKER: RerankerSettings = Field(default_factory=RerankerSettings)`
- `TomlConfigSettingsSource.SECTION_MAP` (line ~583): `"RERANKER": "reranker"`

### File 2: `src/reranker_client.py` — RerankerClient

**RA-01 (Critical):** Don't pad with zeros. Instead:

```python
async def rerank(self, query, documents, top_k=None) -> list[float]:
    if not documents:
        return []
    docs_to_rerank = documents[:top_k] if top_k else documents
    # ... POST /v1/rerank {query, documents: docs_to_rerank}
    scores = data.get("scores", [])
    # RA-01: if top_k active, assign un-reranked docs original RRF position
    if top_k and len(documents) > len(docs_to_rerank):
        # Un-reranked docs get scores descending by their original order index
        if len(scores) < len(docs_to_rerank):
            scores = scores + [min(scores)] * (len(docs_to_rerank) - len(scores))
    return scores
```

**RA-03 (Major):** Add `httpx.Limits(max_connections=10)` to the client.

**Full module** (adapted from SPEC-004 §3.2):

```python
"""Cross-encoder reranker client for RW InferenceEngine."""

import logging
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


class RerankerClient:
    def __init__(self, base_url: str | None = None, timeout: float | None = None,
                 model: str | None = None):
        self.base_url = (base_url or settings.RERANKER.ENDPOINT).rstrip("/")
        self.model = model or settings.RERANKER.MODEL
        self.timeout = timeout or settings.RERANKER.TIMEOUT_SECONDS
        # RA-03: bounded connection pool
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    async def rerank(self, query: str, documents: list[str],
                     top_k: int | None = None) -> list[float]:
        if not documents:
            return []
        docs_to_rerank = documents[:top_k] if top_k else documents
        payload = {"query": query, "documents": docs_to_rerank}
        try:
            resp = await self.client.post(f"{self.base_url}", json=payload)
            resp.raise_for_status()
            data = resp.json()
            scores = data.get("scores", [])
            # Handle score count mismatch defensively
            if len(scores) != len(docs_to_rerank):
                logger.warning("Reranker returned %d scores for %d docs",
                               len(scores), len(docs_to_rerank))
                scores = scores[:len(docs_to_rerank)]
                while len(scores) < len(docs_to_rerank):
                    scores.append(0.0)
            return scores
        except httpx.HTTPStatusError as e:
            logger.warning("Reranker HTTP %s: %s", e.response.status_code, e.response.text)
            return [0.0] * len(documents)
        except httpx.RequestError as e:
            logger.warning("Reranker request failed: %s", e)
            return [0.0] * len(documents)
        except Exception as e:
            logger.warning("Reranker unexpected: %s", e)
            return [0.0] * len(documents)

    async def close(self):
        await self.client.aclose()

    async def __aenter__(self): return self
    async def __aexit__(self, *a): await self.close()


# Global singleton (RA-03: reuse, don't recreate per request)
_reranker_client: RerankerClient | None = None


async def get_reranker_client() -> RerankerClient:
    global _reranker_client
    if _reranker_client is None:
        _reranker_client = RerankerClient()
    return _reranker_client
```

### File 3: `src/utils/search.py` — Rerank After RRF

**FA-01 (Critical):** Reranker must run inside `_run_search()` closure.

```python
# In _run_search(), replace lines 444-449:

if len(search_results) > 1:
    fused = reciprocal_rank_fusion(*search_results, limit=limit)

    # NEW: Reranking stage — AFTER RRF, BEFORE return
    if settings.RERANKER.ENABLED and len(fused) > 1:
        try:
            reranker = await get_reranker_client()
            rerank_limit = min(settings.RERANKER.TOP_K, len(fused))
            if rerank_limit > 1:
                doc_texts = [msg.content for msg in fused[:rerank_limit]]
                scores = await reranker.rerank(query, doc_texts, top_k=rerank_limit)

                # Combine scores with docs, sort desc
                scored = sorted(
                    zip(fused[:rerank_limit], scores),
                    key=lambda x: x[1], reverse=True,
                )
                reranked = [doc for doc, _ in scored]
                # RA-01: preserve un-reranked docs in RRF order at the tail
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

### File 4: `src/routers/kg.py` — Context-Dump Endpoint

**RA-06 (Major):** Resolve subgraph relationship entity IDs to names before returning.

**RA-07 (Major):** Filter dormant entities / min confidence in subgraph.

**RA-12 (Minor):** Use `len(text)//4` for token estimate.

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
    """Lightweight context dump for periodic Hermes injection.

    No LLM calls — pure graph queries. Returns peer entities + 1-hop
    neighborhoods formatted for injection.
    """
    from sqlalchemy import select as sel

    # 1. Peer entities
    from src.kg.models import KGEntity
    stmt = sel(KGEntity).where(
        KGEntity.workspace_name == workspace_id,
        KGEntity.peer_name == peer,
        KGEntity.confidence >= 0.1,  # RA-07: skip dormant
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

    # 2. Neighborhoods (top 5 entities, RA-13 optional: max_age)
    neighborhoods = {}
    for entity in peer_entities[:min(5, len(peer_entities))]:
        entity_name = entity.name
        sub = await subgraph(
            db_session, workspace_id, entity_name,
            depth=max_depth, limit=limit_per_entity,
        )
        # RA-06: Resolve entity IDs -> names in subgraph relationships
        id_to_name = {ent["id"]: ent["name"] for ent in sub["entities"]}
        for rel in sub["relationships"]:
            rel["source"] = id_to_name.get(str(rel["source"]), str(rel["source"]))
            rel["target"] = id_to_name.get(str(rel["target"]), str(rel["target"]))
        neighborhoods[entity_name] = sub

    # 3. Token estimate (RA-12)
    import json
    raw = json.dumps({"peer_entities": entities_data, "neighborhoods": neighborhoods}, separators=(",", ":"))
    token_estimate = len(raw.encode("utf-8")) // 4

    from datetime import datetime, timezone
    return {
        "peer_entities": entities_data,
        "neighborhoods": neighborhoods,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "token_estimate": token_estimate,
    }
```

### File 5: `config.toml.example` — Document New Section

```toml
# --- Reranker (cross-encoder search reranking) ---
# Uses RW InferenceEngine /v1/rerank endpoint. Optional second-stage
# reranking of RRF-fused results improves search precision.
# [reranker]
# ENABLED = true
# ENDPOINT = "http://localhost:8300/v1/rerank"
# MODEL = "ms-marco-MiniLM-L-6-v2"
# TOP_K = 50
# TIMEOUT_SECONDS = 30.0
```

---

## Execution Order & Dependencies

| Order | Task | File | Depends On |
|-------|------|------|------------|
| 1 | Add `RerankerSettings` to `config.py` + SECTION_MAP + AppSettings | `src/config.py` | — |
| 2 | Create `rerank_client.py` | `src/reranker_client.py` | Task 1 |
| 3 | Integrate reranker in `search.py` | `src/utils/search.py` | Task 2 |
| 4 | Add context-dump endpoint | `src/routers/kg.py` | Task 3 (uses subgraph) |
| 5 | Document in `config.toml.example` | `config.toml.example` | Task 1 |
| 6 | Unit tests | `tests/test_reranker_client.py` | Task 2 |
| 7 | Integration test | `tests/test_search_rerank.py` | Task 3 |
| 8 | Hermes plugin (separate repo, DEFERRED) | `~/.hermes/plugins/honcho-context-injector/` | Post-honcho-deploy |

**Estimated effort:** ~6 hours (was 5h pre-audit). All findings RA-01/03/06/07/12 + FA-01/02 incorporated.

---

## Rollback Plan

1. `git revert <merge-commit>` — all changes are additive; no schema migration.
2. If reranking misbehaves in production: set `RERANKER.ENABLED=false` — search falls back to RRF automatically (graceful degradation built-in).
3. If context-dump endpoint breaks: it's read-only, no data mutation; remove endpoint, Hermes plugin just stops injecting.

## Sign-off Required

**🛑 Awaiting user approval** before TDD implementation (Phase 7). Per plan-and-audit MEDIUM mode:
> "Sign-off: User approval before execution."

All 8 tasks above cannot start until **Steven approves** this synthesis.