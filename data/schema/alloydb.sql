CREATE SCHEMA IF NOT EXISTS mclane_routing;
SET search_path TO mclane_routing;

CREATE TABLE IF NOT EXISTS distribution_centers (
  dc_id TEXT NOT NULL,
  name TEXT,
  business_unit TEXT,
  city TEXT,
  state TEXT,
  lat DOUBLE PRECISION,
  lon DOUBLE PRECISION,
  dock_doors BIGINT,
  dispatch_start_min BIGINT,
  dispatch_end_min BIGINT,
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
  lat DOUBLE PRECISION,
  lon DOUBLE PRECISION,
  window_start_min BIGINT,
  window_end_min BIGINT,
  std_service_min BIGINT,
  hard_window BOOLEAN,
  key_drop BOOLEAN,
  requires_liftgate BOOLEAN,
  max_vehicle_length_ft BIGINT,
  priority_tier BIGINT,
  delivery_days TEXT,
  PRIMARY KEY (customer_id)
);

CREATE TABLE IF NOT EXISTS tractors (
  tractor_id TEXT NOT NULL,
  dc_id TEXT NOT NULL,
  unit_type TEXT,
  mpg DOUBLE PRECISION,
  status TEXT,
  PRIMARY KEY (tractor_id)
);

CREATE TABLE IF NOT EXISTS trailers (
  trailer_id TEXT NOT NULL,
  dc_id TEXT NOT NULL,
  trailer_type TEXT,
  length_ft BIGINT,
  capacity_cases BIGINT,
  capacity_cold_cases BIGINT,
  capacity_lbs BIGINT,
  capacity_cube BIGINT,
  has_liftgate BOOLEAN,
  status TEXT,
  PRIMARY KEY (trailer_id)
);

CREATE TABLE IF NOT EXISTS drivers (
  driver_id TEXT NOT NULL,
  dc_id TEXT NOT NULL,
  name TEXT,
  hos_drive_remaining_min BIGINT,
  hos_duty_remaining_min BIGINT,
  shift_start_min BIGINT,
  cdl_class TEXT,
  status TEXT,
  PRIMARY KEY (driver_id)
);

CREATE TABLE IF NOT EXISTS orders (
  order_id TEXT NOT NULL,
  tmw_ord_hdrnumber BIGINT,
  dc_id TEXT NOT NULL,
  customer_id TEXT NOT NULL,
  delivery_date DATE NOT NULL,
  dry_cases BIGINT,
  chill_cases BIGINT,
  frozen_cases BIGINT,
  weight_lbs BIGINT,
  cube_ft3 DOUBLE PRECISION,
  priority TEXT,
  status TEXT,
  PRIMARY KEY (order_id)
);

CREATE TABLE IF NOT EXISTS routes (
  route_id TEXT NOT NULL,
  plan_id TEXT,
  source TEXT,
  dc_id TEXT NOT NULL,
  route_date DATE NOT NULL,
  tractor_id TEXT,
  trailer_id TEXT,
  driver_id TEXT,
  depart_min BIGINT,
  return_min BIGINT,
  stop_count BIGINT,
  total_miles DOUBLE PRECISION,
  total_duration_min BIGINT,
  total_cases BIGINT,
  est_cost_usd DOUBLE PRECISION,
  late_stops BIGINT,
  status TEXT,
  PRIMARY KEY (route_id)
);

CREATE TABLE IF NOT EXISTS route_stops (
  route_id TEXT NOT NULL,
  stop_seq BIGINT NOT NULL,
  order_id TEXT,
  customer_id TEXT,
  eta_min BIGINT,
  etd_min BIGINT,
  miles_from_prev DOUBLE PRECISION,
  window_ok BOOLEAN,
  PRIMARY KEY (route_id, stop_seq)
);

CREATE TABLE IF NOT EXISTS delivery_history (
  delivery_id TEXT NOT NULL,
  customer_id TEXT NOT NULL,
  dc_id TEXT,
  delivery_date DATE,
  planned_arrival_min BIGINT,
  actual_arrival_min BIGINT,
  dwell_min BIGINT,
  cases BIGINT,
  on_time BOOLEAN,
  exception_code TEXT,
  PRIMARY KEY (delivery_id)
);

CREATE TABLE IF NOT EXISTS traffic_events (
  event_id TEXT NOT NULL,
  event_date DATE NOT NULL,
  event_type TEXT,
  corridor TEXT,
  description TEXT,
  lat DOUBLE PRECISION,
  lon DOUBLE PRECISION,
  radius_miles DOUBLE PRECISION,
  start_min BIGINT,
  end_min BIGINT,
  delay_factor DOUBLE PRECISION,
  PRIMARY KEY (event_id)
);

