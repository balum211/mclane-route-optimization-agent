#!/usr/bin/env bash
# Deploys the agent to Vertex AI Agent Engine (Agent Runtime), ready to be
# registered in Gemini Enterprise (see deployment/gemini_enterprise.md).
#
#   export GOOGLE_CLOUD_PROJECT=your-project REGION=us-central1
#   export DB_BACKEND=bigquery            # recommended; sqlite bundles the demo DB
#   bash deployment/deploy_agent_engine.sh
set -euo pipefail
cd "$(dirname "$0")/.."

: "${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"
REGION="${REGION:-us-central1}"
DB_BACKEND="${DB_BACKEND:-bigquery}"

if [[ ! -f route_optimizer/.env ]]; then
  cp .env.example route_optimizer/.env
  echo "Created route_optimizer/.env from .env.example; review it before deploying." >&2
fi
sed -i.bak "s/^DB_BACKEND=.*/DB_BACKEND=${DB_BACKEND}/" route_optimizer/.env && rm -f route_optimizer/.env.bak

if [[ "$DB_BACKEND" == "sqlite" ]]; then
  python data/generate_synthetic_data.py >/dev/null
  cp data/mclane_routing.db route_optimizer/mclane_routing.db
  echo "Bundled SQLite demo DB (writes are per instance and not durable)." >&2
fi

adk deploy agent_engine \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --region "$REGION" \
  --display_name "McLane Dynamic Route Optimization" \
  --description "Plans and re-plans McLane delivery routes (OR-Tools), handles disruptions, dispatches to Trimble TMW." \
  route_optimizer

echo "Copy the reasoningEngines resource name printed above into deployment/register_gemini_enterprise.sh"
