.PHONY: install data test web api serve demo toolbox load-bq load-alloydb deploy-agent-engine deploy-cloud-run events-demo

install:
	uv sync || pip install -r requirements.txt pytest

data:
	uv run python data/generate_synthetic_data.py

test: data
	uv run pytest -q

web: data
	uv run adk web .

api: data
	uv run adk api_server .

load-bq:
	uv run python data/load_bigquery.py --project $(GOOGLE_CLOUD_PROJECT) --replace

load-alloydb:
	uv run python data/load_alloydb.py --replace

events-demo: data
	uv run python -m route_optimizer.event_bus local --file scripts/sample_events/breakdown.json --no-llm

deploy-agent-engine:
	bash deployment/deploy_agent_engine.sh

deploy-cloud-run:
	bash deployment/deploy_cloud_run.sh

serve: data
	uv run uvicorn server:app --host 0.0.0.0 --port 8080

demo: data
	uv run python scripts/demo_run.py

toolbox:
	toolbox --tools-file tools.yaml
