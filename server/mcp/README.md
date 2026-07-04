# Mem0 Self-Hosted MCP Bridge

This sidecar exposes MCP tools for the self-hosted Mem0 REST server. It keeps the hosted MCP tool signatures while forwarding requests to the self-hosted REST API.

## Tools

- `add_memory` (stores preferences/facts, accepts `project` and `task`/`run_id`)
- `search_memories` (searches facts, supports filtering by `project`)
- `get_memories` (lists user memories)
- `get_memory` (gets a single memory)
- `update_memory` (updates a memory)
- `delete_memory` (deletes a memory)
- `delete_all_memories` (deletes memories for a user/run scope)
- `list_entities` (lists users, agents, and runs holding memories)
- `delete_entities` (removes user, agent, or run entities)

## Run With Docker Compose

From the repository root:

```bash
docker compose up -d --build
```

Expose `127.0.0.1:8765` through your reverse proxy or Tailscale HTTPS endpoint, then configure MCP clients with the `/mcp` Streamable HTTP URL.

## Dynamic Client Scoping & Authentication

The MCP bridge dynamically routes requests to the backend using the client's credentials and parameters sent via headers:

- **Authentication**: Forwarded to the backend as `X-API-Key`.
- **User Identity (`X-User-Id`)**: Associates memories to the developer.
- **Source Agent (`X-Source-Agent`)**: Automatically records which agent wrote the memory (stored in `metadata.source`).

### Client Configuration

#### 1. Codex (JSON format)
Configure the MCP server in your `.codex-mcp.json` or equivalent configuration:

```json
{
  "mcpServers": {
    "mem0": {
      "type": "http",
      "url": "https://<your-vps-url>:8765/mcp",
      "bearer_token_env_var": "MEM0_API_KEY",
      "http_headers": {
        "X-User-Id": "seth",
        "X-Source-Agent": "codex"
      }
    }
  }
}
```
*Make sure to export `MEM0_API_KEY` locally in the shell running Codex.*

#### 2. Other Agents (TOML format)
Configure using TOML:

```toml
[mcp_servers.mem0]
url = "https://<your-vps-url>:8765/mcp"
bearer_token_env_var = "MEM0_API_KEY"
http_headers = { "X-User-Id" = "seth", "X-Source-Agent" = "codex" }
```

## Memory Scoping

The self-hosted REST server supports `user_id`, `agent_id`, and `run_id`.
- **Project Scope**: Use the `project` tool parameter. It is automatically stored inside the memory's `metadata` and is used for scoping search queries.
- **Task Scope**: Use the `run_id` (or `task`) tool parameter to isolate memories to specific active debug sessions or tickets.
