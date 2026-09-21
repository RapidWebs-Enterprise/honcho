# Phase 4 Options: Post-Implementation Enhancement

**Date:** 2026-09-21  
**Status:** Ready for Selection

---

## Context

We've completed:
- ✅ Confidence-Gated Retrieval (Phase 1)
- ✅ Causal Reasoning Graph (Phase 2)
- ✅ Episodic Consolidation (Phase 3)
- ✅ Deployment to infra

---

## Phase 4 Candidates

Based on research and audit findings, here are the most impactful next features:

### Option A: Spreading Activation Engine (SYNAPSE-inspired)

**What:** Implement spreading activation algorithm for memory retrieval

**Why:** SYNAPSE paper shows +23% improvement on multi-hop reasoning vs vector-only search

**Core Concept:**
- Memory graph where relevance emerges from propagation, not just similarity
- Energy injected at query anchor points
- Spreads through temporal/causal/semantic edges
- Lateral inhibition suppresses irrelevant nodes
- Fades over time (temporal decay)

**Implementation:**
```python
class SpreadingActivation:
    def spread(self, anchors, max_hops=3):
        # Inject energy at anchor nodes
        # Propagate through graph edges
        # Apply lateral inhibition
        # Return top-K activated nodes
```

**Effort:** 5-7 days  
**Impact:** High (state-of-the-art retrieval)  
**Complexity:** Medium

---

### Option B: Multi-Graph Architecture (MAGMA-inspired)

**What:** Separate graphs for semantic, temporal, causal, entity relationships

**Why:** MAGMA shows consistent outperformance on LoCoMo/LongMemEval

**Core Concept:**
```python
class MultiGraphMemory:
    semantic_graph: KGGraph      # Conceptual similarity
    temporal_graph: KGGraph      # Chronological ordering
    causal_graph: KGGraph        # Cause-effect (already built)
    entity_graph: KGGraph        # Object permanence
```

**Query Routing:**
- "When did X happen?" → temporal_graph
- "Why did X happen?" → causal_graph
- "What's related to X?" → semantic_graph
- "Show me X's history" → entity_graph

**Effort:** 7-10 days  
**Impact:** High (benchmark-leading)  
**Complexity:** High

---

### Option C: Bidirectional Memory (User ↔ Agent)

**What:** Agents remember users AND users remember agent behaviors

**Why:** Current system only models user → agent. Bidirectional creates reciprocity.

**Core Concept:**
- User model (what we have): User preferences, goals, emotions
- Agent model (new): Agent capabilities, mistakes, learning
- Cross-model inference: "Given user prefers X, how should agent adapt?"

**Implementation:**
```python
class BidirectionalMemory:
    user_model: UserMentalState    # Existing ToM
    agent_model: AgentSelfModel    # New: agent's self-knowledge
    interaction_history: list[Dict]  # Joint state
    
    def get_adaptation(self):
        # Recommend how agent should adapt to user
        pass
```

**Effort:** 4-6 days  
**Impact:** Medium-High (personalization)  
**Complexity:** Medium

---

### Option D: Memory Consolidation with Forgetting

**What:** Sleep-time consolidation + intentional forgetting

**Why:** Human memory consolidates during sleep and forgets irrelevant info

**Core Concept:**
- **Consolidation:** Periodic reorganization of memories
  - Move recent → stable storage
  - Extract patterns, create summaries
  - Link related concepts
- **Forgetting:** Intentional decay of low-value memories
  - Temporal decay (already have)
  - Usage-based decay (never accessed → forget)
  - Interference-based decay (overlapped by new info)

**Implementation:**
```python
class ConsolidationEngine:
    def consolidate(self):
        # Batch process recent memories
        # Extract higher-level abstractions
        # Create cross-memory links
        
    def forget(self):
        # Identify low-value memories
        # Apply forgetting curves
        # Archive or delete
```

**Effort:** 5-8 days  
**Impact:** High (long-term efficiency)  
**Complexity:** High

---

### Option E: Collaborative Memory (Multi-Agent)

**What:** Agents share and merge memories

**Why:** Fleet architecture (Lucien + Dagoth) needs shared context

**Core Concept:**
- Agent A learns about deployment → shares with Agent B
- Conflict resolution when agents disagree
- Consensus building on facts
- Privacy-aware (some memories user-only)

**Implementation:**
```python
class CollaborativeMemory:
    def share_memory(self, source_agent, memory):
        # Broadcast to other agents
        
    def merge_memories(self, memories):
        # Resolve conflicts
        # Build consensus
        
    def query_shared(self, query):
        # Search across all agents
```

**Effort:** 6-10 days  
**Impact:** High (fleet operations)  
**Complexity:** High

---

## Recommendation

| Priority | Feature | Effort | Impact | Rationale |
|----------|---------|--------|--------|-----------|
| **1** | A: Spreading Activation | 5-7d | High | Directly improves retrieval quality |
| **2** | C: Bidirectional Memory | 4-6d | Medium-High | Quick win, personalization |
| **3** | D: Consolidation | 5-8d | High | Long-term efficiency |
| **4** | B: Multi-Graph | 7-10d | High | SOTA performance |
| **5** | E: Collaborative | 6-10d | High | Fleet operations |

---

## Quick Start Recommendation

**Start with Option C (Bidirectional Memory):**
- Fastest to implement (4-6 days)
- Immediate personalization benefits
- Builds on existing ToM infrastructure
- Sets foundation for future features

**Then Option A (Spreading Activation):**
- Most impactful retrieval improvement
- Can use existing graph infrastructure
- Proven by SYNAPSE research

---

## Questions for You

1. **Which direction interests you most?**
   - Better retrieval (A, B)
   - Better personalization (C)
   - Better long-term efficiency (D)
   - Better fleet ops (E)

2. **What's your priority?**
   - Speed to value (pick C)
   - Maximum impact (pick A or B)
   - Long-term vision (pick D or E)

3. **Any specific use case driving this?**
   - Deployment troubleshooting?
   - Cross-session continuity?
   - Multi-agent coordination?

---

**Ready to spec out your choice!**
