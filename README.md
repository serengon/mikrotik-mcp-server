# MikroTik MCP Server

MCP server that lets [Claude Code](https://docs.anthropic.com/en/docs/claude-code) manage one or multiple MikroTik routers through the RouterOS v7 REST API.

Claude discovers endpoints via a built-in search index (689 consolidated resources from the RouterOS 7.16 OpenAPI spec) and executes requests against your routers — all through natural language.

## Quick start

### One-line installer

The interactive installer checks prerequisites, tests connectivity to your router, and registers the MCP server in Claude Code:

```bash
curl -fsSL https://raw.githubusercontent.com/serengon/mikrotik-mcp-server/main/install.sh | bash
```

Or if you have the repo cloned:

```bash
bash install.sh
```

It supports both single-router and multi-router setups. Just follow the prompts.

### Manual setup (single router)

You need [Claude Code](https://docs.anthropic.com/en/docs/claude-code/getting-started) and a RouterOS v7 device (physical or Docker).

#### 1. Install `uv` (Python package runner)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### 2. Add the MCP server to Claude Code

```bash
claude mcp add mikrotik \
  -e ROUTEROS_URL=http://192.168.1.1 \
  -e ROUTEROS_USER=admin \
  -e ROUTEROS_PASSWORD= \
  -e ROUTEROS_VERIFY_SSL=false \
  -- uvx --from "git+https://github.com/serengon/mikrotik-mcp-server.git" mikrotik-mcp
```

#### 3. Start a test router (optional)

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

> Default credentials: `admin` with no password. Use `ROUTEROS_URL=http://localhost:8080`.

#### 4. Try it

```bash
claude
```

Type `/mcp` — you should see `mikrotik` connected with 3 tools. Then ask:

- *"What interfaces does the router have?"*
- *"Show me the IP addresses"*
- *"What's the router's uptime?"*
- *"List firewall filter rules"*
- *"Add a static route to 10.0.0.0/8 via 192.168.1.254"*

That's it. No clone, no venv, no config files.

---

## Multi-router setup

To manage multiple routers from a single Claude Code session, create a `routers.json` file:

```json
{
  "routers": {
    "edge-gw":   {"url": "http://192.168.1.1",  "user": "admin", "password": "", "verify_ssl": false},
    "core-sw":   {"url": "http://192.168.1.2",  "user": "admin", "password": "", "verify_ssl": false},
    "fw-01":     {"url": "http://192.168.1.3",  "user": "admin", "password": "", "verify_ssl": false},
    "wifi-ctrl": {"url": "http://192.168.1.4",  "user": "admin", "password": "", "verify_ssl": false}
  }
}
```

Then point the MCP server to it:

```bash
claude mcp add mikrotik \
  -e ROUTEROS_CONFIG=/path/to/routers.json \
  -- uvx --from "git+https://github.com/serengon/mikrotik-mcp-server.git" mikrotik-mcp
```

With multiple routers configured, use `list_routers` to see available devices and specify the target with the `router` parameter:

- *"List all routers"*
- *"Show interfaces on edge-gw"*
- *"What firewall rules does fw-01 have?"*
- *"Show OSPF neighbors on all routers"*

> **Tip:** For auditing, create a read-only user on each router and use those credentials in `routers.json`. Add `routers.json` to `.gitignore` — it contains passwords.

---

## How it works

Claude uses three tools to interact with routers:

| Tool | Purpose |
|---|---|
| `search_api` | Search the RouterOS API index by keyword to discover endpoints |
| `routeros_request` | Execute a REST call (GET/POST/PUT/PATCH/DELETE) against a router |
| `list_routers` | List all configured routers with their name, URL, and RouterOS version |

Plus one resource (`router://api-groups`) that provides an overview of all API groups.

### Configuration resolution order

1. `ROUTEROS_CONFIG` env var → path to a `routers.json` file
2. `routers.json` in the current working directory
3. Single-router fallback using `ROUTEROS_URL` / `ROUTEROS_USER` / `ROUTEROS_PASSWORD` env vars

---

## Configuration reference

| Variable | Default | Description |
|---|---|---|
| `ROUTEROS_URL` | *(required for single router)* | Router REST API base URL |
| `ROUTEROS_USER` | `admin` | Username |
| `ROUTEROS_PASSWORD` | *(empty)* | Password |
| `ROUTEROS_VERIFY_SSL` | `true` | Set to `false` for HTTP or self-signed certs |
| `ROUTEROS_CA_CERT` | *(none)* | Path to CA certificate for custom HTTPS |
| `ROUTEROS_CONFIG` | *(none)* | Path to `routers.json` for multi-router setups |

---

## Connecting to a real router

1. Enable the REST API: `/ip/service set www disabled=no` (HTTP) or `www-ssl disabled=no` (HTTPS)
2. For read-only access, create a dedicated user: `/user add name=mcp-audit group=read`
3. For HTTPS with a custom CA, set `ROUTEROS_VERIFY_SSL=true` and `ROUTEROS_CA_CERT=/path/to/ca.pem`

> The REST API requires RouterOS v7.1+.

---

## Development setup

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

---

## Troubleshooting

**MCP server not connecting**
- Check reachability: `curl -u admin: http://<router-ip>/rest/system/resource`
- For Docker: wait 30s after start, check with `docker logs routeros`

**"Multiple routers configured" error**
- You have more than one router in `routers.json` — specify which one: *"show interfaces on edge-gw"*

**"RouterOS error 401"**
- Wrong credentials — check `ROUTEROS_USER` and `ROUTEROS_PASSWORD`

**"RouterOS error 500"**
- Often a permissions issue (RouterOS returns 500 instead of 403). Check user group on the router.

---

## Project structure

```
src/mikrotik_mcp/
  server.py            # FastMCP entry point (tools + resource registration)
  client.py            # RouterOSClient (httpx wrapper with quirks handling)
  router_registry.py   # RouterRegistry (multi-router client management)
  api_index.py         # OAS2 keyword search index (689 consolidated resources)
  types.py             # Pydantic models and error hierarchy
  config.py            # Configuration from env vars or routers.json
  tools/
    api_tools.py       # search_api + routeros_request + list_routers
  data/
    routeros-7.16-oas2.json  # OpenAPI 2.0 spec (4607 paths)
docker/                # Docker CHR for single-router testing
gns3/                  # GNS3 enterprise rack scripts (see below)
tests/
docs/
  adr/                 # Architecture Decision Records
```

---

## Lab testing with GNS3 (optional)

The multi-router features were validated against a simulated enterprise rack running 4 MikroTik CHR instances in GNS3/QEMU. The `gns3/` directory contains the scripts used to set it up.

**What was tested end-to-end:**

| Test | Scenario |
|------|----------|
| Inter-router IPs | /30 links on ether2–ether4 |
| L3 ping | Between directly connected neighbors |
| Static routes | Reachability between non-adjacent routers |
| VLAN + SVI | VLAN 10 bridge + routed interface on core-sw |
| OSPF area 0 | Full adjacency + route redistribution |
| Firewall filter | Drop ICMP input from edge on fw-01 |
| OSPF full-mesh | All 4 routers, MD5 authentication |
| Policy routing | Force wifi-ctrl → fw-01 → vlan10 via mangle + routing table |

If you want to reproduce the lab:

```bash
# On a Linux machine with GNS3 + QEMU + KVM:
bash gns3/start_rack.sh      # start the 4-router topology
bash gns3/reset_rack.sh      # restore baseline snapshot before each test
```

See `gns3/` for full setup details.

## License

MIT
