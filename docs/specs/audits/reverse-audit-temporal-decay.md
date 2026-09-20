# Reverse Audit: Temporal Decay Implementation

**Date:** 2026-09-20  
**Audit Type:** Reverse (What's Missing?)  
**Auditor:** Lucien (Inline)  
**Mode:** MEDIUM

---

## Critical Gaps (Must Fix)

### 1. Session Context Not Wired 🔴
**Location:** `src/routers/sessions.py`

**Issue:** Temporal decay applied to KG queries but NOT to session context retrieval (`get_context` endpoint). This means the Dialectic agent gets decayed KG results but non-decayed session context.

**Fix:**
```python
# In src/routers/sessions.py, after line ~977
from src.utils.temporal_decay import get_decay_config, apply_decay
decay_config = get_decay_config()
if decay_config["enabled"] and representation:
    # Apply decay to representation conclusions
    representation = _apply_decay_to_representation(representation, decay_config)
```

**Priority:** P0 — Inconsistent behavior between KG and session context

---

### 2. Missing Integration Tests 🟠
**Issue:** Only unit tests exist for `temporal_decay.py`. No tests verify:
- End-to-end decay in KG query tool
- Decay in conclusion query endpoint
- Config loading from honcho.json

**Fix:**
```python
# tests/test_temporal_decay_integration.py
async def test_kg_query_applies_decay():
    """Verify KG query tool applies decay."""
    # Mock DB, call handle_kg_query
    # Assert results have _decay_weight applied

async def test_conclusion_query_applies_decay():
    """Verify conclusion query applies decay."""
    # Mock DB, call query_conclusions
    # Assert weighted sorting
```

**Priority:** P1 — Needed for regression prevention

---

## High Priority Gaps

### 3. No Opt-Out Mechanism 🟠
**Issue:** Spec claims `?decay=false` support but not implemented.

**Impact:** Users cannot bypass decay for specific queries.

**Fix:**
```python
# In src/routers/conclusions.py
decay_enabled: bool = Query(True, description="Whether to apply temporal decay")

# Then check: if decay_enabled and decay_config["enabled"]
```

**Priority:** P1 — Breaking spec promise

---

### 4. Documentation Incomplete 🟡
**Issue:** AGENTS.md updated but:
- No migration guide for existing deployments
- No config examples in README
- No troubleshooting section

**Fix:** Add to `docs/reports/temporal-decay-implementation-summary.md`:
- Migration steps
- Config examples
- Debugging tips

**Priority:** P2 — Affects user onboarding

---

## Medium Priority Gaps

### 5. No Monitoring/Telemetry 🟡
**Issue:** No metrics on:
- How many conclusions get decayed
- Average decay weight distribution
- Query performance with decay

**Fix:** Add to `src/telemetry/events.py`:
```python
class DecayAppliedEvent(BaseModel):
    workspace_id: str
    query_type: str  # "kg_query", "conclusion_search", etc.
    conclusions_count: int
    avg_decay_weight: float
```

**Priority:** P3 — Nice to have for production monitoring

---

### 6. Edge Case: Concurrent Updates 🟡
**Issue:** If conclusions are being written while decay is calculated, timestamps might be slightly off.

**Current behavior:** Uses `created_at` from DB — safe under concurrent writes.

**Status:** ✅ Already handled correctly

---

## Low Priority Gaps

### 7. No CLI Command for Decay Stats 🔵
**Issue:** No way to inspect decay weights without writing code.

**Future enhancement:**
```bash
honcho-cli decay stats --workspace myworkspace
```

**Priority:** P4 — Nice to have

---

## Code Quality Issues

### 8. Import Style Inconsistency 🟡
**Location:** `src/kg/kg_query_tool.py`

**Issue:** Deferred import inside function body:
```python
from src.utils.temporal_decay import get_decay_config, apply_decay
```

**Better:** Import at top of file with other imports.

**Priority:** P3 — Style issue

---

### 9. Error Handling Minimal 🟡
**Location:** `src/utils/temporal_decay.py`

**Issue:** No handling for malformed `created_at` timestamps beyond try/except.

**Current:** Silently uses `now` for malformed timestamps.

**Risk:** Low — already handled gracefully.

---

## Completeness Checklist

| Requirement | Status |
|-------------|--------|
| Core decay calculation | ✅ Complete |
| Configuration schema | ✅ Complete |
| Unit tests | ✅ Complete (10 tests) |
| KG query integration | ✅ Complete |
| Conclusion query integration | ✅ Complete |
| Session context integration | ❌ Missing |
| Opt-out parameter | ❌ Missing |
| Integration tests | ❌ Missing |
| Documentation | 🟡 Partial |
| Telemetry | ❌ Missing |

**Completion:** 6/10 (60%)

---

## Recommended Actions

1. **Immediate (P0):** Wire decay to session context
2. **This Sprint (P1):** Add opt-out parameter, integration tests
3. **Next Sprint (P2):** Complete documentation, add telemetry
4. **Future (P3-P4):** CLI commands, advanced monitoring

---

**Audit Complete.** 1 critical gap, 3 high priority, 5 medium/low. Core functionality solid, integration incomplete.
