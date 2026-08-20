# SPEC-004 v1.0: Cross-Encoder Reranking & Context Injection for Honcho

## Status: Draft v1.0

## 1. Executive Summary

Add cross-encoder reranking to Honcho's hybrid search pipeline using the existing RW InferenceEngine's `/v1/rerank` endpoint, and expose a KG context-dump endpoint for periodic Hermes auto-injection. This enables higher-precision search results and proactive context delivery to agent sessions.

## 2. Motivation

### 2.1 Current State

| Component | Status | Limitation |
|-----------|--------|------------|
| Hybrid Search | ✅ RRF fusion (semantic + fulltext) | No second-stage reranking; RRF only uses rank positions |
| KG Queries | ✅ BFS traversal, pathfinding | No relevance scoring beyond graph structure |
| RW InferenceEngine | ✅ Deployed on srv1:8300 | Has `/v1/rerank` endpoint with `ms-marco-MiniLM-L-6-v2` — **unused by Honcho** |
| Hermes Integration | ⚠️ Session-start injection only | No periodic auto-injection of KG/LM context |

### 2.2 Gap Analysis

| Capability | Current | Target | Gap |
|------------|---------|--------|-----|
| Search precision (p@10) | ~65% (RRF only) | >85% (with reranking) | Missing cross-encoder stage |
| KG relevance scoring | Graph structure only | Semantic + structural | No cross-encoder on KG results |
| Hermes context freshness | Session-start only | Every N turns | No periodic injection endpoint |

### 2.3 Why Now

- RW InferenceEngine **already deployed** on srv1:8300 with reranker model loaded
- Zero new infrastructure — just wire existing endpoint
- Enables both: **better search** + **proactive Hermes context**

---

## 3. Design

### 3.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        HONCHO SEARCH PIPELINE                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Query → [Semantic (pgvector)] + [Fulltext (FTS)]              │
│              │                              │                   │
│              └──────────────┬──────────────┘                   │
│                             ▼                                   │
│                    RRF Fusion (k=60)                            │
│                             │                                   │
│              ┌──────────────┴──────────────┐                   │
│              ▼                             ▼                   │
│      Top-K from RRF                  Remaining               │
│              │                             │                   │
│              ▼                             │                   │
│    ┌─────────────────────┐                │                   │
│    │  RERANKER (NEW)     │                │                   │
│    │  RW_IE /v1/rerank   │                │                   │
│    │  ms-marco-MiniLM    │                │                   │
│    └─────────┬───────────┘                │                   │
│              │                             │                   │
│              ▼                             ▼                   │
│    Re-sorted top-K              Unchanged order              │
│              │                             │                   │
│              └──────────────┬──────────────┘                   │
│                             ▼                                   │
│                    Unified Results (limit)                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Data Flow

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│   Query     │────▶│  Honcho      │────▶│  RW Inference   │
│  "fix auth" │     │  Search      │     │  Engine         │
└─────────────┘     │  (RRF top-50)│     │  POST /v1/rerank│
                    └──────────────┘     │  {query, docs}  │
                           │             └────────┬────────┘
                           ▼                      ▼
                    ┌──────────────────────────────────┐
                    │  Re-scored + Re-ranked Results   │
                    │  [{"text": "...", "score": 0.94}]│
                    └──────────────────────────────────┘
