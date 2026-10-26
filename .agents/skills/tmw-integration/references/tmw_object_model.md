# TMW object mapping used by this repo

Field names follow common TMW.Suite conventions. Confirm them against McLane's TMW version and
integration layer before going live.

| This repo | TMW concept | Fields used |
|---|---|---|
| `orders.order_id`, `tmw_ord_hdrnumber` | Order header | `ord_hdrnumber` |
| `customers.tmw_cmp_id` | Company profile (ship-to) | `cmp_id`, `cmp_name` |
| one route | Movement | `mov_external_ref` = route_id, `revtype1` = business unit |
| route truck assignment | Leg header | `lgh_tractor`, `lgh_primary_trailer`, `lgh_driver1`, `lgh_startdate`, `lgh_enddate`, `lgh_miles`, `lgh_outstatus` (PLN) |
| DC load | Stop | `stp_type` PUP, `stp_event` HLT (hook loaded trailer) |
| each delivery | Stop | `stp_type` DRP, `stp_event` DRL (drop live), `stp_arrivaldate`, `stp_departuredate`, `stp_count` + `stp_countunit` CAS, `stp_weight` + LBS, `ord_hdrnumber` |
| return to DC | Stop | `stp_event` EMT (empty return) |

Message types: `CREATE_MOVEMENT` (new plan), `UPDATE_STOPS` (event re-plan), `CANCEL`.
