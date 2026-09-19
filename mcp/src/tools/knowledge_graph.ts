import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ToolContext } from "../types.js";
import { textResult, errorResult } from "../types.js";

/**
 * Knowledge Graph tools for the Honcho fork's KG overlay.
 *
 * These wrap the server's /v3/workspaces/{w}/kg/* REST endpoints (routers/kg.py),
 * which are fork-specific and NOT part of the standard @honcho-ai/sdk, so we call
 * them via raw fetch to config.baseUrl with WS ID + bearer auth.
 */

type KGContext = ToolContext & { honcho: never };

function kgUrl(ctx: ToolContext, path: string): string {
  const base = (ctx.config.baseUrl || "").replace(/\/$/, "");
  return `${base}/v3/workspaces/${encodeURIComponent(
    ctx.config.workspaceId,
  )}/kg${path}`;
}

async function kgGet(
  ctx: ToolContext,
  path: string,
  params: Record<string, unknown>,
): Promise<Record<string, unknown> | unknown[]> {
  const url = kgUrl(ctx, path);
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") {
      qs.set(k, String(v));
    }
  }
  const full = `${url}?${qs.toString()}`;
  const res = await fetch(full, {
    headers: {
      Accept: "application/json",
      ...(ctx.config.apiKey ? { Authorization: `Bearer ${ctx.config.apiKey}` } : {}),
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`KG endpoint ${path} → HTTP ${res.status}: ${body.slice(0, 300)}`);
  }
  return res.json();
}

