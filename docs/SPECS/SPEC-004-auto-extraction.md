# SPEC-004 v1.0: Auto-Extraction on Message Ingestion

## Status: Draft v1.0

## 1. Executive Summary

Implement automatic Knowledge Graph entity/relationship extraction from messages as they are ingested into Honcho. Currently, KG extraction only runs on-demand via `POST /kg/auto-link`. This SPEC adds automatic extraction during message ingestion so the KG builds continuously without manual intervention.

## 2. Motivation

### Problem
- KG extraction currently only runs on-demand via `POST /kg/auto-link`
- Users must manually trigger extraction after conversations
- KG remains empty until manually populated, making query tools useless
- Deriver already processes messages for observations; extraction should piggyback on that pipeline

### Solution
Hook into the message ingestion pipeline (`create_messages` in `crud/message.py`) to automatically extract entities/relationships from new messages and persist them to the KG.

## 3. Design

### 3.1 Architecture

```
Message Ingestion (create_messages)
        │
        ▼
┌─────────────────────────────────────┐
│  Message Persistence (existing)     │
│  • Persist messages                 │
│  • Create MessageEmbedding rows     │
│  • Commit transaction               │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│  Auto-Extraction (NEW - async)      │
│  • Batch new messages               │
│  • Call LLM with extraction prompt  │
│  • Validate against KG schema       │
│  • Persist entities/relationships   │
└─────────────────────────────────────┘
        │
        ▼
    KG Populated Automatically
```

### 3.2 Integration Point

**Primary integration**: `create_messages()` in `src/crud/message.py`
- After message commit, spawn background extraction task
- Pass newly created messages to extraction pipeline
- Run asynchronously to not block message ingestion

### 3.3 Extraction Pipeline

```
New Messages → Batch by Workspace → LLM Extraction → Validate → Persist to KG
```

#### Batch Strategy
- Group messages by workspace (per workspace KG)
- Batch size: configurable (default 50 messages)
- Time window: flush after N seconds (default 30s)
- Deduplicate by workspace to avoid redundant LLM calls

#### LLM Extraction
- Use existing `KG_EXTRACTION_PROMPT` and `KG_EXTRACTION_SCHEMA`
- Call via `honcho_llm_call` with `json_object` mode
- Target: NVIDIA deepseek-v4-flash-0731 (fast, structured output)

#### Validation & Persistence
- Validate against `KG_EXTRACTION_SCHEMA`
- Validate entity/relationship types against controlled vocabularies
- Upsert entities (merge on name + type + workspace)
- Upsert relationships (source + target + type + workspace)

### 3.4 Configuration

Add to `config.toml`:
```toml
[extraction]
enabled = true
batch_size = 50
flush_interval_seconds = 30
max_concurrent_extractions = 2
# Optional: custom instructions per workspace
# [extraction.custom_instructions]
# "my-workspace" = "Focus on technical infrastructure entities"
```

### 3.5 Error Handling
- Never block message ingestion on extraction failures
- Log errors, continue ingestion
- Retry failed extractions with exponential backoff (max 3 retries)
- Dead letter queue for permanently failed extractions (admin review)

## 4. Implementation Plan

### Phase 1: Core Extraction Module (`src/kg/auto_extractor.py`)
- [ ] `AutoExtractor` class with batch management
- [ ] `extract_from_messages()` - main entry point
- [ ] LLM call with structured output
- [ ] Validation against schema
- [ ] Upsert logic for entities/relationships

### Phase 2: Integration with Message Pipeline
- [ ] Modify `create_messages()` in `crud/message.py`
- [ ] Post-commit hook to trigger extraction
- [ ] Background task management (asyncio)

### Phase 3: Configuration & API
- [ ] Add `extraction` section to `config.toml` / `config.py`
- [ ] Optional: Admin API to trigger/manual flush
- [ ] Metrics: extraction latency, success rate, queue depth

### Phase 4: Testing & Deployment
- [ ] Unit tests for extractor
- [ ] Integration test with message ingestion
- [ ] Deploy to infra, verify KG population

## 5. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| LLM latency blocks ingestion | Async/background, non-blocking |
| LLM costs | Batch messages, cache embeddings, limit concurrent |
| Extraction errors corrupt KG | Validation + upsert (idempotent), dead letter queue |
| Concurrent extractions | Per-workspace locking, max 2 concurrent |
| Schema drift | Structured output + validation |

## 6. Success Metrics

| Metric | Target |
|--------|--------|
| Extraction latency (per batch) | < 5s p95 |
| Extraction success rate | > 99% |
| KG coverage (entities/message) | > 0.5 entities/message |
| End-to-end latency (msg → KG) | < 60s p95 |

---

## 7. Implementation Notes for Developers

### Files to Create/Modify

**New Files:**
- `src/kg/auto_extractor.py` - Core extraction logic
- `src/kg/extraction_queue.py` - Batch queue management

**Modified Files:**
- `src/crud/message.py` - Hook in `create_messages()`
- `src/config.py` - Add `ExtractionConfig` settings
- `src/dependencies.py` - Provide `AutoExtractor` dependency
- `src/routers/extraction.py` (optional) - Admin API

### Key Integration Point

In `create_messages()` in `src/crud/message.py`, after `await db.commit()`:

```python
# After successful message commit
if settings.EXTRACTION_ENABLED:
    from src.kg.extraction_queue import get_extraction_queue
    queue = get_extraction_queue()
    await queue.enqueue(
        workspace_name=workspace_name,
        message_ids=[m.public_id for m in message_objects],
        session_name=session_name,
    )
```

