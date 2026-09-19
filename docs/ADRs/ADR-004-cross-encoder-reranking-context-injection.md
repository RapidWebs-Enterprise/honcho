# ADR-004 v1.0: Cross-Encoder Reranking & Periodic Context Injection

## Status: Proposed

## Context

### Current Architecture

Honcho's search pipeline currently uses **Reciprocal Rank Fusion (RRF)** to combine:
- Semantic search (pgvector cosine distance)
- Fulltext search (PostgreSQL FTS + ILIKE)

Results are fused by rank position only — no second-stage relevance scoring.

RW InferenceEngine (deployed on srv1:8300) exposes a **cross-encoder reranker endpoint** (`POST /v1/rerank` with `ms-marco-MiniLM-L-6-v2`) that is **currently unused** by Honcho.

Hermes integration receives Honcho context only at **session start** via peer card + representation dump. No periodic injection of updated KG/LM context.

### Problem

1. **Search precision limited by RRF** — RRF uses rank positions only, not semantic relevance of query-document pairs. Cross-encoder reranking typically improves p@10 by 15-25%.

2. **Reranker infrastructure exists but unused** — RW InferenceEngine has `ms-marco-MiniLM-L-6-v2` loaded and serving `/v1/rerank`. Zero new infrastructure needed.

3. **Hermes context staleness** — Session-start injection only. Active conversations don't receive updated KG entities, peer relationships, or system status.

### Opportunity

Wire existing reranker endpoint into Honcho search pipeline (+20% precision, ~100ms latency) and expose a lightweight KG context-dump endpoint for periodic Hermes injection.

---

## Decision

### 1. Add Cross-Encoder Reranking Stage to Search Pipeline

**Location**: `src/utils/search.py` — after RRF fusion, before returning results

**Implementation**:
- New module `src/reranker_client.py` — async HTTP client for RW IE `/v1/rerank`
- Configurable `TOP_K` (default 50) — only rerank top-K from RRF
- Graceful fallback: if reranker fails/times out, return RRF order
- Configuration via `settings.RERANKER` (enabled, endpoint, model, top_k, timeout)

**Pipeline**:
```
Query → Semantic + Fulltext → RRF Fusion → Rerank top-K → Re-sort → Return
```

### 2. Expose KG Context-Dump Endpoint

**Location**: `src/routers/kg.py` — new `GET /context-dump`

**Response**:
```json
{
  "peer_entities": [...],
  "neighborhoods": {entity_name: {entities: [...], relationships: [...]}},
  "generated_at": "2026-08-20T12:00:00Z",
  "token_estimate": 1200
}
```

**Parameters**:
- `peer` (default: "sysop")
- `max_entities` (default: 20)
- `max_depth` (default: 1)
- `limit_per_entity` (default: 10)

**No LLM calls** — pure graph queries for speed and reliability.

### 3. Create Hermes Auto-Injection Plugin

**Location**: `~/.hermes/plugins/honcho-context-injector/`

**Mechanism**: Registers `pre_llm_call` hook, fires every N turns (configurable, default 10)

**Injection Content**: Formatted KG context dump (peer entities + 1-hop neighborhoods)

**Configuration**: Environment variables (`HONCHO_BASE_URL`, `HONCHO_WORKSPACE`, `HONCHO_INJECTION_INTERVAL`, etc.)

---

## Consequences

### Positive

- **Search precision**: Expected +20% p@10 over RRF-only baseline
- **Zero new infrastructure**: Uses existing RW IE deployment
- **Proactive context**: Hermes receives fresh KG context every N turns
- **Configurable**: All parameters tunable via config/env
- **Graceful degradation**: Reranker failures fall back to RRF; plugin disabled via env
- **Token-aware**: Context-dump includes token estimate; plugin respects budgets

### Negative

- **Added latency**: ~100ms for reranking top-50 (mitigated by TOP_K limit)
- **External dependency**: Search now calls RW IE (already required for embeddings)
- **Plugin maintenance**: Hermes plugin separate from Honcho core
- **Token overhead**: Injection adds ~1-3k tokens per injection (configurable)

### Neutral

- No database schema changes
- No new model dependencies (uses existing `ms-marco-MiniLM-L-6-v2`)
- No changes to Deriver pipeline or message ingestion

---

## Compliance

- All new code follows existing patterns (async, typed, structured logging)
- Configuration via existing `settings` system with env override
- Reranker client uses existing `httpx` dependency
- Plugin follows Hermes plugin hook contract
- KG endpoint follows existing `/v3/workspaces/{w}/kg/*` pattern
- Telemetry: Reranker latency/errors logged via existing logger

---

## References

- SPEC-004 v1.0 (this feature)
- ADR-001: Knowledge Graph Overlay (existing KG architecture)
- ADR-003: KG Tool Gating (existing KG API governance)
- RW InferenceEngine: `src/routes/rerank.rs` (reranker endpoint spec)
- Honcho search: `src/utils/search.py` (RRF fusion implementation)
- KG router: `src/routers/kg.py` (existing KG endpoints)
- Hermes plugin hooks: `pre_llm_call` injection pattern