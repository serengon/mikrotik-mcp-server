#!/usr/bin/env python3
"""Bootstrap MikroTik CHR routers in GNS3 via telnet console.

Connects to each router's telnet console (exposed by GNS3) and configures:
- System identity
- Management IP on ether1
- HTTP REST API service enabled

Usage:
    python gns3/bootstrap_routers.py [--gns3-url http://10.0.0.20:3080]
"""

from __future__ import annotations

import argparse
import socket
import sys
import time

import httpx

GNS3_URL = "http://10.0.0.20:3080"
GNS3_HOST = "10.0.0.20"
PROJECT_NAME = "enterprise-rack"

ROUTERS = {
    "edge-gw": "172.16.0.1",
    "core-sw": "172.16.0.2",
    "fw-01": "172.16.0.3",
    "wifi-ctrl": "172.16.0.4",
}

BOOT_WAIT = 60
TELNET_TIMEOUT = 10
MAX_RETRIES = 5
RETRY_DELAY = 15


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


def telnet_send(host: str, port: int, commands: list[str]) -> str:
    """Send commands via raw telnet socket to a RouterOS console."""
    output = ""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TELNET_TIMEOUT)
        sock.connect((host, port))

        # Wait for login prompt or existing session
        time.sleep(2)
        try:
            data = sock.recv(4096)
            output += data.decode("utf-8", errors="replace")
        except TimeoutError:
            pass

        # Send enter to get past any prompt
        sock.sendall(b"\r\n")
        time.sleep(1)
        try:
            data = sock.recv(4096)
            output += data.decode("utf-8", errors="replace")
        except TimeoutError:
            pass

        # If we see a login prompt, log in as admin with no password
        if "Login:" in output or "login:" in output:
            sock.sendall(b"admin\r\n")
            time.sleep(1)
            try:
                data = sock.recv(4096)
                output += data.decode("utf-8", errors="replace")
            except TimeoutError:
                pass

            # Password prompt (empty password for fresh CHR)
            if "Password:" in output or "password:" in output:
                sock.sendall(b"\r\n")
                time.sleep(1)
                try:
                    data = sock.recv(4096)
                    output += data.decode("utf-8", errors="replace")
                except TimeoutError:
                    pass

        # Send each command
        for cmd in commands:
            sock.sendall(f"{cmd}\r\n".encode())
            time.sleep(1)
            try:
                data = sock.recv(4096)
                output += data.decode("utf-8", errors="replace")
            except TimeoutError:
                pass

        sock.close()
    except (ConnectionRefusedError, TimeoutError, OSError) as exc:
        return f"CONNECTION_ERROR: {exc}"

    return output


def bootstrap_router(host: str, port: int, name: str, mgmt_ip: str) -> bool:
    """Configure a single router via its telnet console."""
    commands = [
        f"/system identity set name={name}",
        f"/ip address add address={mgmt_ip}/24 interface=ether1",
        "/ip service set www disabled=no port=80",
        "/ip service set api disabled=no",
    ]

    print(f"  Configuring {name} (console {host}:{port})...")
    output = telnet_send(host, port, commands)

    if "CONNECTION_ERROR" in output:
        print(f"    Failed: {output}")
        return False

    if (
        ("failure" in output.lower() or "error" in output.lower())
        and "already have" not in output.lower()
    ):
        print("    Warning: possible error in output")
        print(f"    Output: {output[-200:]}")

    print(f"    Done: {name} -> {mgmt_ip}")
    return True


def verify_rest_api(mgmt_ip: str, name: str) -> bool:
    """Check if the REST API is reachable on a router."""
    try:
        resp = httpx.get(
            f"http://{mgmt_ip}/rest/system/identity",
            auth=("admin", ""),
            timeout=5.0,
        )
        if resp.status_code == 200:
            identity = resp.json()
            print(f"    REST API OK: {identity}")
            return True
        print(f"    REST API returned {resp.status_code}")
        return False
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        print(f"    REST API not reachable: {exc}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap MikroTik CHR routers in GNS3")
    parser.add_argument("--gns3-url", default=GNS3_URL, help="GNS3 server URL")
    parser.add_argument("--gns3-host", default=GNS3_HOST, help="GNS3 server hostname for telnet")
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
    print("\nBootstrapping routers...")
    failed = []
    for name, mgmt_ip in ROUTERS.items():
        port = console_ports[name]
        success = False
        for attempt in range(MAX_RETRIES):
            if bootstrap_router(args.gns3_host, port, name, mgmt_ip):
                success = True
                break
            print(f"    Retry {attempt + 1}/{MAX_RETRIES} in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)
        if not success:
            failed.append(name)

    if failed:
        print(f"\nERROR: Failed to bootstrap: {failed}", file=sys.stderr)
        sys.exit(1)

    # Verify REST API access
    print("\nVerifying REST API access...")
    time.sleep(5)  # Give services a moment to start
    all_ok = True
    for name, mgmt_ip in ROUTERS.items():
        print(f"  {name} ({mgmt_ip}):")
        if not verify_rest_api(mgmt_ip, name):
            all_ok = False

    if all_ok:
        print("\nAll routers bootstrapped and REST API accessible!")
    else:
        print("\nSome routers not yet reachable via REST API.")
        print("This may be normal if the management bridge/route is not yet configured.")
        print("From mvp-server, ensure gns3-mgmt bridge exists:")
        print("  sudo ip link add gns3-mgmt type bridge")
        print("  sudo ip addr add 172.16.0.254/24 dev gns3-mgmt")
        print("  sudo ip link set gns3-mgmt up")
        print("From dev machine, add route:")
        print("  sudo ip route add 172.16.0.0/24 via 10.0.0.20")


if __name__ == "__main__":
    main()
