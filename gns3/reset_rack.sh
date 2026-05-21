#!/usr/bin/env bash
# Reset the GNS3 enterprise rack to the baseline snapshot.
# Run from dev: bash gns3/reset_rack.sh
#
# Use this before each test to restore a clean state:
#   hostname + mgmt IP + REST API enabled, nothing else.
set -euo pipefail

SSH="ssh andres@10.0.0.20"
GNS3_URL="http://localhost:3080"
PROJECT_ID="0e96f5f3-b28f-4ea6-a72c-84a558aa5ef5"
SNAPSHOT_ID="043fe6a7-9538-4612-85da-637623edde7c"
CLOUD_NODE_ID="359a8257-1489-45da-a51a-e1f69ddd903e"
MGMT_IFACE="enxd8bbc11e0730"

echo "=== Resetting rack to baseline snapshot ==="

# 1. Stop all nodes
$SSH "curl -s -X POST $GNS3_URL/v2/projects/$PROJECT_ID/nodes/stop > /dev/null"
sleep 3
echo "Nodes: stopped"

# 2. Restore snapshot (project must be stopped)
$SSH "curl -s -X POST $GNS3_URL/v2/projects/$PROJECT_ID/snapshots/$SNAPSHOT_ID/restore > /dev/null"
sleep 2
echo "Snapshot: restored"

# 3. Reopen project (restore closes it)
$SSH "curl -s -X POST $GNS3_URL/v2/projects/$PROJECT_ID/open > /dev/null"
sleep 2

# 4. Recreate management bridge if needed
$SSH "
if ! ip link show gns3-mgmt > /dev/null 2>&1; then
  sudo ip link add gns3-mgmt type bridge
  sudo ip addr add 172.16.0.254/24 dev gns3-mgmt
  sudo ip link set gns3-mgmt up
fi
"

# 5. Start all nodes
$SSH "curl -s -X POST $GNS3_URL/v2/projects/$PROJECT_ID/nodes/start > /dev/null"
sleep 3

# 6. Restart cloud node to attach tap to bridge
$SSH "curl -s -X POST $GNS3_URL/v2/projects/$PROJECT_ID/nodes/$CLOUD_NODE_ID/stop > /dev/null; sleep 2; curl -s -X POST $GNS3_URL/v2/projects/$PROJECT_ID/nodes/$CLOUD_NODE_ID/start > /dev/null"
sleep 2
echo "Bridge: OK"

# 7. Re-apply iptables forwarding + masquerade rules
$SSH "
sudo iptables -D FORWARD -i gns3-mgmt -o $MGMT_IFACE -j ACCEPT 2>/dev/null || true
sudo iptables -D FORWARD -i $MGMT_IFACE -o gns3-mgmt -j ACCEPT 2>/dev/null || true
sudo iptables -I FORWARD 1 -i gns3-mgmt -o $MGMT_IFACE -j ACCEPT
sudo iptables -I FORWARD 1 -i $MGMT_IFACE -o gns3-mgmt -j ACCEPT
sudo iptables -t nat -C POSTROUTING -s 10.0.0.0/24 -o gns3-mgmt -j MASQUERADE 2>/dev/null || \
sudo iptables -t nat -A POSTROUTING -s 10.0.0.0/24 -o gns3-mgmt -j MASQUERADE
"
echo "iptables: OK"

# 8. Ensure route exists on dev
if ! ip route get 172.16.0.1 2>/dev/null | grep -q "via 10.0.0.20"; then
  sudo ip route add 172.16.0.0/24 via 10.0.0.20
  echo "Route: added"
else
  echo "Route: OK"
fi

# 9. Wait for routers and verify
echo "Waiting for routers to boot..."
sleep 15
ALL_OK=true
for ip in 172.16.0.1 172.16.0.2 172.16.0.3 172.16.0.4; do
  RESULT=$(curl -sf --connect-timeout 3 -u admin:Mcp2026x "http://$ip/rest/system/identity" 2>&1 || echo "FAIL")
  echo "  $ip: $RESULT"
  [[ "$RESULT" == "FAIL" ]] && ALL_OK=false
done

if $ALL_OK; then
  echo ""
  echo "=== Rack reset to baseline. Ready for next test. ==="
else
  echo ""
  echo "=== Some routers not ready yet. Wait a few seconds and retry. ==="
fi
