#!/usr/bin/env python3
"""Bootstrap fresh MikroTik CHR routers in GNS3 from scratch.

Handles the full first-boot experience:
1. EULA acceptance (sends 'q' to skip through the license pages)
2. Forced password change (CHR 7.x won't accept empty as new password)
3. System identity + management IP + REST API service config

Use this when creating a topology from virgin CHR images.
For already-bootstrapped routers, use bootstrap_routers.py instead.

Usage:
    python gns3/bootstrap_fresh.py [--gns3-url http://10.0.0.20:3080]
    python gns3/bootstrap_fresh.py --password 'MyPass123!'
"""

from __future__ import annotations

import argparse
import re
import socket
import sys
import time

import httpx

GNS3_URL = "http://10.0.0.20:3080"
GNS3_HOST = "10.0.0.20"
PROJECT_NAME = "enterprise-rack"
DEFAULT_PASSWORD = "Mcp2026x"

ROUTERS = {
    "edge-gw": "172.16.0.1",
    "core-sw": "172.16.0.2",
    "fw-01": "172.16.0.3",
    "wifi-ctrl": "172.16.0.4",
}

BOOT_WAIT = 65
TELNET_TIMEOUT = 15
MAX_RETRIES = 3
RETRY_DELAY = 10


def api(client: httpx.Client, method: str, path: str, **kwargs) -> dict | list:
    """Make a GNS3 API call."""
    resp = client.request(method, path, **kwargs)
    if resp.status_code >= 400:
        print(f"ERROR {resp.status_code}: {method} {path}", file=sys.stderr)
        print(resp.text, file=sys.stderr)
        sys.exit(1)
    if not resp.content:
        return {}
    return resp.json()


def find_project(client: httpx.Client, name: str) -> str:
    """Find a GNS3 project by name."""
    projects = api(client, "GET", "/v2/projects")
    for p in projects:
        if p["name"] == name:
            if p["status"] != "opened":
                api(client, "POST", f"/v2/projects/{p['project_id']}/open")
            return p["project_id"]
    print(f"ERROR: Project '{name}' not found", file=sys.stderr)
    sys.exit(1)


def get_console_ports(client: httpx.Client, project_id: str) -> dict[str, int]:
    """Get telnet console port for each router node."""
    nodes = api(client, "GET", f"/v2/projects/{project_id}/nodes")
    ports = {}
    for node in nodes:
        if node["name"] in ROUTERS and node.get("console"):
            ports[node["name"]] = node["console"]
    return ports


def raw_recv(sock: socket.socket, wait: float = 1.5) -> str:
    """Read all available data from socket after waiting."""
    time.sleep(wait)
    data = b""
    sock.settimeout(0.3)
    while True:
        try:
            chunk = sock.recv(8192)
            if not chunk:
                break
            data += chunk
        except (TimeoutError, socket.timeout, OSError):
            break
    sock.settimeout(TELNET_TIMEOUT)
    # Strip telnet IAC sequences and ANSI escape codes
    clean = re.sub(rb"\xff[\xfb\xfc\xfd\xfe].", b"", data)
    text = clean.decode("utf-8", errors="replace")
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    text = re.sub(r"\x1b[Zc]", "", text)
    return text


