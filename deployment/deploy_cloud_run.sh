#!/usr/bin/env bash
# Alternative: deploy to Cloud Run with the ADK web UI (handy for the demo).
set -euo pipefail
cd "$(dirname "$0")/.."
: "${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"
REGION="${REGION:-us-central1}"
test -f route_optimizer/.env || cp .env.example route_optimizer/.env
if grep -q "^DB_BACKEND=sqlite" route_optimizer/.env; then
  python data/generate_synthetic_data.py >/dev/null
  cp data/mclane_routing.db route_optimizer/mclane_routing.db
fi
adk deploy cloud_run \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --region "$REGION" \
  --service_name mclane-route-optimizer \
  --with_ui \
  route_optimizer
