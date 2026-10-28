# PRD: McLane specifics for route optimization (PC*MILER, geofence, geolocations, dwell, OTD)

**Date**: 2026-10-28 · **Owner**: Bala Mallampati · **Spec**: `specs/002-mclane-location-otd-pcmiler/`

## Problem
The route optimization agent reported its own matrix miles, measured on-time one way for everyone and
trusted TMW master data for unload times and coordinates. McLane runs on PC*MILER miles, measures Retail
and Restaurant OTD differently, and has geofence and GPS data that show where master data is wrong.

## Users and jobs
| User | Job |
|---|---|
| Night dispatcher | Plan and compare in PC*MILER miles; see Retail and Restaurant OTD of the plan |
| Day dispatcher | Know where trucks are, who is stuck at a dock, which restaurants need a new ETA |
| Master-data analyst | Fix TMW dwell standards and geocodes with evidence |
| Transportation leadership | Retail versus Restaurant OTD against target, by DC and banner |

## Requirements
1. PC*MILER practical miles on every route, plan and TMW payload; live when a key exists, labelled emulation otherwise.
2. Geofence per customer and DC; arrivals, departures and dwell from GPS; DWELL_OVERRUN events.
3. Dwell time change detection with a recommended TMW standard; planner uses recent dwell immediately.
4. Geocode validation from observed parking spots.
5. Retail (window close, 95%) and Restaurant (scheduled ±30 min, 98%) OTD everywhere OTD appears.
6. Master-data fixes only after confirmation, queued to TMW.

## Out of scope
Live TMW writes, polygon geofences, reefer temperature in GPS pings, PC*MILER toll and fuel reports.

## Success
See the spec's success criteria. Demo: `uv run python scripts/demo_run.py` sections 4 to 7.
