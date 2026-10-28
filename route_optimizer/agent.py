"""McLane Dynamic Route Optimization: Google ADK multi-agent system.

    mclane_route_coordinator            (root, routes requests)
    ├── route_planner_agent             demand, fleet, optimize, what-if
    ├── disruption_agent                events: trigger > assess > re-plan > explain > approve
    ├── tms_dispatch_agent              Trimble TMW payloads and dispatch
    ├── customer_comms_agent            ETA notices to stores/restaurants
    ├── location_intelligence_agent     GPS, geofences, dwell time changes, geocodes
    └── analytics_agent                 Retail/Restaurant OTD, KPIs, savings, BigQuery NL2SQL

Run locally:   uv run adk web .     (from the repo root, as in the Antigravity codelabs)
"""

from __future__ import annotations

import logging

from google.adk.agents import LlmAgent
from google.genai import types

from . import prompts
from .config import get_settings
from .tools import (
    analytics_tools,
    comms_tools,
    data_tools,
    disruption_tools,
    event_tools,
    location_tools,
    planning_tools,
    tms_tools,
)

log = logging.getLogger(__name__)
settings = get_settings()

_precise = types.GenerateContentConfig(temperature=0.1)


def _bigquery_tools() -> list:
  """BigQuery NL2SQL tools for the analytics agent when data lives in BigQuery."""
  if settings.db_backend != "bigquery":
    return []
  try:
    import google.auth
    from google.adk.integrations.bigquery import BigQueryCredentialsConfig, BigQueryToolset
    from google.adk.integrations.bigquery.config import BigQueryToolConfig, WriteMode

    creds, _ = google.auth.default()
    return [
        BigQueryToolset(
            credentials_config=BigQueryCredentialsConfig(credentials=creds),
            bigquery_tool_config=BigQueryToolConfig(
                write_mode=WriteMode.BLOCKED,
                default_project_id=settings.bq_project or None,
                default_dataset_id=settings.bq_dataset,
                application_name="mclane-route-optimizer",
            ),
            tool_filter=["execute_sql", "get_table_info", "list_table_ids"],
        )
    ]
  except Exception as e:  # never block the agent on optional tooling
    log.warning("BigQuery toolset disabled: %s", e)
    return []


def _toolbox_tools() -> list:
  """Read-only MCP Toolbox tools (tools.yaml) when a Toolbox server is running at TOOLBOX_URL."""
  url = settings.toolbox_url
  if not url:
    return []
  client = None
  try:
    from toolbox_core import ToolboxSyncClient

    client = ToolboxSyncClient(url)
    return list(client.load_toolset(settings.toolbox_toolset))
  except Exception as e:  # never block the agent on optional tooling
    log.warning("MCP Toolbox tools disabled (%s): %s", url, e)
    if client is not None:
      client.close()
    return []


route_planner_agent = LlmAgent(
    name="route_planner_agent",
    model=settings.coordinator_model,
    description="Builds optimized delivery plans for a DC and date, runs what-if scenarios and compares with TMW static routes.",
    instruction=prompts.ROUTE_PLANNER,
    tools=[
        data_tools.get_delivery_demand,
        data_tools.get_fleet_availability,
        data_tools.get_customer_profile,
        planning_tools.optimize_routes,
        planning_tools.run_what_if_scenarios,
        planning_tools.get_route_plan,
    ],
    generate_content_config=_precise,
)

disruption_agent = LlmAgent(
    name="disruption_agent",
    model=settings.specialist_model,
    description=(
        "Handles real-time events (delays, breakdowns, added or cancelled orders, closures, no-shows, reefer alerts, "
        "geofence dwell overruns): "
        "re-plans only affected routes, explains changes, escalates to a dispatcher when needed."
    ),
    instruction=prompts.DISRUPTION,
    tools=[
        event_tools.list_route_events,
        event_tools.handle_route_event,
        event_tools.simulate_route_event,
        event_tools.get_pending_escalations,
        event_tools.decide_replan_tool,
        data_tools.get_active_disruptions,
        disruption_tools.assess_disruption_impact,
        disruption_tools.reoptimize_route_in_flight,
        location_tools.get_vehicle_locations,
        planning_tools.get_route_plan,
    ],
    generate_content_config=_precise,
)

tms_dispatch_agent = LlmAgent(
    name="tms_dispatch_agent",
    model=settings.specialist_model,
    description="Previews and submits approved plans to Trimble TMW and reports dispatch status.",
    instruction=prompts.TMS_DISPATCH,
    tools=[
        tms_tools.build_tmw_dispatch_payload,
        tms_tools.submit_plan_to_tmw_tool,
        tms_tools.get_dispatch_status,
    ],
    generate_content_config=_precise,
)

customer_comms_agent = LlmAgent(
    name="customer_comms_agent",
    model=settings.specialist_model,
    description="Drafts and sends ETA notices to stores and restaurants for a plan.",
    instruction=prompts.CUSTOMER_COMMS,
    tools=[comms_tools.draft_eta_notifications, comms_tools.send_eta_notifications_tool],
    generate_content_config=_precise,
)

location_intelligence_agent = LlmAgent(
    name="location_intelligence_agent",
    model=settings.specialist_model,
    description=(
        "Truck GPS positions, geofence arrivals and departures, dwell time and dwell time changes, customer "
        "geolocation (geocode) checks, and the TMW master-data fixes that follow."
    ),
    instruction=prompts.LOCATION_INTELLIGENCE,
    tools=[
        location_tools.get_vehicle_locations,
        location_tools.detect_geofence_events,
        location_tools.analyze_dwell_time_changes,
        location_tools.validate_customer_geolocations,
        location_tools.apply_master_data_updates_tool,
        data_tools.get_customer_profile,
    ],
    generate_content_config=_precise,
)

analytics_agent = LlmAgent(
    name="analytics_agent",
    model=settings.specialist_model,
    description="Retail and Restaurant on-time delivery (OTD), delivery KPIs, unload-time gaps, savings history and network roll-ups.",
    instruction=prompts.ANALYTICS,
    tools=[
        analytics_tools.get_otd_by_segment,
        analytics_tools.get_delivery_kpis,
        analytics_tools.list_optimization_runs,
        analytics_tools.get_network_savings_summary,
        *_bigquery_tools(),
        *_toolbox_tools(),
    ],
    generate_content_config=_precise,
)

root_agent = LlmAgent(
    name="mclane_route_coordinator",
    model=settings.coordinator_model,
    description="McLane dynamic route optimization coordinator for dispatchers and transportation managers.",
    instruction=prompts.COORDINATOR,
    tools=[data_tools.list_distribution_centers],
    sub_agents=[
        route_planner_agent,
        disruption_agent,
        tms_dispatch_agent,
        customer_comms_agent,
        location_intelligence_agent,
        analytics_agent,
    ],
    generate_content_config=_precise,
)
