#!/usr/bin/env bash
# Reports an emergency near Ojuelegba and follows it until an ambulance is assigned.
set -euo pipefail
API="${API:-http://localhost:8080}"
json() { python3 -c "import sys, json; print(json.load(sys.stdin)$1)"; }

incident_id=$(curl -sf -X POST "$API/v1/incidents" -H 'Content-Type: application/json' \
  -d '{"caller_phone":"+2348012345678","latitude":6.5097,"longitude":3.3632,"severity":5,"description":"Road accident at Ojuelegba"}' \
  | json '["incident_id"]')
echo "incident reported: $incident_id"

for _ in $(seq 1 20); do
  incident=$(curl -sf "$API/v1/incidents/$incident_id")
  if [ "$(echo "$incident" | json '["status"]')" = "DISPATCHED" ]; then
    echo "$incident" | python3 -c 'import sys, json; i = json.load(sys.stdin); print("dispatched %s: %s km away, ETA %s min" % (i["ambulance_id"], i["distance_km"], i["eta_minutes"]))'
    exit 0
  fi
  sleep 1
done
echo "incident still pending after 20s" >&2
exit 1
