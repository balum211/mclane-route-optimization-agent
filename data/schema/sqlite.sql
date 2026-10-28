CREATE TABLE IF NOT EXISTS distribution_centers (
  dc_id TEXT NOT NULL,
  name TEXT,
  business_unit TEXT,
  city TEXT,
  state TEXT,
  lat REAL,
  lon REAL,
  dock_doors INTEGER,
  dispatch_start_min INTEGER,
  dispatch_end_min INTEGER,
  timezone TEXT,
  PRIMARY KEY (dc_id)
);

CREATE TABLE IF NOT EXISTS customers (
  customer_id TEXT NOT NULL,
  tmw_cmp_id TEXT,
  dc_id TEXT NOT NULL,
  name TEXT,
  banner TEXT,
  segment TEXT,
  address TEXT,
  city TEXT,
  state TEXT,
  lat REAL,
  lon REAL,
  geocode_source TEXT,
  geocode_confidence TEXT,
  window_start_min INTEGER,
  window_end_min INTEGER,
  std_service_min INTEGER,
  hard_window INTEGER,
  key_drop INTEGER,
  requires_liftgate INTEGER,
  max_vehicle_length_ft INTEGER,
  priority_tier INTEGER,
  delivery_days TEXT,
  PRIMARY KEY (customer_id)
);

CREATE TABLE IF NOT EXISTS geofences (
  geofence_id TEXT NOT NULL,
  entity_type TEXT,
  entity_id TEXT NOT NULL,
  dc_id TEXT,
  center_lat REAL,
  center_lon REAL,
  radius_m INTEGER,
  source TEXT,
  active INTEGER,
  PRIMARY KEY (geofence_id)
);

CREATE TABLE IF NOT EXISTS otd_policies (
  segment_group TEXT NOT NULL,
  segments TEXT,
  measure_against TEXT,
  early_tolerance_min INTEGER,
  late_tolerance_min INTEGER,
  target_pct REAL,
  arrival_event TEXT,
  description TEXT,
  PRIMARY KEY (segment_group)
);

CREATE TABLE IF NOT EXISTS tractors (
  tractor_id TEXT NOT NULL,
  dc_id TEXT NOT NULL,
  unit_type TEXT,
  mpg REAL,
  status TEXT,
  PRIMARY KEY (tractor_id)
);

CREATE TABLE IF NOT EXISTS trailers (
  trailer_id TEXT NOT NULL,
  dc_id TEXT NOT NULL,
  trailer_type TEXT,
  length_ft INTEGER,
  capacity_cases INTEGER,
  capacity_cold_cases INTEGER,
  capacity_lbs INTEGER,
  capacity_cube INTEGER,
  has_liftgate INTEGER,
  status TEXT,
  PRIMARY KEY (trailer_id)
);

CREATE TABLE IF NOT EXISTS drivers (
  driver_id TEXT NOT NULL,
  dc_id TEXT NOT NULL,
  name TEXT,
  hos_drive_remaining_min INTEGER,
  hos_duty_remaining_min INTEGER,
  shift_start_min INTEGER,
  cdl_class TEXT,
  status TEXT,
  PRIMARY KEY (driver_id)
);

CREATE TABLE IF NOT EXISTS orders (
  order_id TEXT NOT NULL,
  tmw_ord_hdrnumber INTEGER,
  dc_id TEXT NOT NULL,
  customer_id TEXT NOT NULL,
  delivery_date TEXT NOT NULL,
  dry_cases INTEGER,
  chill_cases INTEGER,
  frozen_cases INTEGER,
  weight_lbs INTEGER,
  cube_ft3 REAL,
  priority TEXT,
  status TEXT,
  PRIMARY KEY (order_id)
);

CREATE TABLE IF NOT EXISTS routes (
  route_id TEXT NOT NULL,
  plan_id TEXT,
  source TEXT,
  dc_id TEXT NOT NULL,
  route_date TEXT NOT NULL,
  tractor_id TEXT,
  trailer_id TEXT,
  driver_id TEXT,
  depart_min INTEGER,
  return_min INTEGER,
  stop_count INTEGER,
  total_miles REAL,
  pcmiler_miles REAL,
  mileage_source TEXT,
  total_duration_min INTEGER,
  total_cases INTEGER,
  est_cost_usd REAL,
  late_stops INTEGER,
  status TEXT,
  PRIMARY KEY (route_id)
);

CREATE TABLE IF NOT EXISTS route_stops (
  route_id TEXT NOT NULL,
  stop_seq INTEGER NOT NULL,
  order_id TEXT,
  customer_id TEXT,
  eta_min INTEGER,
  etd_min INTEGER,
  miles_from_prev REAL,
  pcmiler_leg_miles REAL,
  window_ok INTEGER,
  PRIMARY KEY (route_id, stop_seq)
);

CREATE TABLE IF NOT EXISTS delivery_history (
  delivery_id TEXT NOT NULL,
  customer_id TEXT NOT NULL,
  dc_id TEXT,
  delivery_date TEXT,
  tractor_id TEXT,
  planned_arrival_min INTEGER,
  actual_arrival_min INTEGER,
  actual_departure_min INTEGER,
  arrival_source TEXT,
  dwell_min INTEGER,
  gps_stop_lat REAL,
  gps_stop_lon REAL,
  cases INTEGER,
  on_time INTEGER,
  exception_code TEXT,
  PRIMARY KEY (delivery_id)
);

