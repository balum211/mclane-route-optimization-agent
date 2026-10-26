#!/usr/bin/env bash
# Registers the Agent Engine deployment as a custom agent in a Gemini Enterprise app.
# Requires the Gemini Enterprise Admin role and the Discovery Engine API.
#
#   export GOOGLE_CLOUD_PROJECT=your-project
#   export GE_APP_ID=your-gemini-enterprise-app-id
#   export GE_LOCATION=global                       # global | us | eu (app location)
#   export REASONING_ENGINE=projects/123/locations/us-central1/reasoningEngines/456
#   bash deployment/register_gemini_enterprise.sh
set -euo pipefail
: "${GOOGLE_CLOUD_PROJECT:?}" "${GE_APP_ID:?}" "${REASONING_ENGINE:?}"
GE_LOCATION="${GE_LOCATION:-global}"
if [[ "$GE_LOCATION" == "global" ]]; then HOST="discoveryengine.googleapis.com"; else HOST="${GE_LOCATION}-discoveryengine.googleapis.com"; fi

curl -sS -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  -H "X-Goog-User-Project: ${GOOGLE_CLOUD_PROJECT}" \
  "https://${HOST}/v1alpha/projects/${GOOGLE_CLOUD_PROJECT}/locations/${GE_LOCATION}/collections/default_collection/engines/${GE_APP_ID}/assistants/default_assistant/agents" \
  -d @- <<JSON
{
  "displayName": "McLane Route Optimizer",
  "description": "Builds optimized daily delivery routes for McLane DCs, compares them with Trimble TMW static routes, re-plans in real time when trucks are delayed or break down, orders change or roads close, explains every change and escalates to a dispatcher when needed.",
  "adkAgentDefinition": {
    "provisionedReasoningEngine": { "reasoningEngine": "${REASONING_ENGINE}" }
  }
}
JSON
echo
