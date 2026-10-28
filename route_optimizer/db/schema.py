"""Single source of truth for the synthetic McLane routing data model.

Every backend (SQLite for local dev, BigQuery, AlloyDB for PostgreSQL) is
rendered from this definition, so the generator, the loaders and the agent
tools never drift apart.

Conventions
-----------
* Times of day are stored as integer minutes after midnight (``*_min``) so the
  same SQL works on all three engines and feeds the OR-Tools time dimension
  directly.  For example 05:30 is 330.
* Dates are DATE columns (ISO strings in SQLite).
* Columns prefixed ``tmw_`` mirror the identifiers Trimble TMW.Suite uses
  (order header number, movement, leg header, company id) so plans can be
  round-tripped to the TMS.
"""

from __future__ import annotations

from dataclasses import dataclass

# Logical type -> per-engine type.
_TYPES = {
    "STRING": {"sqlite": "TEXT", "postgres": "TEXT", "bigquery": "STRING"},
    "INT": {"sqlite": "INTEGER", "postgres": "BIGINT", "bigquery": "INT64"},
    "FLOAT": {"sqlite": "REAL", "postgres": "DOUBLE PRECISION", "bigquery": "FLOAT64"},
    "BOOL": {"sqlite": "INTEGER", "postgres": "BOOLEAN", "bigquery": "BOOL"},
    "DATE": {"sqlite": "TEXT", "postgres": "DATE", "bigquery": "DATE"},
    "TIMESTAMP": {"sqlite": "TEXT", "postgres": "TIMESTAMPTZ", "bigquery": "TIMESTAMP"},
    "JSON": {"sqlite": "TEXT", "postgres": "JSONB", "bigquery": "JSON"},
}


@dataclass(frozen=True)
class Column:
  name: str
  type: str
  description: str
  required: bool = False


@dataclass(frozen=True)
class Table:
  name: str
  description: str
  columns: tuple[Column, ...]
  primary_key: tuple[str, ...] = ()

  @property
  def column_names(self) -> list[str]:
    return [c.name for c in self.columns]


def _c(name, type_, description, required=False):
  return Column(name, type_, description, required)


