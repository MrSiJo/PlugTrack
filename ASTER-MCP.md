# Aster charge capture through MCP

Use the existing bearer-authenticated `/mcp/` endpoint. `list_cars` accepts either token scope; `propose_import_charge` and `commit_change` require `readwrite`. Authentication exemptions are unchanged.

1. Call `list_cars` with `{}`. Result: `[{"id":1,"name":"Example car","make":"Example","model":"EV","battery_kwh":58,"active":true}]`. Select an active car explicitly.
2. Call `propose_import_charge` with an explicit `car_id` and 1–10 `extractions` for exactly one charge:

```json
{"car_id":1,"extractions":[{"start_at":"2026-09-09T10:00:00+01:00","end_at":"2026-09-09T11:00:00+01:00","energy_kwh":20,"cost_total_pence":700,"soc_start":20,"soc_end":60,"confidence":0.95}]}
```

Returns `{summary, change_token, expires_in_seconds:600, preview:[...], warnings:[...]}` without saving charging sessions. Preview fields include `car_id`, `charge_start_at`, `charge_end_at`, `date`, `kwh`, `cost` (formatted GBP), `cost_pence`, `soc:{start,end}`, `location_id`, `location_name`, `network`, `source:"aster"`, `cost_basis`, `tariff`, `tariff_p_per_kwh`, `notes`, `charging_type`, `odometer_km`, `odometer`, `confidence`, `actual_charge_seconds`, `power_curve` (mapped `[seconds,soc,power_kw]` points). `id` is null until saved. Some fields can be null.

Show the preview and warnings to the user. Only after their explicit confirmation, call `commit_change` with `{"change_token":"..."}`. Returns `{"ok":true,"charge_ids":[123],"duplicates_skipped":0}`. A duplicate produces no new charge IDs and increments `duplicates_skipped`; existing user overrides are preserved.

Successful commit retries return the same receipt within the original ten-minute lifetime. Proposals/receipts are process-local and expire on restart. An expired/unknown token requires a fresh proposal and confirmation; database duplicate checks remain active. A SQLite writer reservation spans duplicate checking through the caller transaction commit across both Aster and Telegram; duplicate energy uses the prepared effective kWh. Commit checks car ownership and active state again. If car, tariff or location changes alter the reviewed values, commit rejects the stale preview and requires a fresh proposal and confirmation. Existing non-import change tokens remain single-use.

New Aster timestamps are normalized to Europe/London before correlation and storage, so equivalent UTC/BST representations deduplicate consistently. Existing Telegram timestamps are not rewritten; legacy records without reliable timezone provenance retain their existing matching behavior.

Each extraction accepts these fields (all optional; omit unknown readings):

| Field | Type / constraints |
| --- | --- |
| source | string up to 64 characters; default `unknown`; screenshot app identity, not saved session source |
| has_cost | boolean, default false; automatically true if either cost field is present |
| energy_kwh | finite nonnegative number |
| cost_total_pence | nonnegative integer |
| cost_per_kwh_pence | finite nonnegative number |
| start_at, end_at | ISO 8601 with explicit timezone offset; end cannot precede start |
| soc_start, soc_end | integer 0–100; end cannot be lower than start |
| location_name, location_short_name | string up to 128 characters |
| location_address | string up to 512 characters |
| network | string up to 128 characters |
| peak_kw | finite nonnegative number |
| confidence | finite 0–1 number; default 0, producing a review warning |
| odometer | finite nonnegative number; requires `odometer_unit` |
| odometer_unit | `mi` or `km` |
| actual_charge_seconds | positive integer |
| power_curve | up to 200 `[fraction, power_kw]` pairs, fraction 0–1, finite nonnegative power |

Unknown fields are rejected. One timed reading is required; untimed meter readings can join that one charge. Supply energy or both SoC endpoints. The existing screenshot correlation and cost/preview services are reused. No image/model API calls or geocoding run in this integration. Unmatched location text is retained; existing named locations can be matched. Telegram staging is untouched.

Failures return `{error:...}` (validation may add `details`). MCP schema validation may instead return the protocol's tool error. Do not report an import as saved unless `commit_change` returned `ok:true`.
