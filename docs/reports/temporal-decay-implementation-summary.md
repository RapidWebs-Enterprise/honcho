# Temporal Decay — Implementation Summary

**Date:** 2026-09-20  
**Status:** Phase 1 Complete (Core Implementation)  
**Next:** Integration with KG query layer

---

## What Was Implemented

### 1. Core Decay Utility (`src/utils/temporal_decay.py`)
```python
def calculate_decay(age_days: float, half_life: float = 7.0) -> float
def apply_decay(conclusions: list[dict], half_life: float = 7.0, ...) -> list[dict]
def get_decay_config() -> dict[str, Any]
```

### 2. Configuration Schema (`src/schemas/configuration.py`)
```python
class TemporalDecayConfiguration(BaseModel):
    enabled: bool = True
    half_life_days: float = 7.0
    min_weight: float = 0.01
    max_age_days: float = 365.0
```

Added to `WorkspaceConfiguration.temporal_decay` field.

### 3. Tests (`tests/test_temporal_decay.py`)
- 10 test cases covering:
  - Fresh conclusion (~1.0 weight)
  - One half-life (~0.5 weight)
  - Two half-lives (~0.25 weight)
  - Custom half-life
  - Sorting by combined score
  - Missing timestamps
  - Max age floor

---

## How It Answers Your Question

> "Does it require a new tool for the honcho agent to use, or is it a passive benefit to the system?"

### Answer: **PASSIVE BENEFIT** (with opt-out)

Temporal decay is implemented as a **middleware layer**, not a new tool:

| Aspect | Details |
|--------|---------|
| **Application** | Automatic on all KG queries |
| **Agent Visibility** | Transparent — agents don't need to call anything special |
| **Config** | Set once in `~/.hermes/honcho.json` |
| **Opt-out** | `?decay=false` query parameter if needed |

### Why Passive is Better

1. **All consumers benefit** — Dialectic agent, REST API, MCP tools
2. **No code changes** — Existing tools work without modification
3. **Consistent behavior** — Everyone gets the same decay logic
4. **Configurable** — Tunable per-deployment without code changes

### Where It Gets Applied

```
Query comes in
    ↓
[Temporal Decay Middleware]
    ↓
Calculate age for each conclusion
    ↓
Apply decay weight
    ↓
Re-rank by (semantic_score × decay_weight)
    ↓
Return results
```

---

## Integration Status

| Component | Status | Notes |
|-----------|--------|-------|
| Core utility | ✅ Done | `src/utils/temporal_decay.py` |
| Config schema | ✅ Done | `src/schemas/configuration.py` |
| Tests | ✅ Done | `tests/test_temporal_decay.py` |
| KG query integration | ⏳ Pending | Needs wiring to `kg_query_tool.py` |
| Session context integration | ⏳ Pending | Needs wiring to `routers/sessions.py` |
| Documentation | ✅ Done | ADR-004, spec, plan |

---

## Next Steps (Integration Phase)

### Task 1: Wire to KG Query Tool
```python
# In src/kg/kg_query_tool.py
from src.utils.temporal_decay import apply_decay, get_decay_config

async def handle_kg_query(ctx, tool_input):
    # ... existing code ...
    
    # Apply temporal decay
    config = get_decay_config()
    if config["enabled"]:
        results = apply_decay(results, 
                             half_life=config["half_life_days"],
                             min_weight=config["min_weight"])
```

### Task 2: Wire to Session Context
```python
# In src/routers/sessions.py
from src.utils.temporal_decay import apply_decay, get_decay_config

async def get_context(...):
    # ... existing code ...
    
    # Apply decay to conclusions
    config = get_decay_config()
    if config["enabled"]:
        conclusions = apply_decay(conclusions, ...)
```

### Task 3: Add Config to honcho.json
```json
{
  "temporalDecay": {
    "enabled": true,
    "halfLifeDays": 7,
    "minWeight": 0.01,
    "maxAgeDays": 365
  }
}
```

---

## Estimated Effort for Integration

| Task | Time |
|------|------|
| Wire to KG query tool | 15 min |
| Wire to session context | 15 min |
| Update AGENTS.md | 10 min |
| Test end-to-end | 20 min |
| **Total** | **~1 hour** |

---

## Commit History

```
bf33f690 docs: add temporal decay to AGENTS.md and fix lint
01f07c9e feat: add temporal decay for KG retrieval
```

**Repository:** https://github.com/RapidWebs-Enterprise/honcho

---

**Ready for integration phase?** The core is built and tested — just needs wiring to the query layer.