CREATE TABLE IF NOT EXISTS weather_events (
  event_id TEXT NOT NULL,
  event_date DATE NOT NULL,
  alert_type TEXT,
  severity TEXT,
  description TEXT,
  lat DOUBLE PRECISION,
  lon DOUBLE PRECISION,
  radius_miles DOUBLE PRECISION,
  start_min BIGINT,
  end_min BIGINT,
  speed_factor DOUBLE PRECISION,
  PRIMARY KEY (event_id)
);

CREATE TABLE IF NOT EXISTS route_events (
  event_id TEXT NOT NULL,
  dc_id TEXT NOT NULL,
  event_date DATE NOT NULL,
  event_min BIGINT,
  event_type TEXT,
  source TEXT,
  tractor_id TEXT,
  customer_id TEXT,
  order_id TEXT,
  delay_min BIGINT,
  lat DOUBLE PRECISION,
  lon DOUBLE PRECISION,
  radius_miles DOUBLE PRECISION,
  delay_factor DOUBLE PRECISION,
  payload JSONB,
  description TEXT,
  PRIMARY KEY (event_id)
);

CREATE TABLE IF NOT EXISTS event_actions (
  action_id TEXT NOT NULL,
  event_id TEXT,
  source_plan_id TEXT,
  new_plan_id TEXT,
  affected_routes JSONB,
  untouched_routes BIGINT,
  cost_impact_usd DOUBLE PRECISION,
  late_stops_before BIGINT,
  late_stops_after BIGINT,
  requires_approval BOOLEAN,
  escalation_reasons JSONB,
  status TEXT,
  explanation TEXT,
  latency_s DOUBLE PRECISION,
  created_at TIMESTAMPTZ,
  PRIMARY KEY (action_id)
);

CREATE TABLE IF NOT EXISTS replan_approvals (
  approval_id TEXT NOT NULL,
  action_id TEXT,
  decision TEXT,
  decided_by TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ,
  PRIMARY KEY (approval_id)
);

CREATE TABLE IF NOT EXISTS cost_parameters (
  dc_id TEXT NOT NULL,
  cost_per_mile_usd DOUBLE PRECISION,
  fuel_price_usd_gal DOUBLE PRECISION,
  driver_cost_per_hour_usd DOUBLE PRECISION,
  overtime_multiplier DOUBLE PRECISION,
  fixed_cost_per_route_usd DOUBLE PRECISION,
  late_penalty_usd DOUBLE PRECISION,
  co2_kg_per_gal DOUBLE PRECISION,
  PRIMARY KEY (dc_id)
);

CREATE TABLE IF NOT EXISTS optimization_runs (
  plan_id TEXT NOT NULL,
  dc_id TEXT,
  route_date DATE,
  scenario TEXT,
  parameters JSONB,
  orders_planned BIGINT,
  orders_dropped BIGINT,
  routes_used BIGINT,
  total_miles DOUBLE PRECISION,
  total_cost_usd DOUBLE PRECISION,
  baseline_miles DOUBLE PRECISION,
  baseline_cost_usd DOUBLE PRECISION,
  late_stops BIGINT,
  co2_kg DOUBLE PRECISION,
  created_at TIMESTAMPTZ,
  PRIMARY KEY (plan_id)
);

CREATE TABLE IF NOT EXISTS tmw_dispatch_queue (
  message_id TEXT NOT NULL,
  plan_id TEXT,
  route_id TEXT,
  message_type TEXT,
  payload JSONB,
  status TEXT,
  created_at TIMESTAMPTZ,
  PRIMARY KEY (message_id)
);

CREATE TABLE IF NOT EXISTS customer_notifications (
  notification_id TEXT NOT NULL,
  plan_id TEXT,
  customer_id TEXT,
  channel TEXT,
  message TEXT,
  status TEXT,
  created_at TIMESTAMPTZ,
  PRIMARY KEY (notification_id)
);

CREATE INDEX IF NOT EXISTS idx_orders_dc_date ON orders (dc_id, delivery_date);

CREATE INDEX IF NOT EXISTS idx_routes_dc_date ON routes (dc_id, route_date, source);

CREATE INDEX IF NOT EXISTS idx_hist_customer ON delivery_history (customer_id);

CREATE INDEX IF NOT EXISTS idx_traffic_date ON traffic_events (event_date);
