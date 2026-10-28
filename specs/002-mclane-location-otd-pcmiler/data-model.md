# Data model additions

| Table | Key | Purpose |
|---|---|---|
| `geofences` | `geofence_id` | Circle per customer (`GF-<customer_id>`) and DC (`GF-<dc_id>`); `source` MASTER_DATA or GPS_LEARNED |
| `gps_pings` | `ping_id` | Telematics breadcrumbs: tractor, route, minute, lat/lon, speed (5-minute cadence) |
| `geofence_events` | `geofence_event_id` | Completed visits found by the engine: arrive, depart, dwell, planned service |
| `otd_policies` | `segment_group` | RETAIL and RESTAURANT definitions, tolerances, targets |
| `master_data_updates` | `update_id` | Applied dwell-standard and geocode fixes with evidence (insert-only overlay) |

| Table | New columns |
|---|---|
| `customers` | `geocode_source`, `geocode_confidence` |
| `delivery_history` | `tractor_id`, `actual_departure_min`, `arrival_source`, `gps_stop_lat`, `gps_stop_lon`; `on_time` now follows the OTD policy |
| `routes` | `pcmiler_miles`, `mileage_source` |
| `route_stops` | `pcmiler_leg_miles` |
| `optimization_runs` | `pcmiler_miles`, `baseline_pcmiler_miles` |
| `route_events` | event type `DWELL_OVERRUN`, source `GEOFENCE`; payload carries `route_id` |
| `tmw_dispatch_queue` | message type `COMPANY_UPDATE` |

Ground truth for tests: `data/synthetic/_planted_patterns.json` (bad geocodes, dwell changes). It is not loaded into
any database.
