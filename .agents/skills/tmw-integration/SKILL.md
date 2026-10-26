---
name: tmw-integration
description: Use when mapping plans to or from Trimble TMW (TMW.Suite) objects: orders, movements, leg headers, stops, company ids, or when wiring the real TMW endpoint in tools/tms_tools.py.
---

# Trimble TMW integration

## Goal
Plans leave this system as TMW-shaped messages that a dispatcher, or an integration service, can
apply in TMW without manual re-keying.

## Instructions
1. Read `references/tmw_object_model.md` for the object mapping used here.
2. Message builders live in `route_optimizer/tools/tms_tools.py` (`_payloads`). New plans produce
   `CREATE_MOVEMENT`; event re-plans (`EVP-*`, `RPL-*`) produce `UPDATE_STOPS`.
3. The default transport is the `tmw_dispatch_queue` table. To post live, set `TMW_API_BASE_URL`
   (and `TMW_API_TOKEN`) and adapt `_post()` to McLane's integration contract (TMW.Suite REST API,
   Trimble integration services, or internal middleware). Keep the queue write: it is the audit trail.
4. Inbound (TMW to this system): load orders, stops and company master data into the `orders`,
   `customers`, `routes` and `route_stops` tables (BigQuery replica or AlloyDB), keeping
   `tmw_ord_hdrnumber` and `tmw_cmp_id`.
5. Submitting is always behind `require_confirmation=True`.

## Constraints
- Never send to TMW without explicit dispatcher approval.
- Do not invent TMW field names beyond the mapping file without confirming them with McLane's TMW admin.