export function register(server: McpServer, ctx: ToolContext) {
  // ── kg_entity_search ──────────────────────────────────────────────────
  server.registerTool(
    "kg_entity_search",
    {
      description: [
        "Search knowledge graph entities by name or alias (substring/ILIKE match).",
        "Use to discover what entities exist in the knowledge graph before traversing.",
        "Returns entity name, type, aliases, confidence, mention count.",
        "Note: shared field name is `q` (endpoint contract).",
      ].join("\n"),
      inputSchema: {
        q: z.string().min(1).describe("Entity name or alias substring to search (min 1 char)."),
        entity_type: z
          .enum([
            "person", "agent", "service", "tool", "project", "concept",
            "location", "organization", "event", "database", "server",
            "system", "technology", "framework", "platform", "library",
            "protocol", "network", "file", "config", "data", "api",
            "command", "unknown",
          ])
          .optional()
          .describe("Filter by entity type."),
        min_confidence: z.number().min(0).max(1).optional().describe("Minimum confidence (0-1). Default 0."),
        limit: z.number().int().min(1).max(100).optional().describe("Max results. Default 20."),
        include_dormant: z.boolean().optional().describe("Include dormant (stale) entities. Default false."),
      },
    },
    async ({ q, entity_type, min_confidence, limit, include_dormant }) => {
      try {
        const data = await kgGet(ctx, "/entities", {
          q,
          entity_type,
          min_confidence,
          limit,
          include_dormant,
        });
        return textResult(data);
      } catch (e) {
        return errorResult(`kg_entity_search failed: ${e instanceof Error ? e.message : String(e)}`);
      }
    },
  );

  // ── kg_peer_entities ─────────────────────────────────────────────────
  server.registerTool(
    "kg_peer_entities",
    {
      description: [
        "Get entities linked to a specific peer in the knowledge graph.",
        "Use to see what entities a peer is associated with across sessions.",
        "Returns entity name, type, relationship, confidence.",
      ].join("\n"),
      inputSchema: {
        peer_name: z.string().min(1).describe("Peer name (e.g. 'sysop', 'hermes')."),
        relationship_types: z.string().optional().describe("Comma-separated relationship type filter (e.g. 'manages,operates')."),
        limit: z.number().int().min(1).max(200).optional().describe("Max results. Default 50."),
      },
    },
    async ({ peer_name, relationship_types, limit }) => {
      try {
        const data = await kgGet(ctx, "/peer-entities", {
          peer_name,
          relationship_types,
          limit,
        });
        return textResult(data);
      } catch (e) {
        return errorResult(`kg_peer_entities failed: ${e instanceof Error ? e.message : String(e)}`);
      }
    },
  );

  // ── kg_traverse ──────────────────────────────────────────────────────
  server.registerTool(
    "kg_traverse",
    {
      description: [
        "BFS traversal through the knowledge graph from a starting entity.",
        "Use for multi-hop graph reasoning: find what an entity connects to, and at what depth.",
        "Depth clamped to <=6.",
      ].join("\n"),
      inputSchema: {
        entity: z.string().min(1).describe("Starting entity name."),
        max_depth: z.number().int().min(1).max(6).optional().describe("Max traversal depth. Default 2, clamp <=6."),
        relationship_types: z.string().optional().describe("Comma-separated relationship type filter."),
        entity_types: z.string().optional().describe("Comma-separated entity type filter."),
        min_confidence: z.number().min(0).max(1).optional().describe("Minimum confidence. Default 0."),
        limit: z.number().int().min(1).max(200).optional().describe("Max results. Default 100."),
      },
    },
    async ({ entity, max_depth, relationship_types, entity_types, min_confidence, limit }) => {
      try {
        const data = await kgGet(ctx, "/traverse", {
          entity,
          max_depth: Math.min(max_depth ?? 2, 6),
          relationship_types,
          entity_types,
          min_confidence,
          limit,
        });
        return textResult(data);
      } catch (e) {
        return errorResult(`kg_traverse failed: ${e instanceof Error ? e.message : String(e)}`);
      }
    },
  );

  // ── kg_subgraph ──────────────────────────────────────────────────────
  server.registerTool(
    "kg_subgraph",
    {
      description: [
        "Extract the neighborhood subgraph around a given entity.",
        "Use to pull the graph neighborhood around an entity for context injection.",
        "Depth clamped to <=3.",
      ].join("\n"),
      inputSchema: {
        entity: z.string().min(1).describe("Center entity name."),
        depth: z.number().int().min(1).max(3).optional().describe("Neighborhood depth. Default 1, clamp <=3."),
        limit: z.number().int().min(1).max(200).optional().describe("Max results. Default 100."),
      },
    },
    async ({ entity, depth, limit }) => {
      try {
        const data = await kgGet(ctx, "/subgraph", {
          entity,
          depth: Math.min(depth ?? 1, 3),
          limit,
        });
        return textResult(data);
      } catch (e) {
        return errorResult(`kg_subgraph failed: ${e instanceof Error ? e.message : String(e)}`);
      }
    },
  );

  // ── kg_query (pathfinding) ───────────────────────────────────────────
  server.registerTool(
    "kg_query",
    {
      description: [
        "Find a path between two entities in the knowledge graph.",
        "Use to determine how two entities are connected (e.g. 'how does honcho-db relate to postgres-rwdn?').",
        "Note: endpoint uses `from` and `to` query params.",
      ].join("\n"),
      inputSchema: {
        from: z.string().min(1).describe("Starting (source) entity name."),
        to: z.string().min(1).describe("Target entity name."),
        max_depth: z.number().int().min(1).max(10).optional().describe("Max path depth. Default 5."),
      },
    },
    async ({ from: from_, to, max_depth }) => {
      try {
        const data = await kgGet(ctx, "/path", {
          from: from_,
          to,
          max_depth,
        });
        return textResult(data);
      } catch (e) {
        return errorResult(`kg_query failed: ${e instanceof Error ? e.message : String(e)}`);
      }
    },
  );
// ── kg_auto_extract (populate) ─────────────────────────────────────
  server.registerTool(
    "kg_auto_extract",
    {
      description: [
        "Populate the knowledge graph by running entity/relationship extraction over recent workspace messages.",
        "Use to build/fill the knowledge graph from conversation history.",
        "Triggers LLM extraction on up to `limit` recent messages, then auto-links person/agent entities to peers.",
        "Note: this can be slow (LLM per message).",
      ].join("\n"),
      inputSchema: {
        limit: z.number().int().min(1).max(200).optional().describe("Number of recent messages to process. Default 20, max 200."),
        min_content_length: z.number().int().min(0).max(5000).optional().describe("Minimum message content length to consider. Default 40."),
      },
    },
    async ({ limit, min_content_length }) => {
      try {
        const ep = kgUrl(ctx, "/extract");
        const qs = new URLSearchParams({
          ...(limit !== undefined ? { limit: String(limit) } : {}),
          ...(min_content_length !== undefined ? { min_content_length: String(min_content_length) } : {}),
        });
        const res = await fetch(`${ep}?${qs.toString()}`, {
          method: "POST",
          headers: {
            Accept: "application/json",
            ...(ctx.config.apiKey ? { Authorization: `Bearer ${ctx.config.apiKey}` } : {}),
          },
        });
        if (!res.ok) {
          const body = await res.text().catch(() => "");
          throw new Error(`kg_auto_extract → HTTP ${res.status}: ${body.slice(0, 300)}`);
        }
        const data: unknown = await res.json();
        return textResult(data as object);
      } catch (e) {
        return errorResult(`kg_auto_extract failed: ${e instanceof Error ? e.message : String(e)}`);
      }
    },
  );
}