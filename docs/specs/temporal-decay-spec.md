---
name: temporal-decay-spec
description: Spec for temporal decay feature in Honcho KG — automatic recency weighting for conclusions and entities
status: proposed
created: 2026-09-20
author: Lucien (RapidWebs)
related-adrs: [ADR-001]
---

# Spec: Temporal Decay for Honcho KG

## Context

Honcho's Knowledge Graph stores conclusions with timestamps, but retrieval is time-agnostic — a 6-month-old fact competes equally with yesterday's context. Research in episodic memory (McClelland et al., 2025) shows temporal decay is essential for long-term agent reliability.

**Problem:** No recency weighting in KG retrieval. Stale conclusions pollute agent context.

**Solution:** Exponential temporal decay applied automatically to all KG queries.

## Requirements

### R1: Decay Function
The system SHALL apply exponential temporal decay to retrieved conclusions:
```
weight = exp(-age_days * ln(2) / half_life_days)
```
Default half-life: 7 days (50% weight reduction per week)

#### Scenario: Fresh conclusion
- **GIVEN** conclusion created 1 hour ago
- **WHEN** query executes
- **THEN** weight ≈ 1.0 (no decay)

#### Scenario: Old conclusion
- **GIVEN** conclusion created 30 days ago
- **WHEN** query executes
- **THEN** weight ≈ 0.004 (effectively zero)

### R2: Configuration
The system SHALL support configuration via `~/.hermes/honcho.json`:
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

### R3: Passive Application
Decay SHALL be applied automatically to all KG queries:
- `kg_entity_search`
- `kg_traverse`
- `kg_subgraph`
- Session context injection (`get_context`)
- Dialectic agent queries

#### Scenario: Query with mixed-age results
- **GIVEN** 10 conclusions: 5 fresh, 5 old
- **WHEN** semantic search executes
- **THEN** fresh conclusions ranked higher by default

### R4: Opt-Out Support
Queries SHALL support `?decay=false` parameter to disable decay for specific use cases.

#### Scenario: User wants all historical context
- **GIVEN** user queries with `?decay=false`
- **WHEN** query executes
- **THEN** all conclusions returned with equal weight

## Non-Requirements

- Does NOT modify how conclusions are stored
- Does NOT require database schema changes
- Does NOT affect message retrieval (separate feature)
- Does NOT change existing API contracts

## Design Notes

### Architecture

```
Query Request
    ↓
[TemporalDecay Middleware]
    ↓
Apply decay weights to results
    ↓
Sort by (semantic_score * decay_weight)
    ↓
Return ranked results
```

### Integration Points

1. **KG Query Layer** (`src/kg/kg_query_tool.py`)
   - Apply decay after semantic search
   - Re-rank results by combined score

2. **Session Context** (`src/routers/sessions.py`)
   - Apply decay to `get_context` endpoint
   - Affects dialectic agent responses

3. **Conclusion Retrieval** (`src/crud/conclusion.py`)
   - Optional: Add decay column to DB for pre-computed weights

### Weight Formula

```python
import math
from datetime import datetime, timezone

def calculate_decay(age_days: float, half_life: float = 7.0) -> float:
    """Calculate temporal decay weight."""
    if half_life <= 0:
        return 1.0
    return math.exp(-age_days * math.log(2) / half_life)

def apply_decay(conclusions: list[dict], half_life: float = 7.0, min_weight: float = 0.01) -> list[dict]:
    """Apply temporal decay to list of conclusions."""
    now = datetime.now(timezone.utc)
    for c in conclusions:
        created = c.get("created_at")
        if created:
            age_seconds = (now - created).total_seconds()
            age_days = age_seconds / 86400
            c["_decay_weight"] = max(min_weight, calculate_decay(age_days, half_life))
    
    # Sort by semantic score * decay weight
    return sorted(conclusions, 
                  key=lambda x: x.get("score", 0) * x.get("_decay_weight", 1), 
                  reverse=True)
```

## Open Questions

1. Should decay apply to relationships/edges too?
2. How to handle conclusions with missing timestamps?
3. Should we add a `/_decay_stats` endpoint for monitoring?

## References

- Episodic Memory Position (arXiv:2502.06975): Temporal decay essential
- INWARD (NeurIPS 2025): Self-model with temporal awareness
- Honcho ADR-001: KG Overlay architecture
