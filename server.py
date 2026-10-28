"""FastAPI server wrapping the ADK agents, as in the sdd-adk-antigravity codelab starter.

Serves the ADK dev UI and the ADK REST endpoints (/run, /run_sse,
/apps/{app_name}/users/{user_id}/sessions) for route_optimizer with in-memory
sessions. For production use Vertex AI Agent Engine (deployment/).

  uv run uvicorn server:app --host 0.0.0.0 --port 8080
"""

import os

import uvicorn
from google.adk.cli.fast_api import get_fast_api_app

app = get_fast_api_app(agents_dir=os.path.dirname(os.path.abspath(__file__)), web=True)

if __name__ == "__main__":
  port = int(os.environ.get("PORT", 8080))
  uvicorn.run("server:app", host="0.0.0.0", port=port)
