---
title: "ADR-004: Temporal Decay for KG Retrieval"
description: "Decision to add automatic temporal decay to all KG queries with passive application"
category: architecture
tags:
  - temporal
  - decay
  - kg
  - memory
---

# ADR-004: Temporal Decay for KG Retrieval

**Status**: Proposed  
**Date**: 2026-09-20  
**Deciders**: Lucien (RapidWebs)  
**Consulted**: Steven Page  
**Informed**: Engineering team

## Context

Honcho's KG retrieves conclusions without temporal awareness. A conclusion from 6 months ago ranks equally with one from yesterday. This causes:

1. **Context pollution** — Stale facts dominate agent responses
2. **Reduced reliability** — Agents cite outdated information
3. **No learning curve** — Recent corrections have same weight as old errors

Research in episodic memory (McClelland et al., 2025) identifies temporal decay as essential for long-term agent systems.

## Decision

We will implement **automatic temporal decay** applied to all KG queries:

- Weight formula: `exp(-age_days * ln(2) / half_life_days)`
- Default half-life: 7 days
- Configurable via `honcho.json`
- Passive: applies to all queries automatically
- Opt-out: `?decay=false` parameter available

## Alternatives Considered

| Option | Description | Pros | Cons | Reason Rejected |
|--------|-------------|------|------|-----------------|
| **A** | Client-side decay | Simple, no server changes | Duplicated logic, inconsistent | Centralized is better |
| **B** | New decay tool | Explicit control | Requires all consumers to adapt | Passive is more useful |
| **C** | Hybrid (chosen) | Best of both | Slightly more complex | Chosen for flexibility |

## Consequences

### Positive
- All KG consumers benefit automatically
- No code changes required for existing tools
- Configurable per-deployment
- Matches cognitive science research

### Negative
- Changes result ordering (may break brittle tests)
- Requires tuning half-life per use case
- Adds ~1ms overhead per query (negligible)

### Neutral/Follow-ups
- May need dashboard for decay stats
- Could add bulk decay reset for migrations

## Implementation Notes

- Add to `src/kg/kg_query_tool.py`
- Add config to `src/schemas/configuration.py`
- Update ADRs/docs

## References

- SPEC-004: Temporal Decay Specification
- Episodic Memory Position (2025)
