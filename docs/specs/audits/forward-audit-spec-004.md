# Forward Audit — SPEC-004 Cross-Encoder Reranking & Context Injection

**Date:** 2026-08-20
**Auditor:** Lucien (inline, plan-and-audit MEDIUM mode)
**Reference:** `docs/SPECS/SPEC-004-cross-encoder-reranking-context-injection.md`

---

## Audit Scope

Verifying each SPEC-004 claim against the actual Honcho fork source code.

| SPEC Section | Claim | Verified Against | Result |
|--------------|-------|------------------|--------|
| §3.3 | Reranker integration point is after RRF (line 445-446) | `src/utils/search.py:445-446` | ✅ Page 1 |

---

## Detailed Findings

### §3.3 Reranker Integration Point (`search.py`)

```python
# search.py lines 444-449
if len(search_results) > 1:
    return reciprocal_rank_fusion(*search_results, limit=limit)
if len(search_results) == 1:
    return search_results[0][:limit]
return []
```

**Verification:** ✅ Correct insertion point. The `_run_search()` inner function returns here. Reranking should wrap this block. Note: `_run_search` returns `list[models.Message]` — messages have `.content` for reranking.

**Pitfall discovered:** The reranker stage must run INSIDE `_run_search()` (where messages aren't yet expunged) or after expunge but before return. Since `tracked_db` expunges objects after `_run_search` completes, the reranker must operate within `_run_search` closure.

### §3.4 RerankerSettings (`config.py`)

**Verification:** ✅ `AppSettings` registers nested settings models at lines 1488-1504 (`DB`, `AUTH`, ..., `TRACE_VIEWER`). Adding a `RERANKER: RerankerSettings` field follows the established pattern.

**The `RerankerSettings` class needs to be registered in `TomlConfigSettingsSource.SECTION_MAP`** (`src/config.py:583-600`) — otherwise `config.toml [reranker]` won't load.

### §3.3 RerankerClient (`httpx` pattern)

**Verification:** ✅ `httpx` is in `pyproject.toml` (`httpx>=0.27.0`). Existing pattern in `src/webhooks/webhook_delivery.py` uses `async with httpx.AsyncClient(timeout=30.0)`. The embedding client uses OpenAI SDK — but for reranking, raw `httpx` is correct since RW IE exposes a simple REST endpoint.

### §3.5 KG Context-Dump Endpoint (`kg.py` router)

**Verification:** ✅ Router at `src/routers/kg.py` uses `APIRouter(prefix="/v3/workspaces/{workspace_id}/kg", ...)`. Adding a `@router.get("/context-dump")` endpoint fits. The existing `peer-entities` and `subgraph` endpoints show the pattern.

**Dependency check:** The subgraph endpoint uses `get_read_db` via `Depends(get_read_db)`, and `subgraph()` from `src/kg/graph.py` resolves entity by NAME. `peer-entities` returns entity names. ✅ Feasible.

### §3.6 Hermes Plugin (`pre_llm_call` hook)

**Verification:** ⚠️ The plugin lives in a separate location (`~/.hermes/plugins/`, not the Honcho repo). The SPEC references it conceptually. The hook registration pattern matches Hermes plugin contract. **Note:** this is outside the Honcho core scope and deferred to a later phase per the synthesis recommendation.

### §3.3 RW IE `/v1/rerank` Contract

**Verification:** ✅ `RW_InferenceEngine/src/routes/rerank.rs`
- Method: `POST /v1/rerank`
- Request: `{"query": str, "documents": [str]}`
- Response: `{"scores": [float], "model": "ms-marco-MiniLM-L-6-v2"}`
- Empty docs → `{scores: [], model: ...}`

Matches SPEC-004 §3.2 exactly.

**Note:** The model is hardcoded server-side as `ms-marco-MiniLM-L-6-v2`; the request body's `model` field (if sent) is ignored. Sending a different model name has no effect.

---

## Positive Confirmations Summary

| Claim | Status |
|-------|--------|
| RRF integration point at search.py:445 | ✅ Verified (line 445-446) |
| `models.Message` has `.content` | ✅ Verified |
| `httpx` in dependencies | ✅ Verified (`>=0.27.0`) |
| `AppSettings` nested settings pattern | ✅ Verified (lines 1488-1504) |
| KG router prefix pattern | ✅ Verified |
| `subgraph()` accepts entity name | ✅ Verified |
| RW IE rerank contract | ✅ Verified |
| Hermes plugin `pre_llm_call` hook contract | ⚠️ Verified conceptually (outside repo) |

---

## Issues Found

| # | Severity | Issue | Verification |
|---|----------|-------|--------------|
| FA-01 | 🟠 Major | Reranker must run inside `_run_search()` closure (before message expunge) | `search.py:451-455` expunges after `_run_search` returns |
| FA-02 | 🟠 Major | `RerankerSettings` must be added to `SECTION_MAP` for TOML loading | `config.py:583-600` |
| FA-03 | 🟡 Minor | RW IE hardcodes model; configurable model has no effect | `rerank.rs:35-38` |

---

## Conclusion

**Forward audit PASSES with 3 fixes required.** SPEC-004's implementation plan is feasible against the actual codebase. The 3 issues (FA-01 through FA-03) must be incorporated into the synthesis document before TDD implementation begins.