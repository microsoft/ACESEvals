#!/bin/sh
set -e

echo "=== Gateway Startup ==="

# IP forwarding is enabled via docker-compose sysctl
if [ "$(cat /proc/sys/net/ipv4/ip_forward)" = "1" ]; then
    echo "✓ IP forwarding enabled"
else
    echo "✗ IP forwarding NOT enabled"
fi

# Show network interfaces
echo "=== Network Interfaces ==="
ip addr show | grep -E "inet 172.30"

# Default: Allow all forwarding (will be restricted in Phase 4)
iptables -P FORWARD ACCEPT
echo "✓ Forwarding policy: ACCEPT (Phase 2 - no restrictions)"

# Start Flask app
echo "=== Starting Gateway API ==="
exec python /app/app.py
