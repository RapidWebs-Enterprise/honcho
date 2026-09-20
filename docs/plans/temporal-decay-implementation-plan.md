---
title: "Implementation Plan: Temporal Decay v1.0"
description: "Structured plan for adding temporal decay to Honcho KG"
category: planning
tags:
  - implementation
  - temporal
  - kg
---

# Implementation Plan: Temporal Decay v1.0

## Overview

- **Feature**: Temporal Decay for KG Retrieval
- **Objective**: Apply automatic recency weighting to all KG queries
- **Success Criteria**: Decay applied to 100% of queries, configurable via honcho.json
- **Timeline**: 2026-09-20 to 2026-09-21
- **Owner**: Lucien (RapidWebs)
- **Status**: Not started

## Scope

### In Scope
- Temporal decay utility functions
- Integration with KG query tools
- Configuration in honcho.json
- Tests for decay calculation
- Documentation updates

### Out of Scope
- Message-level decay (future)
- Relationship edge decay (future)
- Dashboard/stats endpoint (future)
- Legacy data migration

## Phases

### Phase 1: Core Implementation
**Duration**: 2 hours
**Start**: 2026-09-20
**Target**: 2026-09-20

- [ ] 1.1 Create `src/utils/temporal_decay.py` with decay functions
- [ ] 1.2 Add config schema to `src/schemas/configuration.py`
- [ ] 1.3 Integrate with `src/kg/kg_query_tool.py`
- [ ] 1.4 Integrate with session context retrieval
- [ ] 1.5 Add unit tests for decay calculation

**Deliverable**: Working decay with tests  
**Risk**: Low — isolated utility

### Phase 2: Configuration & Integration
**Duration**: 1 hour
**Start**: 2026-09-20
**Target**: 2026-09-20

- [ ] 2.1 Add `temporalDecay` section to honcho.json schema
- [ ] 2.2 Wire config to KG query layer
- [ ] 2.3 Add opt-out parameter (`?decay=false`)
- [ ] 2.4 Update ADR-001 to reference temporal decay

**Deliverable**: Configurable decay system  
**Risk**: Medium — config wiring

### Phase 3: Testing & Validation
**Duration**: 1 hour
**Start**: 2026-09-20
**Target**: 2026-09-20

- [ ] 3.1 Run existing test suite (ensure no regressions)
- [ ] 3.2 Add integration tests for decay in queries
- [ ] 3.3 Verify config loading
- [ ] 3.4 Test opt-out functionality

**Deliverable**: All tests passing  
**Risk**: Low — mostly verification

### Phase 4: Documentation
**Duration**: 30 min
**Start**: 2026-09-20
**Target**: 2026-09-20

- [ ] 4.1 Update AGENTS.md with temporal decay section
- [ ] 4.2 Add usage examples to README
- [ ] 4.3 Document config options
- [ ] 4.4 Create migration notes if needed

**Deliverable**: Complete documentation  
**Risk**: Low

## Dependencies

| Dependency | Owner | Status |
|------------|-------|--------|
| Honcho fork access | Lucien | ✅ Ready |
| KG query code understanding | Lucien | ✅ Done |
| Config schema knowledge | Lucien | ✅ Done |

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Breaks existing tests | Medium | High | Run full suite, fix as needed |
| Performance regression | Low | Medium | Profile decay calculation |
| Config conflicts | Low | Low | Validate on startup |

## Success Metrics

| Metric | Target |
|--------|--------|
| Test coverage | >90% |
| Query overhead | <5ms |
| Config validation | 100% |
| Documentation completeness | 100% |

## Files to Modify

1. `src/utils/temporal_decay.py` — NEW
2. `src/kg/kg_query_tool.py` — MODIFY
3. `src/schemas/configuration.py` — MODIFY
4. `docs/ADRs/ADR-004-temporal-decay.md` — NEW
5. `docs/specs/temporal-decay-spec.md` — NEW
6. `AGENTS.md` — MODIFY
7. `README.md` — MODIFY
8. `tests/test_temporal_decay.py` — NEW

## References

- Spec: docs/specs/temporal-decay-spec.md
- ADR: docs/ADRs/ADR-004-temporal-decay.md
- Related: ADR-001 (KG Overlay)
