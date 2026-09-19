# Reverse Audit — SPEC-004 Cross-Encoder Reranking & Context Injection

**Date:** 2026-08-20
**Auditor:** Lucien (inline, plan-and-audit MEDIUM mode)
**Reference:** `docs/SPECS/SPEC-004-cross-encoder-reranking-context-injection.md`

---

## Audit Scope

Verifying SPEC-004 against the actual Honcho fork codebase:

| File | Component |
|------|-----------|
| `src/utils/search.py` | Hybrid search + RRF fusion |
| `src/config.py` | Settings (nested model pattern) |
| `src/embedding_client.py` | HTTP client pattern for external services |
| `src/routers/kg.py` | KG router (context-dump insertion) |
| `src/kg/graph.py` | Graph traversal functions |
| `src/kg/peer_linker.py` | Peer-entity linking |
| `src/webhooks/webhook_delivery.py` | `httpx` usage pattern |
| `RW_InferenceEngine/src/routes/rerank.rs` | Reranker endpoint contract |
| `pyproject.toml` | `httpx` dependency |

---

## Findings

### 🔴 CRITICAL

| # | Finding | Impact | Resolution |
|---|---------|--------|------------|
| RA-01 | **SPEC-004 §3.3 padded reranker scores incorrectly.** The SPEC code returns `scores + [0.0] * (len(documents) - top_k)`. But in `search()` we pass `top_k=rerank_limit` which is already `min(settings.RERANKER.TOP_K, len(fused))`. When `top_k >= len(documents)`, the padding adds ZERO-length padding — fine. But when `rerank_limit < len(fused)` (cap active), the spec appends zeros for un-reranked docs — this **dilutes the ranking**: un-reranked docs would get 0.0 score and could outrank poorly-scored reranked docs. **Fix:** Don't pad with zeros; instead assign un-reranked docs a score equal to their original RRF position (descending), OR keep them at the tail. | Wrong ranking when TOP_K cap active | Drop padding; keep un-reranked docs in RRF order at the tail |
| RA-02 | **SPEC-004 §3.3 passes `model` param but RW IE ignores it.** The rerank route (`rerank.rs`) hardcodes response `model: "ms-marco-MiniLM-L-6-v2"` and `state.run_rerank()` uses that model. Sending a different `model` in request body is silently ignored. | False sense of model configurability | Keep configurable model for future proofing, but document it's currently fixed |

### 🟠 MAJOR

| # | Finding | Impact | Resolution |
|---|---------|--------|------------|
| RA-03 | **No timeout connection handling in RerankerClient.** SPEC uses `httpx.AsyncClient(timeout=30.0)` (good) but never sets `httpx.Limits` — default max_connections is 100. For a search path that fires on every request, should use a small pool (e.g. `httpx.Limits(max_connections=10)`). | Connection pool exhaustion under load | Add `httpx.Limits(max_connections=10)` |
| RA-04 | **`search.py` returns `models.Message` objects, but SPEC-004 §3.3 assumes `msg.content`.** Messages have `.content` field. This is correct. OK. | None | — |
| RA-05 | **`RerankerSettings` placed in `AppSettings.EMBEDDING` - but SPEC places under `AppSettings.RERANKER`.** The config pattern uses nested `Settings` models (`DB`, `AUTH`, `SENTRY`, etc.) registered on `AppSettings`. My SPEC §3.4 uses `settings.RERANKER` which requires adding a `RERANKER: RerankerSettings` field to `AppSettings` + a `[reranker]` section mapping in `TomlConfigSettingsSource.SECTION_MAP`. ✅ This is correct. But **must register in SECTION_MAP** (`"RERANKER": "reranker"`) or TOML `[reranker]` won't load. | Config break | Register in SECTION_MAP |
| RA-06 | **context-dump endpoint reuses `kg_subgraph` which uses entity IDS, not names.** SPEC-004 §3.5 calls `kg_peer_entities` then feeds results to `kg_subgraph(entity=entity["name"])`. But `subgraph()` resolves `KGEntity.name == entity_name` (works), whereas `peer-entities` returns names. ✅ Correct. However `subgraph()` returns relationships with `source`/`target` as **entity IDs**, NOT names — the Hermes plugin formatter in SPEC expects names. | Broken plugin output | Format relationship source/target as names in the endpoint, or accept IDs |
| RA-07 | **kg_subgraph doesn't filter dormant/low-confidence entities.** `subgraph()` has no confidence/dormant filter, so context-dump could return stale entities. | Noise in injection | Add `min_confidence` param to subgraph or filter in endpoint |
| RA-08 | **No caching on KG context-dump.** Hermes plugin calls every N turns; each call does N+1 DB queries (1 peer entities + N subgraphs). Could add `cachetools.TTLCache`. | Latency/cost | Optional `functools.lru_cache` with TTL or rely on Postgres query caching |

### 🟡 MINOR

| # | Finding | Impact | Resolution |
|---|---------|--------|------------|
| RA-09 | **SPEC-004 §3.6 Hermes plugin references `pre_llm_call(payload)` but Hermes hooks use `**payload`.** Correct in plugin code. ✅ | None | — |
| RA-10 | **`httpx` is already in pyproject.toml** (`httpx>=0.27.0`). No new dependency. | None | — |
| RA-11 | **Finding: no unit-test strategy in SPEC for `rerank_client.py`.** | None | Added in synthesis |
| RA-12 | **SPEC-004 §3.5 uses `json.dumps(dump_data)//4` for token estimate — should be `len(text) //4`** (chars). `json.dumps` includes formatting; `len` is closer. | Minor over/under-estimate | Use `len(text)//4` |
| RA-13 | **context-dump has no `before/after` time bounds.** Entities from months ago get injected same-weight as recent. | Stale context | Add optional `max_age_days` param |

---

## Positive Confirmations (Verified, Not Just Claimed)

| # | Component | Confirmed |
|---|-----------|-----------|
| ✅ | `search()` RRF fusion at line 445-446 (before return) | Integration point valid |
| ✅ | `models.Message` has `.content` field | Reranker text extraction works |
| ✅ | `httpx` in deps (`>=0.27.0`) | No new dependency |
| ✅ | RW IE `/v1/rerank` returns `{"scores": [...]}` | Contract matches SPEC |
| ✅ | `embedded.` pattern for `rw_inference` transport | Reuse for reranker |
| ✅ | `subgraph()` accepts entity NAME | Works for context-dump |
| ✅ | `peer-entities` returns entity names | Feeds subgraph correctly |
| ✅ | `AppSettings` nested-settings pattern + SECTION_MAP | RerankerSettings integrates cleanly |

---

## Gap Score

| Severity | Count |
|----------|-------|
| 🔴 Critical | 2 |
| 🟠 Major | 5 |
| 🟡 Minor | 4 |
| **Total** | **11** |

## Recommendation

**Proceed to synthesis.** Findings RA-01 (score padding), RA-02 (model config), RA-06 (name vs ID), RA-12 (token estimate) must be incorporated into the final implementation. The rest are optional hardening.

**Updated Effort Estimate: ~6 hours** (was 5h) — +1h for cache, name-vs-ID formatting, and unit tests.