The extractor runs as a background task, completely decoupled from the ingestion path.
```

Now let me implement this in the local repo.
<tool_call>
<function=write_file>
<parameter=content>
# SPEC-004 v1.0: Auto-Extraction on Message Ingestion

## Status: Draft v1.0

## 1. Executive Summary

Implement automatic Knowledge Graph entity/relationship extraction from messages as they are ingested into Honcho. Currently, KG extraction only runs on-demand via `POST /kg/auto-link`. This SPEC adds automatic extraction during message ingestion so the KG builds continuously without manual intervention.

## 2. Motivation

### Problem
- KG extraction currently only runs on-demand via `POST /kg/auto-link`
- Users must manually trigger extraction after conversations
- KG remains empty until manually populated, making query tools useless
- Deriver already processes messages for observations; extraction should piggyback on that pipeline

### Solution
Hook into the message ingestion pipeline (`create_messages` in `crud/message.py`) to automatically extract entities/relationships from new messages and persist them to the KG.

## 3. Design

### 3.1 Architecture

```
Message Ingestion (create_messages)
        │
        ▼
┌─────────────────────────────────────┐
│  Message Persistence (existing)     │
│  • Persist messages                 │
│  • Create MessageEmbedding rows     │
│  • Commit transaction               │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│  Auto-Extraction (NEW - async)      │
│  • Batch new messages               │
│  • Call LLM with extraction prompt  │
│  • Validate against KG schema       │
│  • Persist entities/relationships   │
└─────────────────────────────────────┘
        │
        ▼
    KG Populated Automatically
```

### 3.2 Integration Point

**Primary integration**: `create_messages()` in `src/crud/message.py`
- After message commit, spawn background extraction task
- Pass newly created messages to extraction pipeline
- Run asynchronously to not block message ingestion

### 3.3 Extraction Pipeline

```
New Messages → Batch by Workspace → LLM Extraction → Validate → Persist to KG
```

#### Batch Strategy
- Group messages by workspace (per workspace KG)
- Batch size: configurable (default 50 messages)
- Time window: flush after N seconds (default 30s)
- Deduplicate by workspace to avoid redundant LLM calls

#### LLM Extraction
- Use existing `KG_EXTRACTION_PROMPT` and `KG_EXTRACTION_SCHEMA`
- Call via `honcho_llm_call` with `json_object` mode
- Target: NVIDIA deepseek-v4-flash-0731 (fast, structured output)

#### Validation & Persistence
- Validate against `KG_EXTRACTION_SCHEMA`
- Validate entity/relationship types against controlled vocabularies
- Upsert entities (merge on name + type + workspace)
- Upsert relationships (source + target + type + workspace)

### 3.4 Configuration

Add to `config.toml`:
```toml
[extraction]
enabled = true
batch_size = 50
flush_interval_seconds = 30
max_concurrent_extractions = 2
# Optional: custom instructions per workspace
# [extraction.custom_instructions]
# "my-workspace" = "Focus on technical infrastructure entities"
```

### 3.5 Error Handling
- Never block message ingestion on extraction failures
- Log errors, continue ingestion
- Retry failed extractions with exponential backoff (max 3 retries)
- Dead letter queue for permanently failed extractions (admin review)

## 4. Implementation Plan

### Phase 1: Core Extraction Module (`src/kg/auto_extractor.py`)
- [ ] `AutoExtractor` class with batch management
- [ ] `extract_from_messages()` - main entry point
- [ ] LLM call with structured output
- [ ] Validation against schema
- [ ] Upsert logic for entities/relationships

### Phase 2: Integration with Message Pipeline
- [ ] Modify `create_messages()` in `crud/message.py`
- [ ] Post-commit hook to trigger extraction
- [ ] Background task management (asyncio)

### Phase 3: Configuration & API
- [ ] Add `extraction` section to `config.toml` / `config.py`
- [ ] Optional: Admin API to trigger/manual flush
- [ ] Metrics: extraction latency, success rate, queue depth

### Phase 4: Testing & Deployment
- [ ] Unit tests for extractor
- [ ] Integration test with message ingestion
- [ ] Deploy to infra, verify KG population

## 5. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| LLM latency blocks ingestion | Async/background, non-blocking |
| LLM costs | Batch messages, cache embeddings, limit concurrent |
| Extraction errors corrupt KG | Validation + upsert (idempotent), dead letter queue |
| Concurrent extractions | Per-workspace locking, max 2 concurrent |
| Schema drift | Structured output + validation |

## 6. Success Metrics

| Metric | Target |
|--------|--------|
| Extraction latency (per batch) | < 5s p95 |
| Extraction success rate | > 99% |
| KG coverage (entities/message) | > 0.5 entities/message |
| End-to-end latency (msg → KG) | < 60s p95 |

---

## 7. Implementation Notes for Developers

### Files to Create/Modify

**New Files:**
- `src/kg/auto_extractor.py` - Core extraction logic
- `src/kg/extraction_queue.py` - Batch queue management

**Modified Files:**
- `src/crud/message.py` - Hook in `create_messages()`
- `src/config.py` - Add `ExtractionConfig` settings
- `src/dependencies.py` - Provide `AutoExtractor` dependency
- `src/routers/extraction.py` (optional) - Admin API

### Key Integration Point

In `create_messages()` in `src/crud/message.py`, after `await db.commit()`:

```python
# After successful message commit
if settings.EXTRACTION_ENABLED:
    from src.kg.extraction_queue import get_extraction_queue
    queue = get_extraction_queue()
    await queue.enqueue(
        workspace_name=workspace_name,
        message_ids=[m.public_id for m in message_objects],
        session_name=session_name,
    )
```

The extractor runs as a background task, completely decoupled from the ingestion path.