TABLES: tuple[Table, ...] = (
    Table(
        "distribution_centers",
        "McLane distribution centers (DCs) that originate delivery routes.",
        (
            _c("dc_id", "STRING", "DC identifier, e.g. DC-TEMPLE-TX", True),
            _c("name", "STRING", "Display name"),
            _c("business_unit", "STRING", "GROCERY (convenience/retail) or FOODSERVICE (restaurants)"),
            _c("city", "STRING", "City"),
            _c("state", "STRING", "State code"),
            _c("lat", "FLOAT", "Latitude"),
            _c("lon", "FLOAT", "Longitude"),
            _c("dock_doors", "INT", "Outbound dock doors"),
            _c("dispatch_start_min", "INT", "Earliest truck departure, minutes after midnight"),
            _c("dispatch_end_min", "INT", "Latest truck departure, minutes after midnight"),
            _c("timezone", "STRING", "IANA timezone"),
        ),
        ("dc_id",),
    ),
    Table(
        "customers",
        "Retail stores and restaurants served by a DC (TMW company profile).",
        (
            _c("customer_id", "STRING", "Customer / ship-to id", True),
            _c("tmw_cmp_id", "STRING", "Trimble TMW company id (cmp_id)"),
            _c("dc_id", "STRING", "Servicing DC", True),
            _c("name", "STRING", "Store or restaurant name"),
            _c("banner", "STRING", "Chain banner"),
            _c("segment", "STRING", "CONVENIENCE, GROCERY, MASS_MERCHANT, QSR, CASUAL_DINING"),
            _c("address", "STRING", "Street address (synthetic)"),
            _c("city", "STRING", "City"),
            _c("state", "STRING", "State"),
            _c("lat", "FLOAT", "Latitude of the delivery point (TMW company master data)"),
            _c("lon", "FLOAT", "Longitude of the delivery point (TMW company master data)"),
            _c("geocode_source", "STRING", "Where lat/lon came from: ADDRESS_ROOFTOP, ZIP_CENTROID, GPS_LEARNED"),
            _c("geocode_confidence", "STRING", "HIGH, MEDIUM, LOW"),
            _c("window_start_min", "INT", "Receiving window open, minutes after midnight"),
            _c("window_end_min", "INT", "Receiving window close, minutes after midnight"),
            _c("std_service_min", "INT", "Standard unload time in minutes (TMS master data)"),
            _c("hard_window", "BOOL", "Dock appointment: window close is a hard constraint"),
            _c("key_drop", "BOOL", "Unattended key-drop delivery allowed"),
            _c("requires_liftgate", "BOOL", "Site needs a liftgate / straight truck"),
            _c("max_vehicle_length_ft", "INT", "Longest vehicle the site can take"),
            _c("priority_tier", "INT", "1 = strategic account, 3 = standard"),
            _c("delivery_days", "STRING", "Scheduled delivery days, e.g. MON,WED,FRI"),
        ),
        ("customer_id",),
    ),
    Table(
        "geofences",
        "Circular geofences around each customer delivery point and each DC yard, used to detect arrivals and departures from GPS.",
        (
            _c("geofence_id", "STRING", "Geofence id", True),
            _c("entity_type", "STRING", "CUSTOMER or DC"),
            _c("entity_id", "STRING", "customer_id or dc_id", True),
            _c("dc_id", "STRING", "Distribution center id"),
            _c("center_lat", "FLOAT", "Centre latitude"),
            _c("center_lon", "FLOAT", "Centre longitude"),
            _c("radius_m", "INT", "Radius in meters"),
            _c("source", "STRING", "MASTER_DATA (centred on TMW lat/lon) or GPS_LEARNED"),
            _c("active", "BOOL", "Used by the geofence engine"),
        ),
        ("geofence_id",),
    ),
    Table(
        "otd_policies",
        "On-time delivery (OTD) definitions for Retail and Restaurant customers.",
        (
            _c("segment_group", "STRING", "RETAIL (c-store, grocery, mass merchant) or RESTAURANT (QSR, casual dining)", True),
            _c("segments", "STRING", "Customer segments in the group, comma separated"),
            _c("measure_against", "STRING", "RECEIVING_WINDOW or SCHEDULED_TIME"),
            _c("early_tolerance_min", "INT", "Minutes before the window or scheduled time still counted on time (NULL = early is fine)"),
            _c("late_tolerance_min", "INT", "Minutes after the window close or scheduled time still counted on time"),
            _c("target_pct", "FLOAT", "OTD target in percent"),
            _c("arrival_event", "STRING", "What timestamps the arrival: GEOFENCE_ENTRY, falling back to DRIVER_APP"),
            _c("description", "STRING", "Plain-language definition"),
        ),
        ("segment_group",),
    ),
    Table(
        "tractors",
        "Power units (TMW tractor profile).",
        (
            _c("tractor_id", "STRING", "Tractor id", True),
            _c("dc_id", "STRING", "Home DC", True),
            _c("unit_type", "STRING", "TRACTOR or STRAIGHT_TRUCK"),
            _c("mpg", "FLOAT", "Average fuel economy"),
            _c("status", "STRING", "AVAILABLE, MAINTENANCE"),
        ),
        ("tractor_id",),
    ),
    Table(
        "trailers",
        "Trailers / bodies with capacity by temperature class.",
        (
            _c("trailer_id", "STRING", "Trailer id", True),
            _c("dc_id", "STRING", "Home DC", True),
            _c("trailer_type", "STRING", "MULTI_TEMP (3-compartment reefer), DRY, STRAIGHT_REEFER"),
            _c("length_ft", "INT", "Length in feet"),
            _c("capacity_cases", "INT", "Total case capacity"),
            _c("capacity_cold_cases", "INT", "Chilled + frozen case capacity (0 for dry vans)"),
            _c("capacity_lbs", "INT", "Payload weight limit"),
            _c("capacity_cube", "INT", "Cubic feet"),
            _c("has_liftgate", "BOOL", "Liftgate fitted"),
            _c("status", "STRING", "AVAILABLE, MAINTENANCE"),
        ),
        ("trailer_id",),
    ),
    Table(
        "drivers",
        "Drivers with hours-of-service (HOS) availability.",
        (
            _c("driver_id", "STRING", "Driver id (TMW mpp_id)", True),
            _c("dc_id", "STRING", "Home DC", True),
            _c("name", "STRING", "Synthetic name"),
            _c("hos_drive_remaining_min", "INT", "Remaining driving minutes today (11h rule)"),
            _c("hos_duty_remaining_min", "INT", "Remaining on-duty minutes today (14h rule)"),
            _c("shift_start_min", "INT", "Earliest start, minutes after midnight"),
            _c("cdl_class", "STRING", "A or B"),
            _c("status", "STRING", "AVAILABLE, PTO"),
        ),
        ("driver_id",),
    ),
    Table(
        "orders",
        "Delivery orders for upcoming days (TMW order header).",
        (
            _c("order_id", "STRING", "Order id", True),
            _c("tmw_ord_hdrnumber", "INT", "TMW ord_hdrnumber"),
            _c("dc_id", "STRING", "Originating DC", True),
            _c("customer_id", "STRING", "Ship-to customer", True),
            _c("delivery_date", "DATE", "Requested delivery date", True),
            _c("dry_cases", "INT", "Ambient cases"),
            _c("chill_cases", "INT", "Refrigerated cases"),
            _c("frozen_cases", "INT", "Frozen cases"),
            _c("weight_lbs", "INT", "Gross weight"),
            _c("cube_ft3", "FLOAT", "Cubic feet"),
            _c("priority", "STRING", "STANDARD, HOT (must deliver), FLEX (can move a day)"),
            _c("status", "STRING", "OPEN, PLANNED, DISPATCHED, DELIVERED"),
        ),
        ("order_id",),
    ),
    Table(
        "routes",
        "Route headers. TMW_STATIC = today's fixed routes in TMW; AI_OPTIMIZED = agent output.",
        (
            _c("route_id", "STRING", "Route id", True),
            _c("plan_id", "STRING", "Optimization plan id (NULL for static routes)"),
            _c("source", "STRING", "TMW_STATIC or AI_OPTIMIZED"),
            _c("dc_id", "STRING", "Distribution center id", True),
            _c("route_date", "DATE", "Delivery date", True),
            _c("tractor_id", "STRING", "Assigned tractor"),
            _c("trailer_id", "STRING", "Assigned trailer"),
            _c("driver_id", "STRING", "Assigned driver"),
            _c("depart_min", "INT", "Planned DC departure"),
            _c("return_min", "INT", "Planned DC return"),
            _c("stop_count", "INT", "Number of stops"),
            _c("total_miles", "FLOAT", "Planned road miles from the routing matrix"),
            _c("pcmiler_miles", "FLOAT", "Trimble PC*MILER miles for the stop sequence (mileage of record in TMW)"),
            _c("mileage_source", "STRING", "PCMILER (live API) or PCMILER_EMULATED (offline estimate)"),
            _c("total_duration_min", "INT", "Planned duration"),
            _c("total_cases", "INT", "Cases on board"),
            _c("est_cost_usd", "FLOAT", "Estimated cost"),
            _c("late_stops", "INT", "Stops arriving after window close"),
            _c("status", "STRING", "PLANNED, DISPATCHED, IN_PROGRESS, COMPLETE"),
        ),
        ("route_id",),
    ),
    Table(
        "route_stops",
        "Stop sequence for each route (TMW stops).",
        (
            _c("route_id", "STRING", "Route id", True),
            _c("stop_seq", "INT", "1-based sequence", True),
            _c("order_id", "STRING", "Order delivered"),
            _c("customer_id", "STRING", "Customer"),
            _c("eta_min", "INT", "Planned arrival, minutes after midnight"),
            _c("etd_min", "INT", "Planned departure"),
            _c("miles_from_prev", "FLOAT", "Leg miles"),
            _c("pcmiler_leg_miles", "FLOAT", "PC*MILER leg miles from the previous stop"),
            _c("window_ok", "BOOL", "Arrival inside the receiving window"),
        ),
        ("route_id", "stop_seq"),
    ),
    Table(
        "delivery_history",
        "Last 60 days of completed deliveries with geofence arrival/departure, used to learn dwell time and measure OTD.",
        (
            _c("delivery_id", "STRING", "Delivery id", True),
            _c("customer_id", "STRING", "Customer", True),
            _c("dc_id", "STRING", "Distribution center id"),
            _c("delivery_date", "DATE", "Date"),
            _c("tractor_id", "STRING", "Truck that delivered"),
            _c("planned_arrival_min", "INT", "Scheduled arrival in the dispatched plan"),
            _c("actual_arrival_min", "INT", "Actual arrival (geofence entry, or driver app when the geofence missed)"),
            _c("actual_departure_min", "INT", "Actual departure (geofence exit, or driver app)"),
            _c("arrival_source", "STRING", "GEOFENCE or DRIVER_APP"),
            _c("dwell_min", "INT", "Time on site: departure minus arrival"),
            _c("gps_stop_lat", "FLOAT", "Latitude where the truck actually parked (telematics stop detection)"),
            _c("gps_stop_lon", "FLOAT", "Longitude where the truck actually parked"),
            _c("cases", "INT", "Cases delivered"),
            _c("on_time", "BOOL", "On time under the Retail or Restaurant OTD policy of the customer"),
            _c("exception_code", "STRING", "NONE, TRAFFIC, WEATHER, DOCK_BUSY, LATE_DISPATCH, REFUSED"),
        ),
        ("delivery_id",),
    ),
    Table(
        "traffic_events",
        "Traffic incidents, closures and congestion (simulated feed, e.g. from Maps/511).",
        (
            _c("event_id", "STRING", "Event id", True),
            _c("event_date", "DATE", "Date", True),
            _c("event_type", "STRING", "CLOSURE, ACCIDENT, CONSTRUCTION, CONGESTION"),
            _c("corridor", "STRING", "Road, e.g. I-35 N"),
            _c("description", "STRING", "Human readable description"),
            _c("lat", "FLOAT", "Centre latitude"),
            _c("lon", "FLOAT", "Centre longitude"),
            _c("radius_miles", "FLOAT", "Affected radius"),
            _c("start_min", "INT", "Start, minutes after midnight"),
            _c("end_min", "INT", "End, minutes after midnight"),
            _c("delay_factor", "FLOAT", "Travel-time multiplier inside the radius"),
        ),
        ("event_id",),
    ),
    Table(
        "weather_events",
        "Weather alerts affecting delivery regions.",
        (
            _c("event_id", "STRING", "Event id", True),
            _c("event_date", "DATE", "Date", True),
            _c("alert_type", "STRING", "THUNDERSTORM, ICE, HEAT, FLOOD, WIND"),
            _c("severity", "STRING", "ADVISORY, WATCH, WARNING"),
            _c("description", "STRING", "Description"),
            _c("lat", "FLOAT", "Centre latitude"),
            _c("lon", "FLOAT", "Centre longitude"),
            _c("radius_miles", "FLOAT", "Affected radius"),
            _c("start_min", "INT", "Start"),
            _c("end_min", "INT", "End"),
            _c("speed_factor", "FLOAT", "Travel-time multiplier"),
        ),
        ("event_id",),
    ),
    Table(
        "route_events",
        "Real-time operational events (telematics, driver app, TMS, traffic feed), as published to Pub/Sub.",
        (
            _c("event_id", "STRING", "Event id", True),
            _c("dc_id", "STRING", "Distribution center id", True),
            _c("event_date", "DATE", "Operating date", True),
            _c("event_min", "INT", "Time the event happened, minutes after midnight"),
            _c("event_type", "STRING", "DELAY, BREAKDOWN, ORDER_ADDED, ORDER_CANCELLED, ROAD_CLOSURE, NO_SHOW, REEFER_TEMP_ALERT, DWELL_OVERRUN"),
            _c("source", "STRING", "TELEMATICS, GEOFENCE, DRIVER_APP, TMS, TRAFFIC_FEED, CUSTOMER"),
            _c("tractor_id", "STRING", "Truck involved (resolves to its route in any plan)"),
            _c("customer_id", "STRING", "Customer involved"),
            _c("order_id", "STRING", "Order involved"),
            _c("delay_min", "INT", "Reported delay in minutes"),
            _c("lat", "FLOAT", "Event latitude"),
            _c("lon", "FLOAT", "Event longitude"),
            _c("radius_miles", "FLOAT", "Affected radius (closures)"),
            _c("delay_factor", "FLOAT", "Travel-time multiplier (closures)"),
            _c("payload", "JSON", "Extra fields, e.g. cases for an added order or reefer temperature"),
            _c("description", "STRING", "What happened"),
        ),
        ("event_id",),
    ),
    Table(
        "event_actions",
        "Every re-plan the agent proposed or applied in response to an event (audit log).",
        (
            _c("action_id", "STRING", "Action id", True),
            _c("event_id", "STRING", "Triggering event"),
            _c("source_plan_id", "STRING", "Plan that was disrupted"),
            _c("new_plan_id", "STRING", "Plan holding the re-planned routes"),
            _c("affected_routes", "JSON", "Routes re-planned"),
            _c("untouched_routes", "INT", "Routes left exactly as they were"),
            _c("cost_impact_usd", "FLOAT", "Cost of the new plan minus the original plan for the affected work"),
            _c("late_stops_before", "INT", "Late or failed stops if nothing is changed"),
            _c("late_stops_after", "INT", "Late stops after re-plan"),
            _c("requires_approval", "BOOL", "Escalated to a human dispatcher"),
            _c("escalation_reasons", "JSON", "Why it was escalated"),
            _c("status", "STRING", "AUTO_APPLIED, PENDING_APPROVAL, NO_ACTION"),
            _c("explanation", "STRING", "Plain-language summary for dispatchers"),
            _c("latency_s", "FLOAT", "Seconds from event intake to re-plan"),
            _c("created_at", "TIMESTAMP", "Created"),
        ),
        ("action_id",),
    ),
    Table(
        "replan_approvals",
        "Dispatcher decisions on escalated re-plans.",
        (
            _c("approval_id", "STRING", "Approval id", True),
            _c("action_id", "STRING", "Action decided"),
            _c("decision", "STRING", "APPROVED or REJECTED"),
            _c("decided_by", "STRING", "User"),
            _c("notes", "STRING", "Notes"),
            _c("created_at", "TIMESTAMP", "Created"),
        ),
        ("approval_id",),
    ),
    Table(
        "cost_parameters",
        "Per-DC cost model used to price routes.",
        (
            _c("dc_id", "STRING", "Distribution center id", True),
            _c("cost_per_mile_usd", "FLOAT", "Variable cost per mile (fuel excluded)"),
            _c("fuel_price_usd_gal", "FLOAT", "Diesel price"),
            _c("driver_cost_per_hour_usd", "FLOAT", "Loaded driver wage"),
            _c("overtime_multiplier", "FLOAT", "Multiplier after 10 hours"),
            _c("fixed_cost_per_route_usd", "FLOAT", "Fixed cost of dispatching a truck"),
            _c("late_penalty_usd", "FLOAT", "Service penalty per late stop"),
            _c("co2_kg_per_gal", "FLOAT", "CO2 per gallon of diesel"),
        ),
        ("dc_id",),
    ),
    Table(
        "optimization_runs",
        "Audit log of every optimization run made by the agent.",
        (
            _c("plan_id", "STRING", "Plan id", True),
            _c("dc_id", "STRING", "Distribution center id"),
            _c("route_date", "DATE", "Delivery date"),
            _c("scenario", "STRING", "BASE, WHAT_IF, REOPTIMIZE"),
            _c("parameters", "JSON", "Solver parameters"),
            _c("orders_planned", "INT", "Orders routed"),
            _c("orders_dropped", "INT", "Orders the solver could not fit"),
            _c("routes_used", "INT", "Trucks used"),
            _c("total_miles", "FLOAT", "Miles"),
            _c("pcmiler_miles", "FLOAT", "PC*MILER miles of the plan"),
            _c("total_cost_usd", "FLOAT", "Cost"),
            _c("baseline_miles", "FLOAT", "TMW static plan miles"),
            _c("baseline_pcmiler_miles", "FLOAT", "TMW static plan PC*MILER miles"),
            _c("baseline_cost_usd", "FLOAT", "TMW static plan cost"),
            _c("late_stops", "INT", "Late stops"),
            _c("co2_kg", "FLOAT", "Estimated CO2"),
            _c("created_at", "TIMESTAMP", "Created"),
        ),
        ("plan_id",),
    ),
    Table(
        "tmw_dispatch_queue",
        "Outbound messages to Trimble TMW (simulated integration queue).",
        (
            _c("message_id", "STRING", "Message id", True),
            _c("plan_id", "STRING", "Plan id"),
            _c("route_id", "STRING", "Route id"),
            _c("message_type", "STRING", "CREATE_MOVEMENT, UPDATE_STOPS, CANCEL, COMPANY_UPDATE"),
            _c("payload", "JSON", "TMW-shaped payload"),
            _c("status", "STRING", "QUEUED, SENT, ACKED, FAILED"),
            _c("created_at", "TIMESTAMP", "Created"),
        ),
        ("message_id",),
    ),
    Table(
        "customer_notifications",
        "ETA notifications sent to stores and restaurants.",
        (
            _c("notification_id", "STRING", "Notification id", True),
            _c("plan_id", "STRING", "Plan id"),
            _c("customer_id", "STRING", "Customer"),
            _c("channel", "STRING", "SMS, EMAIL, EDI_214"),
            _c("message", "STRING", "Message body"),
            _c("status", "STRING", "DRAFT, SENT"),
            _c("created_at", "TIMESTAMP", "Created"),
        ),
        ("notification_id",),
    ),
    Table(
        "gps_pings",
        "Truck telematics breadcrumbs (ELD / GPS), one row per position report.",
        (
            _c("ping_id", "STRING", "Ping id", True),
            _c("dc_id", "STRING", "Distribution center id", True),
            _c("ping_date", "DATE", "Operating date", True),
            _c("ping_min", "INT", "Report time, minutes after midnight"),
            _c("tractor_id", "STRING", "Tractor reporting", True),
            _c("route_id", "STRING", "Route the truck is running (as dispatched in TMW)"),
            _c("lat", "FLOAT", "Latitude"),
            _c("lon", "FLOAT", "Longitude"),
            _c("speed_mph", "FLOAT", "Speed in mph"),
        ),
        ("ping_id",),
    ),
    Table(
        "geofence_events",
        "Arrivals and departures detected by the geofence engine from GPS pings.",
        (
            _c("geofence_event_id", "STRING", "Visit id (one row per geofence visit)", True),
            _c("dc_id", "STRING", "Distribution center id"),
            _c("event_date", "DATE", "Operating date"),
            _c("tractor_id", "STRING", "Tractor"),
            _c("route_id", "STRING", "Route"),
            _c("geofence_id", "STRING", "Geofence entered"),
            _c("entity_type", "STRING", "CUSTOMER or DC"),
            _c("entity_id", "STRING", "customer_id or dc_id"),
            _c("arrive_min", "INT", "Geofence entry, minutes after midnight"),
            _c("depart_min", "INT", "Geofence exit (NULL while the truck is still inside)"),
            _c("dwell_min", "INT", "Minutes inside the geofence so far"),
            _c("planned_service_min", "INT", "Unload time the plan allowed"),
            _c("created_at", "TIMESTAMP", "Detected"),
        ),
        ("geofence_event_id",),
    ),
    Table(
        "master_data_updates",
        "Customer master-data corrections proposed by the agent (dwell standard, geocode) and sent to TMW.",
        (
            _c("update_id", "STRING", "Update id", True),
            _c("dc_id", "STRING", "Distribution center id"),
            _c("customer_id", "STRING", "Customer", True),
            _c("field", "STRING", "std_service_min, lat_lon"),
            _c("old_value", "STRING", "Value before"),
            _c("new_value", "STRING", "Value after"),
            _c("reason", "STRING", "Why the change is proposed"),
            _c("evidence", "JSON", "Numbers behind the change"),
            _c("status", "STRING", "APPLIED (used in planning, queued for TMW) or REJECTED"),
            _c("created_at", "TIMESTAMP", "Created"),
        ),
        ("update_id",),
    ),
)

