# PC*MILER Web Services: what this repo calls

Confirm every field against the PC*MILER Web Services developer guide for McLane's account
(https://developer.trimblemaps.com/restful-apis/) before going live.

## Route report (mileage of record)

`GET {PCMILER_BASE_URL}/route/routeReports`, default base `https://pcmiler.alk.com/apis/rest/v1.0/Service.svc`

Header: `Authorization: {PCMILER_API_KEY}`

| Query parameter | Value used |
|---|---|
| `stops` | `lon,lat;lon,lat;...` (DC, stops in sequence, DC) |
| `reports` | `Mileage` |
| `routeType` | `Practical` (or `Shortest`, `Fastest`; from `PCMILER_ROUTING_TYPE`) |
| `vehType` | `Truck` |
| `region` | `NA` (`PCMILER_REGION`) |
| `dataVer` | `Current` (`PCMILER_DATA_VERSION`) |

Parsed response: a list of reports; the Mileage report's `ReportLines`, one per stop, with leg miles
`LMiles` (first line is the origin, 0) and cumulative hours `THours` as `h:mm`. Some report types return
`TDistance` / `TMinutes` instead; `_parse_report` accepts both.

## Settings

| Env var | Default | Meaning |
|---|---|---|
| `PCMILER_API_KEY` | empty | Empty = offline emulation (`PCMILER_EMULATED`) |
| `PCMILER_ROUTING_TYPE` | `PRACTICAL` | `PRACTICAL`, `SHORTEST`, `FASTEST` |
| `PCMILER_BASE_URL` | see above | Override for a regional or proxy endpoint |
| `PCMILER_MATRIX_MAX_POINTS` | 60 | Largest live pairwise matrix for `TRAVEL_PROVIDER=pcmiler` |
