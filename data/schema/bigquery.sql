-- Replace YOUR_PROJECT with your project id, or run data/load_bigquery.py which does it for you.
CREATE SCHEMA IF NOT EXISTS `YOUR_PROJECT.mclane_routing` OPTIONS(location='US');

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.mclane_routing.distribution_centers` (
  dc_id STRING NOT NULL OPTIONS(description="DC identifier, e.g. DC-TEMPLE-TX"),
  name STRING OPTIONS(description="Display name"),
  business_unit STRING OPTIONS(description="GROCERY (convenience/retail) or FOODSERVICE (restaurants)"),
  city STRING OPTIONS(description="City"),
  state STRING OPTIONS(description="State code"),
  lat FLOAT64 OPTIONS(description="Latitude"),
  lon FLOAT64 OPTIONS(description="Longitude"),
  dock_doors INT64 OPTIONS(description="Outbound dock doors"),
  dispatch_start_min INT64 OPTIONS(description="Earliest truck departure, minutes after midnight"),
  dispatch_end_min INT64 OPTIONS(description="Latest truck departure, minutes after midnight"),
  timezone STRING OPTIONS(description="IANA timezone"),
  PRIMARY KEY (dc_id) NOT ENFORCED
)
OPTIONS(description="McLane distribution centers (DCs) that originate delivery routes.");

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.mclane_routing.customers` (
  customer_id STRING NOT NULL OPTIONS(description="Customer / ship-to id"),
  tmw_cmp_id STRING OPTIONS(description="Trimble TMW company id (cmp_id)"),
  dc_id STRING NOT NULL OPTIONS(description="Servicing DC"),
  name STRING OPTIONS(description="Store or restaurant name"),
  banner STRING OPTIONS(description="Chain banner"),
  segment STRING OPTIONS(description="CONVENIENCE, GROCERY, MASS_MERCHANT, QSR, CASUAL_DINING"),
  address STRING OPTIONS(description="Street address (synthetic)"),
  city STRING OPTIONS(description="City"),
  state STRING OPTIONS(description="State"),
  lat FLOAT64 OPTIONS(description="Latitude"),
  lon FLOAT64 OPTIONS(description="Longitude"),
  window_start_min INT64 OPTIONS(description="Receiving window open, minutes after midnight"),
  window_end_min INT64 OPTIONS(description="Receiving window close, minutes after midnight"),
  std_service_min INT64 OPTIONS(description="Standard unload time in minutes (TMS master data)"),
  hard_window BOOL OPTIONS(description="Dock appointment: window close is a hard constraint"),
  key_drop BOOL OPTIONS(description="Unattended key-drop delivery allowed"),
  requires_liftgate BOOL OPTIONS(description="Site needs a liftgate / straight truck"),
  max_vehicle_length_ft INT64 OPTIONS(description="Longest vehicle the site can take"),
  priority_tier INT64 OPTIONS(description="1 = strategic account, 3 = standard"),
  delivery_days STRING OPTIONS(description="Scheduled delivery days, e.g. MON,WED,FRI"),
  PRIMARY KEY (customer_id) NOT ENFORCED
)
OPTIONS(description="Retail stores and restaurants served by a DC (TMW company profile).");

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.mclane_routing.tractors` (
  tractor_id STRING NOT NULL OPTIONS(description="Tractor id"),
  dc_id STRING NOT NULL OPTIONS(description="Home DC"),
  unit_type STRING OPTIONS(description="TRACTOR or STRAIGHT_TRUCK"),
  mpg FLOAT64 OPTIONS(description="Average fuel economy"),
  status STRING OPTIONS(description="AVAILABLE, MAINTENANCE"),
  PRIMARY KEY (tractor_id) NOT ENFORCED
)
OPTIONS(description="Power units (TMW tractor profile).");

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.mclane_routing.trailers` (
  trailer_id STRING NOT NULL OPTIONS(description="Trailer id"),
  dc_id STRING NOT NULL OPTIONS(description="Home DC"),
  trailer_type STRING OPTIONS(description="MULTI_TEMP (3-compartment reefer), DRY, STRAIGHT_REEFER"),
  length_ft INT64 OPTIONS(description="Length in feet"),
  capacity_cases INT64 OPTIONS(description="Total case capacity"),
  capacity_cold_cases INT64 OPTIONS(description="Chilled + frozen case capacity (0 for dry vans)"),
  capacity_lbs INT64 OPTIONS(description="Payload weight limit"),
  capacity_cube INT64 OPTIONS(description="Cubic feet"),
  has_liftgate BOOL OPTIONS(description="Liftgate fitted"),
  status STRING OPTIONS(description="AVAILABLE, MAINTENANCE"),
  PRIMARY KEY (trailer_id) NOT ENFORCED
)
OPTIONS(description="Trailers / bodies with capacity by temperature class.");

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.mclane_routing.drivers` (
  driver_id STRING NOT NULL OPTIONS(description="Driver id (TMW mpp_id)"),
  dc_id STRING NOT NULL OPTIONS(description="Home DC"),
  name STRING OPTIONS(description="Synthetic name"),
  hos_drive_remaining_min INT64 OPTIONS(description="Remaining driving minutes today (11h rule)"),
  hos_duty_remaining_min INT64 OPTIONS(description="Remaining on-duty minutes today (14h rule)"),
  shift_start_min INT64 OPTIONS(description="Earliest start, minutes after midnight"),
  cdl_class STRING OPTIONS(description="A or B"),
  status STRING OPTIONS(description="AVAILABLE, PTO"),
  PRIMARY KEY (driver_id) NOT ENFORCED
)
OPTIONS(description="Drivers with hours-of-service (HOS) availability.");

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.mclane_routing.orders` (
  order_id STRING NOT NULL OPTIONS(description="Order id"),
  tmw_ord_hdrnumber INT64 OPTIONS(description="TMW ord_hdrnumber"),
  dc_id STRING NOT NULL OPTIONS(description="Originating DC"),
  customer_id STRING NOT NULL OPTIONS(description="Ship-to customer"),
  delivery_date DATE NOT NULL OPTIONS(description="Requested delivery date"),
  dry_cases INT64 OPTIONS(description="Ambient cases"),
  chill_cases INT64 OPTIONS(description="Refrigerated cases"),
  frozen_cases INT64 OPTIONS(description="Frozen cases"),
  weight_lbs INT64 OPTIONS(description="Gross weight"),
  cube_ft3 FLOAT64 OPTIONS(description="Cubic feet"),
  priority STRING OPTIONS(description="STANDARD, HOT (must deliver), FLEX (can move a day)"),
  status STRING OPTIONS(description="OPEN, PLANNED, DISPATCHED, DELIVERED"),
  PRIMARY KEY (order_id) NOT ENFORCED
)
OPTIONS(description="Delivery orders for upcoming days (TMW order header).");

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.mclane_routing.routes` (
  route_id STRING NOT NULL OPTIONS(description="Route id"),
  plan_id STRING OPTIONS(description="Optimization plan id (NULL for static routes)"),
  source STRING OPTIONS(description="TMW_STATIC or AI_OPTIMIZED"),
  dc_id STRING NOT NULL OPTIONS(description="Distribution center id"),
  route_date DATE NOT NULL OPTIONS(description="Delivery date"),
  tractor_id STRING OPTIONS(description="Assigned tractor"),
  trailer_id STRING OPTIONS(description="Assigned trailer"),
  driver_id STRING OPTIONS(description="Assigned driver"),
  depart_min INT64 OPTIONS(description="Planned DC departure"),
  return_min INT64 OPTIONS(description="Planned DC return"),
  stop_count INT64 OPTIONS(description="Number of stops"),
  total_miles FLOAT64 OPTIONS(description="Planned road miles"),
  total_duration_min INT64 OPTIONS(description="Planned duration"),
  total_cases INT64 OPTIONS(description="Cases on board"),
  est_cost_usd FLOAT64 OPTIONS(description="Estimated cost"),
  late_stops INT64 OPTIONS(description="Stops arriving after window close"),
  status STRING OPTIONS(description="PLANNED, DISPATCHED, IN_PROGRESS, COMPLETE"),
  PRIMARY KEY (route_id) NOT ENFORCED
)
OPTIONS(description="Route headers. TMW_STATIC = today's fixed routes in TMW; AI_OPTIMIZED = agent output.");

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.mclane_routing.route_stops` (
  route_id STRING NOT NULL OPTIONS(description="Route id"),
  stop_seq INT64 NOT NULL OPTIONS(description="1-based sequence"),
  order_id STRING OPTIONS(description="Order delivered"),
  customer_id STRING OPTIONS(description="Customer"),
  eta_min INT64 OPTIONS(description="Planned arrival, minutes after midnight"),
  etd_min INT64 OPTIONS(description="Planned departure"),
  miles_from_prev FLOAT64 OPTIONS(description="Leg miles"),
  window_ok BOOL OPTIONS(description="Arrival inside the receiving window"),
  PRIMARY KEY (route_id, stop_seq) NOT ENFORCED
)
OPTIONS(description="Stop sequence for each route (TMW stops).");

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.mclane_routing.delivery_history` (
  delivery_id STRING NOT NULL OPTIONS(description="Delivery id"),
  customer_id STRING NOT NULL OPTIONS(description="Customer"),
  dc_id STRING OPTIONS(description="Distribution center id"),
  delivery_date DATE OPTIONS(description="Date"),
  planned_arrival_min INT64 OPTIONS(description="Planned arrival"),
  actual_arrival_min INT64 OPTIONS(description="Actual arrival"),
  dwell_min INT64 OPTIONS(description="Actual time on site"),
  cases INT64 OPTIONS(description="Cases delivered"),
  on_time BOOL OPTIONS(description="Arrived inside window"),
  exception_code STRING OPTIONS(description="NONE, TRAFFIC, WEATHER, DOCK_BUSY, LATE_DISPATCH, REFUSED"),
  PRIMARY KEY (delivery_id) NOT ENFORCED
)
OPTIONS(description="Last 60 days of completed deliveries, used to learn dwell time and lateness.");

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.mclane_routing.traffic_events` (
  event_id STRING NOT NULL OPTIONS(description="Event id"),
  event_date DATE NOT NULL OPTIONS(description="Date"),
  event_type STRING OPTIONS(description="CLOSURE, ACCIDENT, CONSTRUCTION, CONGESTION"),
  corridor STRING OPTIONS(description="Road, e.g. I-35 N"),
  description STRING OPTIONS(description="Human readable description"),
  lat FLOAT64 OPTIONS(description="Centre latitude"),
  lon FLOAT64 OPTIONS(description="Centre longitude"),
  radius_miles FLOAT64 OPTIONS(description="Affected radius"),
  start_min INT64 OPTIONS(description="Start, minutes after midnight"),
  end_min INT64 OPTIONS(description="End, minutes after midnight"),
  delay_factor FLOAT64 OPTIONS(description="Travel-time multiplier inside the radius"),
  PRIMARY KEY (event_id) NOT ENFORCED
)
OPTIONS(description="Traffic incidents, closures and congestion (simulated feed, e.g. from Maps/511).");

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.mclane_routing.weather_events` (
  event_id STRING NOT NULL OPTIONS(description="Event id"),
  event_date DATE NOT NULL OPTIONS(description="Date"),
  alert_type STRING OPTIONS(description="THUNDERSTORM, ICE, HEAT, FLOOD, WIND"),
  severity STRING OPTIONS(description="ADVISORY, WATCH, WARNING"),
  description STRING OPTIONS(description="Description"),
  lat FLOAT64 OPTIONS(description="Centre latitude"),
  lon FLOAT64 OPTIONS(description="Centre longitude"),
  radius_miles FLOAT64 OPTIONS(description="Affected radius"),
  start_min INT64 OPTIONS(description="Start"),
  end_min INT64 OPTIONS(description="End"),
  speed_factor FLOAT64 OPTIONS(description="Travel-time multiplier"),
  PRIMARY KEY (event_id) NOT ENFORCED
)
OPTIONS(description="Weather alerts affecting delivery regions.");

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.mclane_routing.route_events` (
  event_id STRING NOT NULL OPTIONS(description="Event id"),
  dc_id STRING NOT NULL OPTIONS(description="Distribution center id"),
  event_date DATE NOT NULL OPTIONS(description="Operating date"),
  event_min INT64 OPTIONS(description="Time the event happened, minutes after midnight"),
  event_type STRING OPTIONS(description="DELAY, BREAKDOWN, ORDER_ADDED, ORDER_CANCELLED, ROAD_CLOSURE, NO_SHOW, REEFER_TEMP_ALERT"),
  source STRING OPTIONS(description="TELEMATICS, DRIVER_APP, TMS, TRAFFIC_FEED, CUSTOMER"),
  tractor_id STRING OPTIONS(description="Truck involved (resolves to its route in any plan)"),
  customer_id STRING OPTIONS(description="Customer involved"),
  order_id STRING OPTIONS(description="Order involved"),
  delay_min INT64 OPTIONS(description="Reported delay in minutes"),
  lat FLOAT64 OPTIONS(description="Event latitude"),
  lon FLOAT64 OPTIONS(description="Event longitude"),
  radius_miles FLOAT64 OPTIONS(description="Affected radius (closures)"),
  delay_factor FLOAT64 OPTIONS(description="Travel-time multiplier (closures)"),
  payload JSON OPTIONS(description="Extra fields, e.g. cases for an added order or reefer temperature"),
  description STRING OPTIONS(description="What happened"),
  PRIMARY KEY (event_id) NOT ENFORCED
)
OPTIONS(description="Real-time operational events (telematics, driver app, TMS, traffic feed), as published to Pub/Sub.");

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.mclane_routing.event_actions` (
  action_id STRING NOT NULL OPTIONS(description="Action id"),
  event_id STRING OPTIONS(description="Triggering event"),
  source_plan_id STRING OPTIONS(description="Plan that was disrupted"),
  new_plan_id STRING OPTIONS(description="Plan holding the re-planned routes"),
  affected_routes JSON OPTIONS(description="Routes re-planned"),
  untouched_routes INT64 OPTIONS(description="Routes left exactly as they were"),
  cost_impact_usd FLOAT64 OPTIONS(description="Cost of the new plan minus the original plan for the affected work"),
  late_stops_before INT64 OPTIONS(description="Late or failed stops if nothing is changed"),
  late_stops_after INT64 OPTIONS(description="Late stops after re-plan"),
  requires_approval BOOL OPTIONS(description="Escalated to a human dispatcher"),
  escalation_reasons JSON OPTIONS(description="Why it was escalated"),
  status STRING OPTIONS(description="AUTO_APPLIED, PENDING_APPROVAL, NO_ACTION"),
  explanation STRING OPTIONS(description="Plain-language summary for dispatchers"),
  latency_s FLOAT64 OPTIONS(description="Seconds from event intake to re-plan"),
  created_at TIMESTAMP OPTIONS(description="Created"),
  PRIMARY KEY (action_id) NOT ENFORCED
)
OPTIONS(description="Every re-plan the agent proposed or applied in response to an event (audit log).");

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.mclane_routing.replan_approvals` (
  approval_id STRING NOT NULL OPTIONS(description="Approval id"),
  action_id STRING OPTIONS(description="Action decided"),
  decision STRING OPTIONS(description="APPROVED or REJECTED"),
  decided_by STRING OPTIONS(description="User"),
  notes STRING OPTIONS(description="Notes"),
  created_at TIMESTAMP OPTIONS(description="Created"),
  PRIMARY KEY (approval_id) NOT ENFORCED
)
OPTIONS(description="Dispatcher decisions on escalated re-plans.");

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.mclane_routing.cost_parameters` (
  dc_id STRING NOT NULL OPTIONS(description="Distribution center id"),
  cost_per_mile_usd FLOAT64 OPTIONS(description="Variable cost per mile (fuel excluded)"),
  fuel_price_usd_gal FLOAT64 OPTIONS(description="Diesel price"),
  driver_cost_per_hour_usd FLOAT64 OPTIONS(description="Loaded driver wage"),
  overtime_multiplier FLOAT64 OPTIONS(description="Multiplier after 10 hours"),
  fixed_cost_per_route_usd FLOAT64 OPTIONS(description="Fixed cost of dispatching a truck"),
  late_penalty_usd FLOAT64 OPTIONS(description="Service penalty per late stop"),
  co2_kg_per_gal FLOAT64 OPTIONS(description="CO2 per gallon of diesel"),
  PRIMARY KEY (dc_id) NOT ENFORCED
)
OPTIONS(description="Per-DC cost model used to price routes.");

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.mclane_routing.optimization_runs` (
  plan_id STRING NOT NULL OPTIONS(description="Plan id"),
  dc_id STRING OPTIONS(description="Distribution center id"),
  route_date DATE OPTIONS(description="Delivery date"),
  scenario STRING OPTIONS(description="BASE, WHAT_IF, REOPTIMIZE"),
  parameters JSON OPTIONS(description="Solver parameters"),
  orders_planned INT64 OPTIONS(description="Orders routed"),
  orders_dropped INT64 OPTIONS(description="Orders the solver could not fit"),
  routes_used INT64 OPTIONS(description="Trucks used"),
  total_miles FLOAT64 OPTIONS(description="Miles"),
  total_cost_usd FLOAT64 OPTIONS(description="Cost"),
  baseline_miles FLOAT64 OPTIONS(description="TMW static plan miles"),
  baseline_cost_usd FLOAT64 OPTIONS(description="TMW static plan cost"),
  late_stops INT64 OPTIONS(description="Late stops"),
  co2_kg FLOAT64 OPTIONS(description="Estimated CO2"),
  created_at TIMESTAMP OPTIONS(description="Created"),
  PRIMARY KEY (plan_id) NOT ENFORCED
)
OPTIONS(description="Audit log of every optimization run made by the agent.");

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.mclane_routing.tmw_dispatch_queue` (
  message_id STRING NOT NULL OPTIONS(description="Message id"),
  plan_id STRING OPTIONS(description="Plan id"),
  route_id STRING OPTIONS(description="Route id"),
  message_type STRING OPTIONS(description="CREATE_MOVEMENT, UPDATE_STOPS, CANCEL"),
  payload JSON OPTIONS(description="TMW-shaped payload"),
  status STRING OPTIONS(description="QUEUED, SENT, ACKED, FAILED"),
  created_at TIMESTAMP OPTIONS(description="Created"),
  PRIMARY KEY (message_id) NOT ENFORCED
)
OPTIONS(description="Outbound messages to Trimble TMW (simulated integration queue).");

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT.mclane_routing.customer_notifications` (
  notification_id STRING NOT NULL OPTIONS(description="Notification id"),
  plan_id STRING OPTIONS(description="Plan id"),
  customer_id STRING OPTIONS(description="Customer"),
  channel STRING OPTIONS(description="SMS, EMAIL, EDI_214"),
  message STRING OPTIONS(description="Message body"),
  status STRING OPTIONS(description="DRAFT, SENT"),
  created_at TIMESTAMP OPTIONS(description="Created"),
  PRIMARY KEY (notification_id) NOT ENFORCED
)
OPTIONS(description="ETA notifications sent to stores and restaurants.");
