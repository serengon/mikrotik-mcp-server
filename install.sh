#!/usr/bin/env bash
set -euo pipefail

# ── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

info()    { echo -e "${CYAN}ℹ${NC}  $*"; }
success() { echo -e "${GREEN}✔${NC}  $*"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $*"; }
error()   { echo -e "${RED}✖${NC}  $*"; }

# ── Step 1: Prerequisites ──────────────────────────────────────────────────
echo
echo -e "${BOLD}MikroTik MCP Server — Installer${NC}"
echo -e "────────────────────────────────────────"
echo

# claude
if ! command -v claude &>/dev/null; then
    error "Claude Code is not installed."
    echo "  Install it first: https://docs.anthropic.com/en/docs/claude-code/getting-started"
    exit 1
fi
success "Claude Code found"

# uv
if ! command -v uv &>/dev/null; then
    warn "uv not found — installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Source the env so uv is available in this session
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv &>/dev/null; then
        error "uv installation failed. Install manually: https://docs.astral.sh/uv/"
        exit 1
    fi
    success "uv installed"
else
    success "uv found"
fi

# curl
if ! command -v curl &>/dev/null; then
    error "curl is required but not installed."
    exit 1
fi
success "curl found"

echo

# ── Step 2: Interactive config ─────────────────────────────────────────────
echo -e "${BOLD}Router configuration${NC}"
echo

echo "  1) Single router"
echo "  2) Multi-router (existing routers.json)"
echo
read -rp "Choose [1]: " MODE_CHOICE
MODE_CHOICE="${MODE_CHOICE:-1}"

if [[ "$MODE_CHOICE" == "2" ]]; then
    # ── Multi-router ──
    read -rp "Path to routers.json: " ROUTERS_JSON
    ROUTERS_JSON="${ROUTERS_JSON/#\~/$HOME}"

    if [[ ! -f "$ROUTERS_JSON" ]]; then
        error "File not found: $ROUTERS_JSON"
        exit 1
    fi
    success "routers.json found: $ROUTERS_JSON"

    ROUTERS_JSON="$(cd "$(dirname "$ROUTERS_JSON")" && pwd)/$(basename "$ROUTERS_JSON")"

    # Store multi-router passwords in keyring
    echo
    info "Storing router passwords in OS keyring..."
    KEYRING_OK=true
    if uvx --from "git+https://github.com/serengon/mikrotik-mcp-server.git" python -c "
import json, keyring, sys
with open('$ROUTERS_JSON') as f:
    data = json.load(f)
routers = data.get('routers', data)
for name, cfg in routers.items():
    pw = cfg.get('password', '')
    if pw:
        keyring.set_password('mikrotik-mcp', name, pw)
        print(f'  Stored password for: {name}')
" 2>/dev/null; then
        success "Passwords stored in OS keyring"
        info "You can now remove 'password' fields from routers.json"
    else
        warn "Could not store passwords in keyring (no backend available?)"
        warn "Passwords will be read from routers.json instead"
        KEYRING_OK=false
    fi

    echo
    info "Registering MCP server with Claude Code..."
    claude mcp add mikrotik \
        -e "ROUTEROS_CONFIG=$ROUTERS_JSON" \
        -- uvx --from "git+https://github.com/serengon/mikrotik-mcp-server.git" mikrotik-mcp

    echo
    success "Done! MCP server registered with multi-router config."
    echo
    echo -e "  Open ${BOLD}claude${NC} and type ${BOLD}/mcp${NC} to verify."
    echo "  Then try: \"List all routers\""
    exit 0
fi

# ── Single router ──
read -rp "Router URL (e.g. 192.168.1.1 or http://192.168.1.1): " ROUTER_INPUT

# Strip trailing slashes
ROUTER_INPUT="${ROUTER_INPUT%/}"

echo
echo "  1) HTTP  (default, no certificate needed)"
echo "  2) HTTPS"
echo
read -rp "Protocol [1]: " PROTO_CHOICE
PROTO_CHOICE="${PROTO_CHOICE:-1}"

if [[ "$PROTO_CHOICE" == "2" ]]; then
    SCHEME="https"
    VERIFY_SSL="true"
else
    SCHEME="http"
    VERIFY_SSL="false"
fi

# Build the URL — add scheme if user didn't provide one
if [[ "$ROUTER_INPUT" =~ ^https?:// ]]; then
    ROUTER_URL="$ROUTER_INPUT"
    # Override verify_ssl based on scheme
    if [[ "$ROUTER_INPUT" =~ ^http:// ]]; then
        VERIFY_SSL="false"
    else
        VERIFY_SSL="true"
    fi
else
    ROUTER_URL="${SCHEME}://${ROUTER_INPUT}"
fi

echo
read -rp "Username [admin]: " ROUTER_USER
ROUTER_USER="${ROUTER_USER:-admin}"

read -srp "Password (hidden): " ROUTER_PASS
echo

# ── Step 3: Connectivity test ──────────────────────────────────────────────
echo
info "Testing connectivity to ${ROUTER_URL}..."

CURL_OPTS=(-s -o /dev/null -w "%{http_code}" -u "${ROUTER_USER}:${ROUTER_PASS}" --connect-timeout 10)
if [[ "$VERIFY_SSL" == "false" ]]; then
    CURL_OPTS+=(-k)
fi

HTTP_CODE=$(curl "${CURL_OPTS[@]}" "${ROUTER_URL}/rest/system/identity" 2>/dev/null) || HTTP_CODE="000"

if [[ "$HTTP_CODE" == "200" ]]; then
    # Fetch identity for confirmation
    IDENTITY_OPTS=(-s -u "${ROUTER_USER}:${ROUTER_PASS}" --connect-timeout 10)
    if [[ "$VERIFY_SSL" == "false" ]]; then
        IDENTITY_OPTS+=(-k)
    fi
    IDENTITY=$(curl "${IDENTITY_OPTS[@]}" "${ROUTER_URL}/rest/system/identity" 2>/dev/null)
    ROUTER_NAME=$(echo "$IDENTITY" | grep -oP '"name"\s*:\s*"\K[^"]+' 2>/dev/null || echo "unknown")
    success "Connected to router: ${BOLD}${ROUTER_NAME}${NC}"
elif [[ "$HTTP_CODE" == "401" ]]; then
    error "Authentication failed (HTTP 401). Check username and password."
    exit 1
elif [[ "$HTTP_CODE" == "000" ]]; then
    error "Could not connect to ${ROUTER_URL}"
    echo "  • Is the router reachable from this machine?"
    echo "  • Is the REST API enabled? (RouterOS: /ip/service set www disabled=no)"
    echo "  • Is the URL correct?"
    exit 1
else
    error "Unexpected response: HTTP ${HTTP_CODE}"
    echo "  • HTTP 404: REST API may not be available (requires RouterOS v7.1+)"
    echo "  • HTTP 500: Check user permissions on the router"
    exit 1
fi

# ── Step 4: Store password in keyring ──────────────────────────────────────
echo
info "Storing password in OS keyring..."
KEYRING_OK=false
if uvx --from "git+https://github.com/serengon/mikrotik-mcp-server.git" python -c "
import keyring
keyring.set_password('mikrotik-mcp', 'default', '''${ROUTER_PASS}''')
" 2>/dev/null; then
    success "Password stored in OS keyring (not saved to disk)"
    KEYRING_OK=true
else
    warn "Could not store password in keyring (no backend available?)"
    warn "Password will be passed as environment variable instead"
fi

# ── Step 5: Register in Claude Code ────────────────────────────────────────
echo
info "Registering MCP server with Claude Code..."

if [[ "$KEYRING_OK" == "true" ]]; then
    claude mcp add mikrotik \
        -e "ROUTEROS_URL=${ROUTER_URL}" \
        -e "ROUTEROS_USER=${ROUTER_USER}" \
        -e "ROUTEROS_VERIFY_SSL=${VERIFY_SSL}" \
        -- uvx --from "git+https://github.com/serengon/mikrotik-mcp-server.git" mikrotik-mcp
else
    claude mcp add mikrotik \
        -e "ROUTEROS_URL=${ROUTER_URL}" \
        -e "ROUTEROS_USER=${ROUTER_USER}" \
        -e "ROUTEROS_PASSWORD=${ROUTER_PASS}" \
        -e "ROUTEROS_VERIFY_SSL=${VERIFY_SSL}" \
        -- uvx --from "git+https://github.com/serengon/mikrotik-mcp-server.git" mikrotik-mcp
fi

# ── Step 6: Success ────────────────────────────────────────────────────────
echo
echo -e "${GREEN}────────────────────────────────────────${NC}"
success "MikroTik MCP server installed!"
echo -e "${GREEN}────────────────────────────────────────${NC}"
echo
echo -e "  Open ${BOLD}claude${NC} and type ${BOLD}/mcp${NC} to verify the server is connected."
echo
echo "  Try these prompts:"
echo "    • \"What interfaces does the router have?\""
echo "    • \"Show me the IP addresses\""
echo "    • \"What's the router's uptime?\""
echo
