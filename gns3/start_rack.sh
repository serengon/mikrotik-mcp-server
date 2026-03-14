#!/usr/bin/env bash
# Start the GNS3 enterprise rack on mvp-server (10.0.0.20).
# Run from dev: bash gns3/start_rack.sh
set -euo pipefail

SSH="ssh andres@10.0.0.20"
GNS3_URL="http://localhost:3080"
PROJECT_ID="19cbfa0c-b4d8-449c-a387-1e23dfec3fce"
CLOUD_NODE_ID="c054837c-9c8e-4b02-8404-bdabe0d939e6"
MGMT_IFACE="enxd8bbc11e0730"

echo "=== Starting GNS3 rack on mvp-server ==="

# 1. Start GNS3 if not running
$SSH "pgrep gns3server > /dev/null || sg kvm -c 'nohup gns3server --host 0.0.0.0 --port 3080 > /tmp/gns3.log 2>&1 &'"
sleep 3
$SSH "curl -sf $GNS3_URL/v2/version > /dev/null && echo 'GNS3: OK'"

# 2. Open project and start QEMU nodes
$SSH "curl -s -X POST $GNS3_URL/v2/projects/$PROJECT_ID/open > /dev/null"
$SSH "curl -s -X POST $GNS3_URL/v2/projects/$PROJECT_ID/nodes/start > /dev/null"
echo "Nodes: started"

# 3. Recreate management bridge
$SSH "
if ! ip link show gns3-mgmt > /dev/null 2>&1; then
  sudo ip link add gns3-mgmt type bridge
  sudo ip addr add 172.16.0.254/24 dev gns3-mgmt
  sudo ip link set gns3-mgmt up
fi
"

# 4. Restart cloud node to attach tap to bridge
$SSH "curl -s -X POST $GNS3_URL/v2/projects/$PROJECT_ID/nodes/$CLOUD_NODE_ID/stop > /dev/null; sleep 2; curl -s -X POST $GNS3_URL/v2/projects/$PROJECT_ID/nodes/$CLOUD_NODE_ID/start > /dev/null"
sleep 2
echo "Bridge: OK"

# 5. Re-apply iptables forwarding rules
$SSH "
sudo iptables -D FORWARD -i gns3-mgmt -o $MGMT_IFACE -j ACCEPT 2>/dev/null || true
sudo iptables -D FORWARD -i $MGMT_IFACE -o gns3-mgmt -j ACCEPT 2>/dev/null || true
sudo iptables -I FORWARD 1 -i gns3-mgmt -o $MGMT_IFACE -j ACCEPT
sudo iptables -I FORWARD 1 -i $MGMT_IFACE -o gns3-mgmt -j ACCEPT
"
echo "iptables: OK"

# 6. Ensure route exists on dev
if ! ip route get 172.16.0.1 2>/dev/null | grep -q "via 10.0.0.20"; then
  sudo ip route add 172.16.0.0/24 via 10.0.0.20
  echo "Route: added"
else
  echo "Route: OK"
fi

# 7. Wait for routers and verify
echo "Waiting for routers to be ready..."
sleep 15
ALL_OK=true
for ip in 172.16.0.1 172.16.0.2 172.16.0.3 172.16.0.4; do
  RESULT=$(curl -sf --connect-timeout 3 -u admin: "http://$ip/rest/system/identity" 2>&1 || echo "FAIL")
  echo "  $ip: $RESULT"
  [[ "$RESULT" == "FAIL" ]] && ALL_OK=false
done

if $ALL_OK; then
  echo ""
  echo "=== Rack ready. Restart Claude Code to reconnect MCP. ==="
else
  echo ""
  echo "=== Some routers not ready. Try again in a few seconds. ==="
fi
