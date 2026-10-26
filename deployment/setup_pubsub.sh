#!/usr/bin/env bash
# Creates the event topic and the agent's pull subscription.
# Optional: a BigQuery subscription that lands every raw event in a table for analytics.
set -euo pipefail
: "${GOOGLE_CLOUD_PROJECT:?}"
TOPIC="${PUBSUB_TOPIC:-mclane-route-events}"
SUB="${PUBSUB_SUBSCRIPTION:-mclane-route-events-agent}"
gcloud pubsub topics create "$TOPIC" --project "$GOOGLE_CLOUD_PROJECT" || true
gcloud pubsub subscriptions create "$SUB" --topic "$TOPIC" --project "$GOOGLE_CLOUD_PROJECT" \
  --ack-deadline 60 --min-retry-delay 10s --max-retry-delay 120s || true
echo "Publish a test event: python -m route_optimizer.event_bus publish --file scripts/sample_events/breakdown.json"
echo "Run the worker:       python -m route_optimizer.event_bus worker"