CREATE TABLE IF NOT EXISTS traffic_events (
  event_id TEXT NOT NULL,
  event_date TEXT NOT NULL,
  event_type TEXT,
  corridor TEXT,
  description TEXT,
  lat REAL,
  lon REAL,
  radius_miles REAL,
  start_min INTEGER,
  end_min INTEGER,
  delay_factor REAL,
  PRIMARY KEY (event_id)
);

CREATE TABLE IF NOT EXISTS weather_events (
  event_id TEXT NOT NULL,
  event_date TEXT NOT NULL,
  alert_type TEXT,
  severity TEXT,
  description TEXT,
  lat REAL,
  lon REAL,
  radius_miles REAL,
  start_min INTEGER,
  end_min INTEGER,
  speed_factor REAL,
  PRIMARY KEY (event_id)
);

CREATE TABLE IF NOT EXISTS route_events (
  event_id TEXT NOT NULL,
  dc_id TEXT NOT NULL,
  event_date TEXT NOT NULL,
  event_min INTEGER,
  event_type TEXT,
  source TEXT,
  tractor_id TEXT,
  customer_id TEXT,
  order_id TEXT,
  delay_min INTEGER,
  lat REAL,
  lon REAL,
  radius_miles REAL,
  delay_factor REAL,
  payload TEXT,
  description TEXT,
  PRIMARY KEY (event_id)
);

CREATE TABLE IF NOT EXISTS event_actions (
  action_id TEXT NOT NULL,
  event_id TEXT,
  source_plan_id TEXT,
  new_plan_id TEXT,
  affected_routes TEXT,
  untouched_routes INTEGER,
  cost_impact_usd REAL,
  late_stops_before INTEGER,
  late_stops_after INTEGER,
  requires_approval INTEGER,
  escalation_reasons TEXT,
  status TEXT,
  explanation TEXT,
  latency_s REAL,
  created_at TEXT,
  PRIMARY KEY (action_id)
);

CREATE TABLE IF NOT EXISTS replan_approvals (
  approval_id TEXT NOT NULL,
  action_id TEXT,
  decision TEXT,
  decided_by TEXT,
  notes TEXT,
  created_at TEXT,
  PRIMARY KEY (approval_id)
);

CREATE TABLE IF NOT EXISTS cost_parameters (
  dc_id TEXT NOT NULL,
  cost_per_mile_usd REAL,
  fuel_price_usd_gal REAL,
  driver_cost_per_hour_usd REAL,
  overtime_multiplier REAL,
  fixed_cost_per_route_usd REAL,
  late_penalty_usd REAL,
  co2_kg_per_gal REAL,
  PRIMARY KEY (dc_id)
);

CREATE TABLE IF NOT EXISTS optimization_runs (
  plan_id TEXT NOT NULL,
  dc_id TEXT,
  route_date TEXT,
  scenario TEXT,
  parameters TEXT,
  orders_planned INTEGER,
  orders_dropped INTEGER,
  routes_used INTEGER,
  total_miles REAL,
  pcmiler_miles REAL,
  total_cost_usd REAL,
  baseline_miles REAL,
  baseline_pcmiler_miles REAL,
  baseline_cost_usd REAL,
  late_stops INTEGER,
  co2_kg REAL,
  created_at TEXT,
  PRIMARY KEY (plan_id)
);

CREATE TABLE IF NOT EXISTS tmw_dispatch_queue (
  message_id TEXT NOT NULL,
  plan_id TEXT,
  route_id TEXT,
  message_type TEXT,
  payload TEXT,
  status TEXT,
  created_at TEXT,
  PRIMARY KEY (message_id)
);

CREATE TABLE IF NOT EXISTS customer_notifications (
  notification_id TEXT NOT NULL,
  plan_id TEXT,
  customer_id TEXT,
  channel TEXT,
  message TEXT,
  status TEXT,
  created_at TEXT,
  PRIMARY KEY (notification_id)
);

CREATE TABLE IF NOT EXISTS gps_pings (
  ping_id TEXT NOT NULL,
  dc_id TEXT NOT NULL,
  ping_date TEXT NOT NULL,
  ping_min INTEGER,
  tractor_id TEXT NOT NULL,
  route_id TEXT,
  lat REAL,
  lon REAL,
  speed_mph REAL,
  PRIMARY KEY (ping_id)
);

CREATE TABLE IF NOT EXISTS geofence_events (
  geofence_event_id TEXT NOT NULL,
  dc_id TEXT,
  event_date TEXT,
  tractor_id TEXT,
  route_id TEXT,
  geofence_id TEXT,
  entity_type TEXT,
  entity_id TEXT,
  arrive_min INTEGER,
  depart_min INTEGER,
  dwell_min INTEGER,
  planned_service_min INTEGER,
  created_at TEXT,
  PRIMARY KEY (geofence_event_id)
);

CREATE TABLE IF NOT EXISTS master_data_updates (
  update_id TEXT NOT NULL,
  dc_id TEXT,
  customer_id TEXT NOT NULL,
  field TEXT,
  old_value TEXT,
  new_value TEXT,
  reason TEXT,
  evidence TEXT,
  status TEXT,
  created_at TEXT,
  PRIMARY KEY (update_id)
);
