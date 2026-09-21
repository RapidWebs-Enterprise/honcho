---
title: "ADR-009: Bidirectional Memory Architecture"
description: "Decision to implement two-way memory models (user ↔ agent) with automatic extraction and context injection"
category: architecture
tags:
  - honcho
  - memory
  - bidirectional
  - agent-self-model
---

# ADR-009: Bidirectional Memory Architecture

**Status**: Proposed  
**Date**: 2026-09-21  
**Deciders**: Lucien (RapidWebs)  
**Consulted**: Steven Page  
**Informed**: Engineering team

## Context

Honcho currently implements unidirectional memory:
- Agent models user (Theory of Mind plugin)
- User has no visibility into agent's self-model
- No feedback loop for agent self-improvement
- Agents are "black boxes"

**Current state:**
- `UserMentalState` class exists in epistemic plugin
- Automatic extraction runs on session end
- Context injected on session start

**Problem:** Users cannot see what agent knows about them, and agents cannot learn from their own mistakes persistently.

## Decision

We will implement **bidirectional memory** with:
1. **User Model** (existing): Preferences, goals, emotional state
2. **Agent Model** (new): Lessons learned, capabilities, mistakes
3. **Automatic extraction** of both models at session end
4. **Context injection** of both models at session start
5. **Cross-model inference** for adaptive behavior

**Decision:** Extend existing episodic consolidation pipeline to extract and store both user and agent models, inject both into session context.

## Alternatives Considered

| Option | Description | Pros | Cons | Reason Rejected |
|--------|-------------|------|------|-----------------|
| **A** | Bidirectional memory (chosen) | Mutual learning, adaptive | Slightly more storage | Chosen for completeness |
| **B** | User-only memory | Simpler | No agent self-improvement | Insufficient value |
| **C** | Explicit user feedback | Direct control | Friction, user burden | Poor UX |
| **D** | LLM-generated summaries | Rich context | Expensive, slow | Over-engineered |

## Consequences

### Positive
- Agents learn from corrections automatically
- Users can query what agent knows (via existing tools)
- Mutual adaptation improves over time
- No new tools required (minimal surface)
- Builds on existing ToM infrastructure

### Negative
- Double storage (user + agent models)
- More complex extraction logic
- Need to handle conflicting lessons
- Initial implementation effort

### Neutral/Follow-ups
- Monitor storage growth (user vs agent model size)
- Consider aggregation of similar lessons
- Evaluate need for lesson expiration

## Implementation Notes

### File Structure
```
src/
├── memory/
│   ├── user_model.py      # Existing: UserMentalState
│   ├── agent_model.py     # NEW: AgentSelfModel
│   └── bidirectional.py   # NEW: Cross-model inference
├── workers/
│   └── consolidation.py   # EXTEND: Extract both models
└── routers/
    └── episodes.py        # EXTEND: Add agent endpoints
```

### Database Schema
```sql
-- Existing: episodes table
CREATE TABLE episodes (...);

-- NEW: agent_models table
CREATE TABLE agent_models (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    workspace_name TEXT NOT NULL,
    lessons JSONB DEFAULT '[]',
    capabilities JSONB DEFAULT '{}',
    mistakes JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);

-- Link to episodes via session_id
CREATE INDEX idx_agent_models_session ON agent_models(session_id);
```

### API Endpoints
```
GET    /v3/workspaces/{w}/agents/{id}/model     # View agent model
POST   /v3/workspaces/{w}/agents/{id}/feedback  # User provides feedback
GET    /v3/workspaces/{w}/episodes              # Existing (now includes agent lessons)
```

## References

- Spec: spec-010-bidirectional-memory.md
- Existing: spec-006-theory-of-mind.md (User Model)
- Existing: spec-009-episodic-consolidation.md (Worker pattern)
- Honcho AGENTS.md: Message processing pipeline
