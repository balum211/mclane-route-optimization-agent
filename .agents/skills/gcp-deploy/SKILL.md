---
name: gcp-deploy
description: Use when deploying the route optimization agent to Google Cloud (BigQuery or AlloyDB data, Vertex AI Agent Engine, Cloud Run, Pub/Sub) or registering it in Gemini Enterprise.
---

# GCP deploy

## Goal
Get from laptop to a Gemini Enterprise agent backed by Agent Engine and cloud data, safely.

## Instructions
1. Auth: `gcloud auth login && gcloud auth application-default login`, then
   `gcloud config set project $GOOGLE_CLOUD_PROJECT`.
2. Enable APIs: `gcloud services enable aiplatform.googleapis.com bigquery.googleapis.com
   pubsub.googleapis.com discoveryengine.googleapis.com alloydb.googleapis.com
   cloudbuild.googleapis.com run.googleapis.com`.
3. Data: `python data/load_bigquery.py --project $GOOGLE_CLOUD_PROJECT --replace`, or for AlloyDB
   `python data/load_alloydb.py --replace`. Set `DB_BACKEND` in `route_optimizer/.env`.
4. Agent Engine: `bash deployment/deploy_agent_engine.sh` and note the
   `projects/.../reasoningEngines/...` name. The runtime service account needs BigQuery Data Editor
   and Job User on the dataset (or AlloyDB Client), plus Vertex AI User.
5. Gemini Enterprise: `GE_APP_ID=... REASONING_ENGINE=... bash deployment/register_gemini_enterprise.sh`
   (needs Gemini Enterprise Admin), or in the console: Gemini Enterprise > app > Agents > Add agent >
   Custom agent via Agent Runtime.
6. Events: `bash deployment/setup_pubsub.sh`, then run `python -m route_optimizer.event_bus worker`
   (Cloud Run job or GCE VM for the hackathon).
7. Smoke test in Gemini Enterprise: "Build tomorrow's plan for Temple and compare with TMW static routes."

## Constraints
- Ask the user before creating billable resources (AlloyDB, Agent Engine, Cloud Run).
- Never put secrets in `.env` files that get committed; use Secret Manager for `PG_PASSWORD` and `TMW_API_TOKEN`.
