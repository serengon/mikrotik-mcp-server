#!/usr/bin/env python3
"""Create the enterprise-rack topology in GNS3 on mvp-server (10.0.0.20).

Connects to the GNS3 REST API and creates:
- 4 MikroTik CHR nodes (edge-gw, core-sw, fw-01, wifi-ctrl)
- 1 ethernet switch (mgmt-switch)
- 1 cloud node (bridged to gns3-mgmt)
- All inter-router links per the enterprise rack design

Usage:
    python gns3/create_topology.py [--gns3-url http://10.0.0.20:3080]
"""

from __future__ import annotations

import argparse
import sys

import httpx

GNS3_URL = "http://10.0.0.20:3080"
PROJECT_NAME = "enterprise-rack"
TEMPLATE_NAME = "MikroTik CHR 7.16"

ROUTERS = [
    {"name": "edge-gw", "x": 0, "y": -200},
    {"name": "core-sw", "x": -200, "y": 0},
    {"name": "fw-01", "x": 200, "y": 0},
    {"name": "wifi-ctrl", "x": -200, "y": 200},
]

# Links between routers: (node_a, adapter_a, node_b, adapter_b)
# adapter 0 = ether1 (mgmt), adapter 1 = ether2, etc.
INTER_ROUTER_LINKS = [
    ("edge-gw", 1, "core-sw", 1),  # edge-gw:ether2 <-> core-sw:ether2
    ("edge-gw", 2, "fw-01", 1),    # edge-gw:ether3 <-> fw-01:ether2
    ("core-sw", 2, "fw-01", 2),    # core-sw:ether3 <-> fw-01:ether3
    ("core-sw", 3, "wifi-ctrl", 1),  # core-sw:ether4 <-> wifi-ctrl:ether2
]


def api(client: httpx.Client, method: str, path: str, **kwargs) -> dict:
    """Make a GNS3 API call, raise on error."""
    resp = client.request(method, path, **kwargs)
    if resp.status_code >= 400:
        print(f"ERROR {resp.status_code}: {method} {path}", file=sys.stderr)
        print(resp.text, file=sys.stderr)
        sys.exit(1)
    if not resp.content:
        return {}
    return resp.json()


def find_template(client: httpx.Client, name: str) -> str:
    """Find a GNS3 template by name, return its ID."""
    templates = api(client, "GET", "/v2/templates")
    for t in templates:
        if t["name"] == name:
            return t["template_id"]
    print(f"ERROR: Template '{name}' not found. Available:", file=sys.stderr)
    for t in templates:
        print(f"  - {t['name']}", file=sys.stderr)
    sys.exit(1)


def find_or_create_project(client: httpx.Client, name: str) -> str:
    """Find existing project or create a new one."""
    projects = api(client, "GET", "/v2/projects")
    for p in projects:
        if p["name"] == name:
            print(f"Found existing project: {name} ({p['project_id']})")
            # Open it if not already open
            if p["status"] != "opened":
                api(client, "POST", f"/v2/projects/{p['project_id']}/open")
            return p["project_id"]

    project = api(client, "POST", "/v2/projects", json={"name": name})
    print(f"Created project: {name} ({project['project_id']})")
    return project["project_id"]


def create_node_from_template(
    client: httpx.Client, project_id: str, template_id: str, name: str, x: int, y: int
) -> dict:
    """Create a node from a template."""
    node = api(
        client,
        "POST",
        f"/v2/projects/{project_id}/templates/{template_id}",
        json={"name": name, "x": x, "y": y},
    )
    print(f"  Created node: {name} ({node['node_id']})")
    return node


def create_ethernet_switch(client: httpx.Client, project_id: str) -> dict:
    """Create a built-in ethernet switch node."""
    node = api(
        client,
        "POST",
        f"/v2/projects/{project_id}/nodes",
        json={
            "name": "mgmt-switch",
            "node_type": "ethernet_switch",
            "compute_id": "local",
            "x": 0,
            "y": 100,
            "properties": {
                "ports_mapping": [
                    {"name": f"Ethernet{i}", "port_number": i, "type": "access", "vlan": 1}
                    for i in range(8)
                ],
            },
        },
    )
    print(f"  Created node: mgmt-switch ({node['node_id']})")
    return node


