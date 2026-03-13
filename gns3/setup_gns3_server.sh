#!/usr/bin/env bash
# Install and configure GNS3 server + QEMU on mvp-server (10.0.0.20).
# Run from dev machine: ssh andres@10.0.0.20 'bash -s' < gns3/setup_gns3_server.sh
set -euo pipefail

echo "=== Installing GNS3 server + QEMU on $(hostname) ==="

# Add GNS3 PPA and install
sudo add-apt-repository ppa:gns3/ppa -y
sudo apt update
sudo apt install -y gns3-server qemu-system-x86 qemu-utils

# Add user to required groups
sudo usermod -aG kvm,libvirt "$USER"

# Enable and start GNS3 service
sudo systemctl enable --now gns3

# Configure GNS3 to listen on all interfaces
GNS3_CONF="$HOME/.config/GNS3/gns3_server.conf"
mkdir -p "$(dirname "$GNS3_CONF")"
if [ ! -f "$GNS3_CONF" ]; then
    cat > "$GNS3_CONF" << 'EOF'
[Server]
host = 0.0.0.0
port = 3080
EOF
    echo "Created GNS3 config: $GNS3_CONF"
    sudo systemctl restart gns3
else
    echo "GNS3 config already exists: $GNS3_CONF"
    echo "Ensure host = 0.0.0.0 is set for remote access."
fi

# Download and prepare CHR image
echo ""
echo "=== Preparing MikroTik CHR image ==="
mkdir -p ~/gns3-images
cd ~/gns3-images

if [ ! -f chr-7.16.qcow2 ]; then
    wget -q https://download.mikrotik.com/routeros/7.16/chr-7.16.img.zip
    unzip -o chr-7.16.img.zip
    qemu-img convert -f raw -O qcow2 chr-7.16.img chr-7.16.qcow2
    rm -f chr-7.16.img chr-7.16.img.zip
    echo "CHR image ready: ~/gns3-images/chr-7.16.qcow2"
else
    echo "CHR image already exists: ~/gns3-images/chr-7.16.qcow2"
fi

# Wait for GNS3 to be ready
echo ""
echo "=== Waiting for GNS3 server ==="
for i in $(seq 1 10); do
    if curl -sf http://localhost:3080/v2/version > /dev/null 2>&1; then
        echo "GNS3 server is running."
        curl -s http://localhost:3080/v2/version | python3 -m json.tool
        break
    fi
    echo "  Waiting... ($i/10)"
    sleep 3
done

# Upload CHR image to GNS3
echo ""
echo "=== Uploading CHR image to GNS3 ==="
curl -s -X POST "http://localhost:3080/v2/computes/local/qemu/images/chr-7.16.qcow2" \
    --data-binary @~/gns3-images/chr-7.16.qcow2 \
    -o /dev/null -w "Upload status: %{http_code}\n"

# Create QEMU template
echo ""
echo "=== Creating QEMU template ==="
curl -s -X POST "http://localhost:3080/v2/templates" \
    -H "Content-Type: application/json" \
    -d '{
  "name": "MikroTik CHR 7.16",
  "template_type": "qemu",
  "compute_id": "local",
  "qemu_path": "/usr/bin/qemu-system-x86_64",
  "ram": 256,
  "cpus": 1,
  "hda_disk_image": "chr-7.16.qcow2",
  "hda_disk_interface": "virtio",
  "adapters": 5,
  "adapter_type": "virtio-net-pci",
  "boot_priority": "c",
  "console_type": "telnet",
  "platform": "x86_64"
}' | python3 -m json.tool

# Create management bridge
echo ""
echo "=== Setting up management bridge ==="
if ! ip link show gns3-mgmt > /dev/null 2>&1; then
    sudo ip link add gns3-mgmt type bridge
    sudo ip addr add 172.16.0.254/24 dev gns3-mgmt
    sudo ip link set gns3-mgmt up
    echo "Management bridge gns3-mgmt created (172.16.0.254/24)"
else
    echo "Management bridge gns3-mgmt already exists"
fi

echo ""
echo "=== Setup complete ==="
echo "Next steps:"
echo "  1. From dev (10.0.0.21): sudo ip route add 172.16.0.0/24 via 10.0.0.20"
echo "  2. From dev: python gns3/create_topology.py"
echo "  3. Wait ~60s, then: python gns3/bootstrap_routers.py"
