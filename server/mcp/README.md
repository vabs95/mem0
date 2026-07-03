# Mem0 Self-Hosted MCP Bridge

This sidecar exposes MCP tools for the self-hosted Mem0 REST server. It keeps the
hosted MCP tool names while forwarding requests to the self-hosted REST API.

## Tools

- `add_memory`
- `search_memories`
- `get_memories`
- `get_memory`
- `update_memory`
- `delete_memory`
- `delete_all_memories`
- `list_entities`
- `delete_entities`

## Run With Docker Compose

From the repository root:

```bash
MEM0_API_KEY="m0sk_..." \
MEM0_DEFAULT_USER_ID="demo-user" \
docker compose -f docker-compose.mem0-mcp.yaml up -d --build
```

By default the sidecar joins the `mem0_mem0_network` Docker network and calls
`http://mem0:8000`. Override these when your deployment uses different names:

```bash
MEM0_DOCKER_NETWORK="my_mem0_network" \
MEM0_API_URL="http://mem0:8000" \
docker compose -f docker-compose.mem0-mcp.yaml up -d --build
```

Expose `127.0.0.1:8765` through your reverse proxy or Tailscale HTTPS endpoint,
then configure MCP clients with the `/mcp` Streamable HTTP URL.

## Scoping

The self-hosted REST server supports `user_id`, `agent_id`, and `run_id`. The
bridge accepts hosted-compatible `app_id` and maps it to `agent_id`.
