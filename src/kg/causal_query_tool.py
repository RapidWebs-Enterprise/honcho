"""Causal query tool for the Dialectic agent."""

from typing import Any

from src.dependencies import tracked_db
from src.kg.causal_traversal import get_causal_chain, find_root_causes, find_downstream_effects

CAUSAL_QUERY_TOOL_DEFINITION: dict[str, Any] = {
    "name": "kg_causal_query",
    "description": (
        "Query causal relationships in the Knowledge Graph. "
        "Use for 'why' and 'what happened' questions. "
        "Examples: 'Why did the service crash?', 'What happened after the database filled?'"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "entity": {
                "type": "string",
                "description": "The entity to query causal relationships for",
            },
            "direction": {
                "type": "string",
                "enum": ["outgoing", "incoming", "both"],
                "description": "'outgoing' for causes, 'incoming' for effects, 'both' for all",
                "default": "both",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum traversal depth (1-5)",
                "default": 3,
                "minimum": 1,
                "maximum": 5,
            },
        },
        "required": ["entity"],
    },
}


async def handle_causal_query(
    ctx: Any,
    tool_input: dict[str, Any],
) -> str:
    """Execute a causal query and return formatted results."""
    workspace_name = ctx.workspace_name
    entity = tool_input.get("entity", "")
    direction = tool_input.get("direction", "both")
    max_depth = min(tool_input.get("max_depth", 3), 5)

    if not entity:
        return "Error: 'entity' is required."

    async with tracked_db("kg_causal_query", read_only=True) as db:
        results = await get_causal_chain(
            db, workspace_name, entity,
            direction=direction,
            max_depth=max_depth,
        )

    if not results:
        return f"No causal relationships found for '{entity}'."

    return _format_causal_results(results, entity, direction)


def _format_causal_results(results: list[dict], root: str, direction: str) -> str:
    """Format causal query results for LLM consumption."""
    lines = [f"Causal relationships for '{root}' (direction: {direction}):"]

    for r in results:
        depth = r.get("depth", "?")
        conf = r.get("confidence", "?")
        evidence = r.get("evidence", "")
        rel_type = r.get("type", "?")

        if rel_type == "causal_outgoing":
            lines.append(f"  [{depth}] {r.get('cause', '?')} --(caused, {conf:.2f})--> {r.get('effect', '?')}")
        else:
            lines.append(f"  [{depth}] {r.get('from', '?')} --(caused, {conf:.2f})--> {r.get('effect', '?')}")

        if evidence:
            lines.append(f"      Evidence: {evidence[:100]}...")

    lines.append(f"\nTotal causal relationships: {len(results)}")
    return "\n".join(lines)


CAUSAL_ROOT_CAUSES_TOOL = {
    "name": "kg_find_root_causes",
    "description": (
        "Find root causes for an entity. "
        "Use when asked 'why did X happen?' or 'what caused X?'"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "entity": {"type": "string", "description": "The effect entity"},
            "max_depth": {"type": "integer", "default": 3, "minimum": 1, "maximum": 5},
        },
        "required": ["entity"],
    },
}


async def handle_root_causes(ctx: Any, tool_input: dict[str, Any]) -> str:
    """Find root causes for an entity."""
    workspace_name = ctx.workspace_name
    entity = tool_input.get("entity", "")
    max_depth = min(tool_input.get("max_depth", 3), 5)

    if not entity:
        return "Error: 'entity' is required."

    async with tracked_db("kg_root_causes", read_only=True) as db:
        results = await find_root_causes(db, workspace_name, entity, max_depth)

    if not results:
        return f"No root causes found for '{entity}'."

    lines = [f"Root causes for '{entity}':"]
    for r in results:
        lines.append(f"  • {r.get('from', '?')} → {entity} (confidence: {r.get('confidence', 0):.2f})")

    return "\n".join(lines) if lines else "No root causes found."


CAUSAL_DOWNSTREAM_TOOL = {
    "name": "kg_find_downstream_effects",
    "description": (
        "Find downstream effects of an entity. "
        "Use when asked 'what happened after X?' or 'what were the effects of X?'"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "entity": {"type": "string", "description": "The cause entity"},
            "max_depth": {"type": "integer", "default": 3, "minimum": 1, "maximum": 5},
        },
        "required": ["entity"],
    },
}


async def handle_downstream_effects(ctx: Any, tool_input: dict[str, Any]) -> str:
    """Find downstream effects of an entity."""
    workspace_name = ctx.workspace_name
    entity = tool_input.get("entity", "")
    max_depth = min(tool_input.get("max_depth", 3), 5)

    if not entity:
        return "Error: 'entity' is required."

    async with tracked_db("kg_downstream", read_only=True) as db:
        results = await find_downstream_effects(db, workspace_name, entity, max_depth)

    if not results:
        return f"No downstream effects found for '{entity}'."

    lines = [f"Downstream effects of '{entity}':"]
    for r in results:
        lines.append(f"  • {entity} → {r.get('effect', '?')} (confidence: {r.get('confidence', 0):.2f})")

    return "\n".join(lines) if lines else "No downstream effects found."
