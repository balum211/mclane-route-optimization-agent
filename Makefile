.PHONY: install data test web api load-bq load-alloydb deploy-agent-engine deploy-cloud-run events-demo

install:
	uv sync || pip install -r requirements.txt pytest

data:
	python data/generate_synthetic_data.py

test: data
	python -m pytest -q

web: data
	adk web .

api: data
	adk api_server .

load-bq:
	python data/load_bigquery.py --project $(GOOGLE_CLOUD_PROJECT) --replace

load-alloydb:
	python data/load_alloydb.py --replace

events-demo: data
	python -m route_optimizer.event_bus local --file scripts/sample_events/breakdown.json --no-llm

deploy-agent-engine:
	bash deployment/deploy_agent_engine.sh

deploy-cloud-run:
	bash deployment/deploy_cloud_run.sh
