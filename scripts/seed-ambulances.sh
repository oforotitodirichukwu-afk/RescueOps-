#!/usr/bin/env bash
# Registers a fleet of ambulances at real Lagos locations.
set -euo pipefail
API="${API:-http://localhost:8080}"

while read -r id lat lon area; do
  curl -sf -X POST "$API/v1/ambulances" -H 'Content-Type: application/json' \
    -d "{\"ambulance_id\":\"$id\",\"latitude\":$lat,\"longitude\":$lon}" >/dev/null
  echo "registered $id ($area)"
done <<'EOF'
LAG-AMB-001 6.6018 3.3515 Ikeja
LAG-AMB-002 6.5095 3.3711 Yaba
LAG-AMB-003 6.4478 3.4723 Lekki-Phase-1
LAG-AMB-004 6.5005 3.3581 Surulere
LAG-AMB-005 6.4281 3.4219 Victoria-Island
EOF