def create_cloud_node(client: httpx.Client, project_id: str) -> dict:
    """Create a cloud node bridged to gns3-mgmt interface."""
    node = api(
        client,
        "POST",
        f"/v2/projects/{project_id}/nodes",
        json={
            "name": "mgmt-cloud",
            "node_type": "cloud",
            "compute_id": "local",
            "x": 200,
            "y": 100,
            "properties": {
                "ports_mapping": [
                    {
                        "interface": "gns3-mgmt",
                        "name": "gns3-mgmt",
                        "port_number": 0,
                        "type": "ethernet",
                    }
                ],
            },
        },
    )
    print(f"  Created node: mgmt-cloud ({node['node_id']})")
    return node


def create_link(
    client: httpx.Client,
    project_id: str,
    node_a_id: str,
    adapter_a: int,
    port_a: int,
    node_b_id: str,
    adapter_b: int,
    port_b: int,
) -> dict:
    """Create a link between two nodes."""
    return api(
        client,
        "POST",
        f"/v2/projects/{project_id}/links",
        json={
            "nodes": [
                {"node_id": node_a_id, "adapter_number": adapter_a, "port_number": port_a},
                {"node_id": node_b_id, "adapter_number": adapter_b, "port_number": port_b},
            ]
        },
    )


def start_all_nodes(client: httpx.Client, project_id: str) -> None:
    """Start all nodes in the project."""
    nodes = api(client, "GET", f"/v2/projects/{project_id}/nodes")
    for node in nodes:
        if node["status"] != "started":
            api(client, "POST", f"/v2/projects/{project_id}/nodes/{node['node_id']}/start")
            print(f"  Started: {node['name']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create GNS3 enterprise-rack topology")
    parser.add_argument("--gns3-url", default=GNS3_URL, help="GNS3 server URL")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.gns3_url, timeout=30.0)

    # Verify GNS3 connectivity
    version = api(client, "GET", "/v2/version")
    print(f"GNS3 server: {version.get('version', 'unknown')}")

    # Find CHR template
    template_id = find_template(client, TEMPLATE_NAME)
    print(f"Using template: {TEMPLATE_NAME} ({template_id})")

    # Create or reuse project
    project_id = find_or_create_project(client, PROJECT_NAME)

    # Create router nodes
    print("\nCreating router nodes...")
    nodes = {}
    for router in ROUTERS:
        node = create_node_from_template(
            client, project_id, template_id, router["name"], router["x"], router["y"]
        )
        nodes[router["name"]] = node

    # Create management switch and cloud
    print("\nCreating management infrastructure...")
    mgmt_switch = create_ethernet_switch(client, project_id)
    mgmt_cloud = create_cloud_node(client, project_id)

    # Link cloud to mgmt-switch (port 0)
    print("\nCreating management links...")
    create_link(
        client,
        project_id,
        mgmt_cloud["node_id"],
        0,
        0,
        mgmt_switch["node_id"],
        0,
        0,
    )
    print("  mgmt-cloud <-> mgmt-switch:Ethernet0")

    # Link each router ether1 (adapter 0) to mgmt-switch
    for i, router in enumerate(ROUTERS):
        switch_port = i + 1  # ports 1-4 on the switch
        create_link(
            client,
            project_id,
            nodes[router["name"]]["node_id"],
            0,
            0,
            mgmt_switch["node_id"],
            0,
            switch_port,
        )
        print(f"  {router['name']}:ether1 <-> mgmt-switch:Ethernet{switch_port}")

    # Create inter-router links
    print("\nCreating inter-router links...")
    for node_a, adapter_a, node_b, adapter_b in INTER_ROUTER_LINKS:
        create_link(
            client,
            project_id,
            nodes[node_a]["node_id"],
            adapter_a,
            0,
            nodes[node_b]["node_id"],
            adapter_b,
            0,
        )
        ether_a = adapter_a + 1
        ether_b = adapter_b + 1
        print(f"  {node_a}:ether{ether_a} <-> {node_b}:ether{ether_b}")

    # Start all nodes
    print("\nStarting all nodes...")
    start_all_nodes(client, project_id)

    print("\nTopology created. Waiting for routers to boot...")
    print("Run bootstrap_routers.py after ~60s to configure management IPs.")


if __name__ == "__main__":
    main()