TABLES_BY_NAME = {t.name: t for t in TABLES}


def render_ddl(engine: str, qualifier: str = "") -> str:
  """Returns CREATE TABLE statements for ``engine`` (sqlite|postgres|bigquery)."""
  statements = []
  for table in TABLES:
    name = f"{qualifier}{table.name}"
    if engine == "bigquery":
      name = f"`{name}`"
    cols = []
    for col in table.columns:
      line = f"  {col.name} {_TYPES[col.type][engine]}"
      if col.required:
        line += " NOT NULL"
      if engine == "bigquery":
        desc = col.description.replace('"', "'")
        line += f' OPTIONS(description="{desc}")'
      cols.append(line)
    if table.primary_key:
      pk = ", ".join(table.primary_key)
      if engine == "bigquery":
        cols.append(f"  PRIMARY KEY ({pk}) NOT ENFORCED")
      else:
        cols.append(f"  PRIMARY KEY ({pk})")
    body = ",\n".join(cols)
    stmt = f"CREATE TABLE IF NOT EXISTS {name} (\n{body}\n)"
    if engine == "bigquery":
      desc = table.description.replace('"', "'")
      stmt += f'\nOPTIONS(description="{desc}")'
    statements.append(stmt + ";")
  if engine == "postgres":
    statements.extend(_POSTGRES_INDEXES)
  return "\n\n".join(statements) + "\n"


_POSTGRES_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_orders_dc_date ON orders (dc_id, delivery_date);",
    "CREATE INDEX IF NOT EXISTS idx_routes_dc_date ON routes (dc_id, route_date, source);",
    "CREATE INDEX IF NOT EXISTS idx_hist_customer ON delivery_history (customer_id);",
    "CREATE INDEX IF NOT EXISTS idx_traffic_date ON traffic_events (event_date);",
    "CREATE INDEX IF NOT EXISTS idx_pings_dc_date ON gps_pings (dc_id, ping_date, tractor_id, ping_min);",
    "CREATE INDEX IF NOT EXISTS idx_hist_dc_date ON delivery_history (dc_id, delivery_date);",
)


def bigquery_schema_json(table: Table) -> list[dict]:
  """Schema in the JSON form ``bq load --schema`` accepts."""
  return [
      {
          "name": c.name,
          "type": _TYPES[c.type]["bigquery"].replace("INT64", "INTEGER").replace("FLOAT64", "FLOAT").replace("BOOL", "BOOLEAN"),
          "mode": "REQUIRED" if c.required else "NULLABLE",
          "description": c.description,
      }
      for c in table.columns
  ]
