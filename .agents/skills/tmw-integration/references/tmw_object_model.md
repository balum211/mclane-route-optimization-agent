# TMW object mapping used by this repo

Field names follow common TMW.Suite conventions. Confirm them against McLane's TMW version and
integration layer before going live.

| This repo | TMW concept | Fields used |
|---|---|---|
| `orders.order_id`, `tmw_ord_hdrnumber` | Order header | `ord_hdrnumber` |
| `customers.tmw_cmp_id` | Company profile (ship-to) | `cmp_id`, `cmp_name` |
| one route | Movement | `mov_external_ref` = route_id, `revtype1` = business unit |
| route truck assignment | Leg header | `lgh_tractor`, `lgh_primary_trailer`, `lgh_driver1`, `lgh_startdate`, `lgh_enddate`, `lgh_miles` (PC*MILER miles of the route), `lgh_outstatus` (PLN), plus `mileage_type` / `mileage_source` for the integration layer |
| DC load | Stop | `stp_type` PUP, `stp_event` HLT (hook loaded trailer) |
| each delivery | Stop | `stp_type` DRP, `stp_event` DRL (drop live), `stp_arrivaldate`, `stp_departuredate`, `stp_count` + `stp_countunit` CAS, `stp_weight` + LBS, `ord_hdrnumber`, `stp_lgh_mileage` (PC*MILER leg miles) |
| return to DC | Stop | `stp_event` EMT (empty return), `stp_lgh_mileage` = empty miles back |
| customer geocode fix | Company profile | `cmp_id`, `cmp_latseconds`, `cmp_longseconds` (TMW keeps coordinates in seconds; longitude as a positive number for the western hemisphere; confirm sign convention) |
| customer dwell standard | Company profile | `cmp_id`, `standard_stop_minutes` (placeholder name: map to the field McLane uses for default stop time) |

Message types: `CREATE_MOVEMENT` (new plan), `UPDATE_STOPS` (event re-plan), `CANCEL`, `COMPANY_UPDATE`
(master-data fix from `apply_master_data_updates`).

Mileage: TMW rates, pays and bills on PC*MILER. `lgh_miles` and `stp_lgh_mileage` are PC*MILER miles
(`mileage_source` PCMILER) or the offline emulation (`PCMILER_EMULATED`); never routing-matrix miles
unless PC*MILER stamping was skipped (`ROUTING_MATRIX`).
