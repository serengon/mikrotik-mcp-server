# MikroTik MCP Server

MCP server that lets [Claude Code](https://docs.anthropic.com/en/docs/claude-code) manage a MikroTik router through the RouterOS v7 REST API.

Claude discovers endpoints via a built-in search index (689 consolidated resources from the RouterOS 7.16 OpenAPI spec) and executes requests against your router — all through natural language.

> **Status:** Beta — read operations work well; write support is coming.

## Prerequisites

- **Python 3.11+**
- **Docker** (with KVM support) — for the test router
- **Claude Code** — [installation guide](https://docs.anthropic.com/en/docs/claude-code/getting-started)

Verify KVM is available (required by the RouterOS Docker image):

```bash
ls /dev/kvm
```

## Quick start

### 1. Clone and install

```bash
git clone https://github.com/serengon/mikrotik-mcp-server.git
cd mikrotik-mcp-server
python3 -m venv .venv
.venv/bin/pip install -e .
```

This creates the `mikrotik-mcp` CLI entry point at `.venv/bin/mikrotik-mcp`.

### 2. Start the test router

The project includes a Docker Compose file that runs a RouterOS CHR instance:

```bash
docker compose -f docker/docker-compose.yml up -d
```

Wait ~30 seconds for RouterOS to boot, then verify it's responding:

```bash
curl -s -u admin: http://localhost:8080/rest/system/resource | head -c 200
```

You should see JSON with fields like `board-name`, `version`, `uptime`, etc.

> **Ports:** 8080 (HTTP REST API), 8443 (HTTPS), 2222 (SSH), 5900 (VNC).
> Default credentials: `admin` with no password.

### 3. Configure environment variables

```bash
cp .env.example .env
```

The defaults work out of the box with the Docker CHR:

| Variable | Default | Description |
|---|---|---|
| `ROUTEROS_URL` | `http://localhost:8080` | Router REST API base URL |
| `ROUTEROS_USER` | `admin` | Username |
| `ROUTEROS_PASSWORD` | *(empty)* | Password |
| `ROUTEROS_VERIFY_SSL` | `false` | Set to `true` + provide `ROUTEROS_CA_CERT` for production |
| `ROUTEROS_CA_CERT` | *(none)* | Path to CA certificate file for custom HTTPS |

### 4. Set your env vars in the shell

The `.mcp.json` references env vars with `${VAR}` syntax. Make sure they're exported in whatever shell Claude Code runs from:

```bash
# Option A: export directly
export ROUTEROS_URL=http://localhost:8080
export ROUTEROS_USER=admin
export ROUTEROS_PASSWORD=""
export ROUTEROS_VERIFY_SSL=false

# Option B: source .env (if your shell supports it)
set -a && source .env && set +a
```

### 5. Launch Claude Code

From the project root:

```bash
claude
```

Claude Code reads `.mcp.json` automatically and starts the MikroTik MCP server. Verify with:

```
/mcp
```

You should see `mikrotik` listed as a connected server with 2 tools and 1 resource.

### 6. Try it out

Ask Claude things like:

- *"What interfaces does the router have?"*
- *"Show me the IP addresses configured"*
- *"Search for DHCP-related endpoints"*
- *"What's the router's uptime and version?"*
- *"List firewall filter rules"*

Behind the scenes, Claude uses two tools:

| Tool | Purpose |
|---|---|
| `search_api` | Search the RouterOS API index by keyword to discover endpoints |
| `routeros_request` | Execute a REST call (GET/POST/PUT/PATCH/DELETE) against the router |

## Running tests

```bash
# Unit tests (no router needed)
.venv/bin/pytest -x -v --ignore=tests/test_integration.py

# Integration tests (requires Docker CHR running)
.venv/bin/pytest -x -v -m integration
```

## Connecting to a real router

To use this with a physical MikroTik device instead of Docker CHR:

1. Enable the REST API on the router: `ip/service set www-ssl disabled=no` (or `www` for HTTP)
2. Update your env vars to point to the router's IP and credentials
3. For HTTPS with a custom certificate, set `ROUTEROS_VERIFY_SSL=true` and `ROUTEROS_CA_CERT=/path/to/ca.pem`

> **Note:** The REST API is available on RouterOS v7.1+ only.

## Troubleshooting

**"Connection refused" when starting Claude Code**
- Check that Docker CHR is running: `docker compose -f docker/docker-compose.yml ps`
- Verify the REST API responds: `curl -u admin: http://localhost:8080/rest/system/resource`

**MCP server not showing in `/mcp`**
- Make sure you're in the project root directory (where `.mcp.json` lives)
- Check that env vars are exported in your shell
- Verify the entry point exists: `ls .venv/bin/mikrotik-mcp`

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
