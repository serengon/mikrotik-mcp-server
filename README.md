# MikroTik MCP Server

MCP server that lets [Claude Code](https://docs.anthropic.com/en/docs/claude-code) manage a MikroTik router through the RouterOS v7 REST API.

Claude discovers endpoints via a built-in search index (689 consolidated resources from the RouterOS 7.16 OpenAPI spec) and executes requests against your router — all through natural language.

> **Status:** Beta — read operations work well; write support is coming.

## Quick start (for testers)

You need [Claude Code](https://docs.anthropic.com/en/docs/claude-code/getting-started) and a RouterOS v7 device (physical or Docker).

### 1. Install `uv` (Python package runner)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Add the MCP server to Claude Code

```bash
claude mcp add mikrotik \
  -e ROUTEROS_URL=http://localhost:8080 \
  -e ROUTEROS_USER=admin \
  -e ROUTEROS_PASSWORD= \
  -e ROUTEROS_VERIFY_SSL=false \
  -- uvx --from "git+https://github.com/serengon/mikrotik-mcp-server.git" mikrotik-mcp
```

Adjust the `-e` values if your router has a different IP, user, or password.

### 3. Start a test router (optional)

If you don't have a physical MikroTik, run one in Docker (requires KVM — check with `ls /dev/kvm`):

```bash
docker run -d --name routeros --cap-add NET_ADMIN \
  --device /dev/net/tun --device /dev/kvm \
  -p 8080:80 -p 8443:443 -p 2222:22 \
  evilfreelancer/docker-routeros:7.16
```

Wait ~30 seconds for it to boot, then verify:

```bash
curl -s -u admin: http://localhost:8080/rest/system/resource | head -c 200
```

> Default credentials: `admin` with no password.

### 4. Try it

```bash
claude
```

Type `/mcp` — you should see `mikrotik` connected with 2 tools. Then ask:

- *"What interfaces does the router have?"*
- *"Show me the IP addresses"*
- *"What's the router's uptime?"*
- *"Search for DHCP-related endpoints"*
- *"List firewall filter rules"*

That's it. No clone, no venv, no config files.

---

## How it works

Claude uses two tools to interact with the router:

| Tool | Purpose |
|---|---|
| `search_api` | Search the RouterOS API index by keyword to discover endpoints |
| `routeros_request` | Execute a REST call (GET/POST/PUT/PATCH/DELETE) against the router |

Plus one resource (`router://api-groups`) that provides an overview of all API groups.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ROUTEROS_URL` | *(required)* | Router REST API base URL |
| `ROUTEROS_USER` | *(required)* | Username |
| `ROUTEROS_PASSWORD` | *(empty)* | Password |
| `ROUTEROS_VERIFY_SSL` | `true` | Set to `false` for HTTP or self-signed certs |
| `ROUTEROS_CA_CERT` | *(none)* | Path to CA certificate file for custom HTTPS |

## Connecting to a real router

1. Enable the REST API on the router: `/ip/service set www-ssl disabled=no` (or `www` for HTTP)
2. Use the router's IP and credentials in the `claude mcp add` command
3. For HTTPS with a custom CA, set `ROUTEROS_VERIFY_SSL=true` and `ROUTEROS_CA_CERT=/path/to/ca.pem`

> The REST API requires RouterOS v7.1+.

## Development setup

For contributors who want to modify the code or run tests:

```bash
git clone https://github.com/serengon/mikrotik-mcp-server.git
cd mikrotik-mcp-server
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

The project includes a `.mcp.json` that points to the local venv, so Claude Code picks it up automatically when working from the repo. Export the env vars first:

```bash
cp .env.example .env
# edit .env with your values, then:
set -a && source .env && set +a
claude
```

### Running tests

```bash
# Unit tests (no router needed)
.venv/bin/pytest -x -v --ignore=tests/test_integration.py

# Integration tests (requires Docker CHR running)
docker compose -f docker/docker-compose.yml up -d
.venv/bin/pytest -x -v -m integration

# Lint
.venv/bin/ruff check src/ tests/
```

## Troubleshooting

**MCP server not connecting**
- Check that the router is reachable: `curl -u admin: http://localhost:8080/rest/system/resource`
- For Docker: wait 30s after start, check with `docker logs routeros`

**MCP server not showing in `/mcp`**
- Verify it was added: `claude mcp list`
- Re-add if needed with the `claude mcp add` command above

**"RouterOS error 401"**
- Wrong credentials — check `ROUTEROS_USER` and `ROUTEROS_PASSWORD`

**"RouterOS error 500"**
- Often a permissions issue (RouterOS returns 500 instead of 403). Check user privileges on the router.

## Project structure

```
src/mikrotik_mcp/
  server.py          # FastMCP entry point (tools + resource registration)
  client.py          # RouterOSClient (httpx wrapper with quirks handling)
  api_index.py       # OAS2 keyword search index (689 consolidated resources)
  types.py           # Pydantic models and error hierarchy
  config.py          # Configuration from env vars
  data/
    routeros-7.16-oas2.json  # OpenAPI 2.0 spec (4607 paths)
  tools/
    api_tools.py     # search_api + routeros_request
docker/
  docker-compose.yml # RouterOS CHR for testing
tests/
docs/
  adr/               # Architecture Decision Records
```

## License

MIT