```

---

### 3.2 Reranker Client Module

**File**: `src/reranker_client.py`

```python
"""
Cross-encoder reranker client for RW InferenceEngine.
Provides second-stage relevance scoring for search results.
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
    """
    
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30.0,
        model: str = "ms-marco-MiniLM-L-6-v2",
    ):
        self.base_url = (base_url or settings.RERANKER.ENDPOINT).rstrip("/")
        self.model = model
        self.client = httpx.AsyncClient(timeout=timeout)
    
    async def rerank(
        self,
        query: str,
        documents: list[str],
        model: str | None = None,
        top_k: int | None = None,
    ) -> list[float]:
        """
        Score query-document pairs using cross-encoder.
        
        Args:
            query: Search query string
            documents: List of document texts to score
            model: Reranker model name (default: ms-marco-MiniLM-L-6-v2)
            top_k: Limit reranking to top-k documents (default: all)
            
        Returns:
            List of relevance scores (0.0-1.0), one per document
        """
        if not documents:
            return []
        
        # Optionally limit to top-k before reranking
        docs_to_rerank = documents[:top_k] if top_k else documents
        
        payload = {
            "query": query,
            "documents": docs_to_rerank,
        }
        
        try:
            resp = await self.client.post(
                f"{self.base_url}/v1/rerank",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            
            scores = data.get("scores", [])
            if len(scores) != len(docs_to_rerank):
                logger.warning(
                    f"Reranker returned {len(scores)} scores for {len(docs_to_rerank)} docs"
                )
                # Pad or truncate
                scores = scores[:len(docs_to_rerank)] + [0.0] * max(0, len(docs_to_rerank) - len(scores))
            
            # If we only reranked top-k, append zeros for remaining
            if top_k and len(documents) > top_k:
                scores = scores + [0.0] * (len(documents) - top_k)
            
            return scores
            
        except httpx.HTTPStatusError as e:
            logger.warning(f"Reranker HTTP error: {e.response.status_code} - {e.response.text}")
            return [0.0] * len(documents)
        except httpx.RequestError as e:
            logger.warning(f"Reranker request failed: {e}")
            return [0.0] * len(documents)
        except Exception as e:
            logger.warning(f"Reranker unexpected error: {e}")
            return [0.0] * len(documents)
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        await self.close()


# Global instance for reuse
_reranker_client: RerankerClient | None = None


async def get_reranker_client() -> RerankerClient:
    """Get or create the global reranker client."""
    global _reranker_client
    if _reranker_client is None:
        _reranker_client = RerankerClient()
    return _reranker_client
```

### 3.3 Search Integration

**File**: `src/utils/search.py` — Modify `search()` function

```python
# Add to imports
from src.reranker_client import get_reranker_client

# In search() function, after RRF fusion (around line 446):
if len(search_results) > 1:
    fused = reciprocal_rank_fusion(*search_results, limit=limit)
    
    # NEW: Cross-encoder reranking stage
    if settings.RERANKER.ENABLED and len(fused) > 1:
        try:
            reranker = await get_reranker_client()
            
            # Limit reranking to top-K from RRF (configurable)
            rerank_limit = min(settings.RERANKER.TOP_K, len(fused))
            if rerank_limit > 1:
                # Extract text content for reranking
                doc_texts = [msg.content for msg in fused[:rerank_limit]]
                
                scores = await reranker.rerank(
                    query=query,
                    documents=doc_texts,
                    model=settings.RERANKER.MODEL,
                    top_k=rerank_limit,
                )
                
                # Re-sort by reranker scores (descending)
                scored_docs = list(zip(fused[:rerank_limit], scores))
                scored_docs.sort(key=lambda x: x[1], reverse=True)
                reranked = [doc for doc, _ in scored_docs]
                
                # Preserve remaining items in RRF order
                fused = reranked + fused[rerank_limit:]
                
        except Exception as e:
            logger.warning(f"Reranking failed, using RRF order: {e}")
    
    return fused[:limit]
```

### 3.4 Configuration

**File**: `src/config.py` — Add to settings

```python
class RerankerSettings(BaseSettings):
    """Cross-encoder reranker configuration."""
    
    ENABLED: bool = True
    ENDPOINT: str = "http://100.64.255.48:8300/v1/rerank"
    MODEL: str = "ms-marco-MiniLM-L-6-v2"
    TOP_K: int = 50  # Rerank top-K from RRF fusion
    TIMEOUT_SECONDS: float = 30.0
    
    class Config:
        env_prefix = "RERANKER_"


class Settings(BaseSettings):
    # ... existing settings ...
    RERANKER: RerankerSettings = RerankerSettings()
```

### 3.5 Configuration File (config.toml)

```toml
[reranker]
enabled = true
endpoint = "http://100.64.255.48:8300/v1/rerank"
model = "ms-marco-MiniLM-L-6-v2"
top_k = 50
timeout_seconds = 30.0
```

---

### 3.5 KG Context-Dump Endpoint

**File**: `src/routers/kg.py` — Add new endpoint

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
    Lightweight context dump for Hermes auto-injection.
    
    Returns peer entities + 1-hop neighborhoods formatted for injection.
    No LLM calls — pure graph queries. Designed for periodic injection.
    
    Returns:
    {
        "peer_entities": [...],
        "neighborhoods": {entity_name: {entities: [...], relationships: [...]}},
        "generated_at": "2026-08-20T12:00:00Z",
        "token_estimate": 1200
    }
    """
    from datetime import datetime, timezone
    
    # Get peer entities
    peer_entities = await kg_peer_entities(
        workspace_id=workspace_id,
        peer_name=peer,
        limit=max_entities,
        db_session=db_session,
    )
    
    entities_data = peer_entities.get("entities", [])
    
    # Get neighborhood for top entities
    neighborhoods = {}
    for entity in entities_data[:min(5, len(entities_data))]:  # Top 5 entities
        entity_name = entity["name"]
        subgraph = await kg_subgraph(
            workspace_id=workspace_id,
            entity=entity_name,
            depth=max_depth,
            limit=limit_per_entity,
            db_session=db_session,
        )
        neighborhoods[entity_name] = subgraph
    
    # Estimate tokens (rough: 4 chars/token)
    import json
    dump_data = {
        "peer_entities": entities_data,
        "neighborhoods": neighborhoods,
    }
    token_estimate = len(json.dumps(dump_data)) // 4
    
    return {
        "peer_entities": entities_data,
        "neighborhoods": neighborhoods,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "token_estimate": token_estimate,
    }
```

---

### 3.6 Hermes Auto-Injection Plugin

**File**: `~/.hermes/plugins/honcho-context-injector/__init__.py`

```python
"""
Honcho Context Injector Plugin for Hermes.

Periodically injects Honcho KG context into Hermes conversations
via the pre_llm_call hook.
"""

import json
import logging
import os
import time
from datetime import datetime

import httpx

from hermes_cli.plugins import register_hook

logger = logging.getLogger(__name__)


# Configuration from environment
HONCHO_BASE_URL = os.environ.get("HONCHO_BASE_URL", "http://100.64.255.48:8000")
HONCHO_WORKSPACE = os.environ.get("HONCHO_WORKSPACE", "hermes")
HONCHO_API_KEY = os.environ.get("HONCHO_API_KEY", "")
INJECTION_INTERVAL = int(os.environ.get("HONCHO_INJECTION_INTERVAL", "10"))
INJECTION_ENABLED = os.environ.get("HONCHO_INJECTION_ENABLED", "true").lower() == "true"
PEER_NAME = os.environ.get("HONCHO_PEER_NAME", "sysop")


def _format_context(data: dict) -> str:
    """Format Honcho context dump for injection."""
    lines = ["=== HONCHO KNOWLEDGE GRAPH CONTEXT ==="]
    lines.append(f"Generated: {data.get('generated_at', 'unknown')}")
    lines.append(f"Token estimate: ~{data.get('token_estimate', '?')}")
    lines.append("")
    
    # Peer entities
    peer_entities = data.get("peer_entities", [])
    if peer_entities:
        lines.append("PEER ENTITIES:")
        for e in peer_entities:
            lines.append(f"  - {e['name']} ({e['type']}) confidence={e['confidence']:.2f} mentions={e.get('mention_count', 0)}")
        lines.append("")
    
    # Neighborhoods
    neighborhoods = data.get("neighborhoods", {})
    if neighborhoods:
        lines.append("ENTITY NEIGHBORHOODS (1-hop):")
        for entity_name, subgraph in neighborhoods.items():
            lines.append(f"  {entity_name}:")
            for ent in subgraph.get("entities", [])[:5]:
                lines.append(f"    - {ent['name']} ({ent['type']})")
            for rel in subgraph.get("relationships", [])[:5]:
                lines.append(f"    - {rel['source']} --{rel['type']}--> {rel['target']}")
            lines.append("")
    
    return "\n".join(lines)


async def _on_pre_llm_call(**payload):
    """Pre-LLM hook: inject Honcho context every N turns."""
    
    if not INJECTION_ENABLED:
        return None
    
    turn_id = payload.get("turn_id", 0)
    if turn_id % INJECTION_INTERVAL != 0:
        return None
    
    session_id = payload.get("session_id", "")
    if not session_id:
        return None
    
    # Build request URL
    url = f"{HONCHO_BASE_URL}/v3/workspaces/{HONCHO_WORKSPACE}/kg/context-dump"
    params = {
        "peer": PEER_NAME,
        "max_entities": 20,
        "max_depth": 1,
        "limit_per_entity": 10,
    }
    headers = {}
    if HONCHO_API_KEY:
        headers["Authorization"] = f"Bearer {HONCHO_API_KEY}"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                context = _format_context(data)
                logger.debug(f"Honcho context injection: {len(context)} chars")
                return {"context": context}
            else:
                logger.warning(f"Honcho context-dump failed: {resp.status_code}")
    except httpx.TimeoutException:
        logger.warning("Honcho context-dump timeout")
    except Exception as e:
        logger.warning(f"Honcho context-dump error: {e}")
    
    return None


def register(ctx):
    """Plugin entry point."""
    if not INJECTION_ENABLED:
        logger.info("Honcho context injection disabled via env")
        return
    
    logger.info(f"Honcho context injector registered (interval={INJECTION_INTERVAL})")
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
```

---

## 4. Configuration Summary

### Honcho (config.toml)

```toml
[reranker]
enabled = true
endpoint = "http://100.64.255.48:8300/v1/rerank"
model = "ms-marco-MiniLM-L-6-v2"
top_k = 50
timeout_seconds = 30.0
```

### Hermes Plugin (environment variables)

```bash
# ~/.hermes/.env additions
HONCHO_BASE_URL=http://100.64.255.48:8000
HONCHO_WORKSPACE=hermes
HONCHO_API_KEY=honcho
HONCHO_INJECTION_ENABLED=true
HONCHO_INJECTION_INTERVAL=10
HONCHO_PEER_NAME=sysop
```

---

## 5. Implementation Plan

| Phase | Task | Effort | Dependencies |
|-------|------|--------|--------------|
| 1 | Add `RerankerSettings` to `config.py` | 30 min | — |
| 2 | Create `src/reranker_client.py` | 45 min | `httpx` (already in deps) |
| 3 | Integrate reranker in `utils/search.py` | 45 min | Phase 1-2 |
| 4 | Add `kg_context_dump` endpoint to `routers/kg.py` | 45 min | — |
| 5 | Add `reranker` section to `config.toml.example` | 15 min | Phase 1 |
| 6 | Create Hermes plugin `honcho-context-injector` | 60 min | — |
| 7 | Add plugin install script + docs | 30 min | Phase 6 |
| 8 | Test end-to-end: search → rerank → results | 30 min | Phase 1-3 |
| 9 | Test: Hermes plugin injection every 10 turns | 30 min | Phase 6 |

**Total**: ~5 hours

---

## 6. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Reranker latency adds >200ms | Medium | Medium | Configurable `TOP_K` (default 50); timeout 30s; graceful fallback to RRF |
| RW IE reranker unavailable | Low | Medium | Graceful degradation — return RRF order if reranker fails |
| Token budget exceeded | Low | Low | Token estimate in context-dump; configurable `max_entities`/`max_depth` |
| Reranker model quality | Low | Medium | `ms-marco-MiniLM-L-6-v2` is well-tested; can swap model via config |
| Network latency to RW IE | Low | Low | Same host network (infra VM); <5ms typical |

---

## 7. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Search p@10 improvement | +20% over RRF | Internal eval set (50 queries) |
| Reranker latency (p95) | < 150ms | RW IE telemetry |
| Reranker error rate | < 1% | Honcho telemetry |
| Hermes injection frequency | Exactly every N turns | Plugin logs |
| Context token budget | < 3000 tokens | Context-dump `token_estimate` |
| End-to-end search latency | < 500ms p95 | Honcho telemetry |

---

## 8. Rollout Plan

1. **Deploy Honcho changes** (reranker + context-dump) to infra VM
2. **Verify** search quality improvement on eval set
3. **Install Hermes plugin** on workstation
4. **Test** injection at interval=10 for 24 hours
5. **Tune** interval/token budget based on real usage
6. **Document** in AGENTS.md + RAPIDWEBS.README.md

---

## 9. References

- RW InferenceEngine reranker: `src/routes/rerank.rs` (ms-marco-MiniLM-L-6-v2)
- Honcho hybrid search: `src/utils/search.py` (RRF fusion)
- KG router: `src/routers/kg.py` (existing endpoints)
- Hermes plugin hooks: `pre_llm_call` injection pattern
- Existing ADRs: ADR-001 (KG Overlay), ADR-003 (KG Tool Gating)