def bootstrap_router(host: str, port: int, name: str, mgmt_ip: str, password: str) -> bool:
    """Configure a single fresh CHR router via its telnet console."""
    print(f"\n  [{name}] Connecting to console {host}:{port}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TELNET_TIMEOUT)

    try:
        sock.connect((host, port))
    except (ConnectionRefusedError, TimeoutError, OSError) as exc:
        print(f"  [{name}] Connection failed: {exc}")
        return False

    # Step 1: Read initial output
    out = raw_recv(sock, 3.0)

    # Step 2: Press enter to trigger login
    sock.sendall(b"\r\n")
    out = raw_recv(sock, 2.0)

    # Step 3: Login if we see a login prompt
    if "Login:" in out:
        sock.sendall(b"admin\r\n")
        out = raw_recv(sock, 1.5)
        if "Password:" in out:
            sock.sendall(b"\r\n")  # empty password for fresh CHR
            out = raw_recv(sock, 2.0)

    # Step 4: Skip EULA by sending 'q' repeatedly
    eula_pages = 0
    for _ in range(40):
        if "new password" in out.lower() or "@" in out:
            break
        sock.sendall(b"q")
        out = raw_recv(sock, 0.5)
        eula_pages += 1

    if eula_pages > 0:
        print(f"  [{name}] Skipped EULA ({eula_pages} pages)")

    # Step 5: Handle forced password change
    if "new password" in out.lower():
        print(f"  [{name}] Setting password...")
        sock.sendall(password.encode() + b"\r\n")
        out = raw_recv(sock, 2.0)

        if "repeat" in out.lower():
            sock.sendall(password.encode() + b"\r\n")
            out = raw_recv(sock, 3.0)

        if "@" in out:
            print(f"  [{name}] Password set, got CLI prompt")
        else:
            print(f"  [{name}] WARNING: unexpected state after password change")
            print(f"  [{name}] Output: {out.strip()[-150:]}")
    elif "@" in out:
        print(f"  [{name}] Already at CLI prompt (no password change needed)")
    else:
        print(f"  [{name}] WARNING: unexpected state, trying commands anyway")
        print(f"  [{name}] Output: {out.strip()[-150:]}")

    # Step 6: Send configuration commands
    commands = [
        f"/system identity set name={name}",
        f"/ip address add address={mgmt_ip}/24 interface=ether1",
        "/ip service set www disabled=no port=80",
        "/ip service set api disabled=no",
    ]

    for cmd in commands:
        sock.sendall(cmd.encode() + b"\r\n")
        out = raw_recv(sock, 1.5)
        if "failure:" in out.lower() or "bad command" in out.lower():
            if "already have" not in out.lower():
                print(f"  [{name}] Command error: {cmd}")
                print(f"  [{name}]   -> {out.strip()[-100:]}")

    sock.close()
    print(f"  [{name}] Configured: {mgmt_ip}")
    return True


def verify_rest_api(mgmt_ip: str, name: str, password: str) -> bool:
    """Check if the REST API is reachable."""
    try:
        resp = httpx.get(
            f"http://{mgmt_ip}/rest/system/identity",
            auth=("admin", password),
            timeout=5.0,
        )
        if resp.status_code == 200:
            identity = resp.json()
            print(f"  [{name}] REST API OK: {identity}")
            return True
        print(f"  [{name}] REST API returned {resp.status_code}")
        return False
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        print(f"  [{name}] REST API not reachable: {exc}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap fresh MikroTik CHR routers in GNS3 (handles EULA + password change)"
    )
    parser.add_argument("--gns3-url", default=GNS3_URL, help="GNS3 server URL")
    parser.add_argument("--gns3-host", default=GNS3_HOST, help="GNS3 server hostname for telnet")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Password to set on routers")
    parser.add_argument("--skip-wait", action="store_true", help="Skip initial boot wait")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.gns3_url, timeout=30.0)

    # Find project and get console ports
    project_id = find_project(client, PROJECT_NAME)
    console_ports = get_console_ports(client, project_id)

    missing = set(ROUTERS) - set(console_ports)
    if missing:
        print(f"ERROR: Missing console ports for: {missing}", file=sys.stderr)
        print("Make sure all router nodes are started.", file=sys.stderr)
        sys.exit(1)

    print(f"Console ports: {console_ports}")

    # Wait for boot
    if not args.skip_wait:
        print(f"\nWaiting {BOOT_WAIT}s for routers to boot...")
        time.sleep(BOOT_WAIT)

    # Bootstrap each router with retries
    print("\nBootstrapping fresh CHR routers...")
    failed = []
    for name, mgmt_ip in ROUTERS.items():
        port = console_ports[name]
        success = False
        for attempt in range(MAX_RETRIES):
            if bootstrap_router(args.gns3_host, port, name, mgmt_ip, args.password):
                success = True
                break
            print(f"  [{name}] Retry {attempt + 1}/{MAX_RETRIES} in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)
        if not success:
            failed.append(name)

    if failed:
        print(f"\nERROR: Failed to bootstrap: {failed}", file=sys.stderr)
        sys.exit(1)

    # Verify REST API access
    print("\nVerifying REST API access...")
    time.sleep(5)
    all_ok = True
    for name, mgmt_ip in ROUTERS.items():
        if not verify_rest_api(mgmt_ip, name, args.password):
            all_ok = False

    if all_ok:
        print("\nAll routers bootstrapped and REST API accessible!")
        print(f"Credentials: admin / {args.password}")
        print("\nNext: take a snapshot so reset_rack.sh can restore to this state:")
        print(f'  curl -s -X POST "{args.gns3_url}/v2/projects/{project_id}/snapshots" \\')
        print('    -H "Content-Type: application/json" \\')
        print('    -d \'{"name": "baseline"}\'')
    else:
        print("\nSome routers not reachable via REST API.")
        print("Check management bridge and routing:")
        print("  From mvp-server: sudo ip link show gns3-mgmt")
        print("  From dev: ip route get 172.16.0.1")
        print("  NAT rule: sudo iptables -t nat -A POSTROUTING -s 10.0.0.0/24 -o gns3-mgmt -j MASQUERADE")


if __name__ == "__main__":
    main()
