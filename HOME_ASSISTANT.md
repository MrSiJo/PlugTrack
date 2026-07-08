# PlugTrack → Home Assistant

PlugTrack can publish a summary of your EV charging data to an MQTT broker, which Home
Assistant reads as native `mqtt:` sensors — tiles on a dashboard, an EV-charging source in
the Energy dashboard, and triggers for automations ("notify me when a charge is logged").

No add-on, no custom integration, no polling: PlugTrack **pushes** one retained JSON message
and Home Assistant subscribes to it.

## How it works

```
PlugTrack ──publish (retained)──▶ MQTT broker ──subscribe──▶ Home Assistant mqtt: sensors
```

- PlugTrack publishes to **`<base_topic>/summary`** (default `plugtrack/summary`):
  - **hourly** (scheduler job), and
  - **immediately after every charge saved** via the Telegram bot.
- The message is **retained**, so Home Assistant repopulates all sensors instantly after a
  restart — even if PlugTrack is down at the time.
- Publishing is best-effort: a broker outage is logged and swallowed, and never breaks a
  charge save or the scheduler.

## PlugTrack configuration

Everything lives in **Admin → MQTT / Home Assistant**:

| Setting | Default | Notes |
|---|---|---|
| Publish to MQTT / Home Assistant | on | Master switch — turns the hourly job and save-hook on/off. |
| Broker host | — | Hostname or IP of your MQTT broker (often the HA Mosquitto add-on). |
| Broker port | `1883` | |
| Broker username / password | — | Leave blank for anonymous brokers. The password is stored encrypted at rest. |
| Base topic | `plugtrack` | The summary is published to `<base topic>/summary`. |

Changes apply on the next publish — no restart needed.

## The payload

One JSON document for the primary (first active) car. All values are **numbers in
display-ready units** — costs in £ (GBP), distances in miles — so the HA sensors can carry
proper `device_class` / `state_class` without template maths:

```json
{
  "car": "Cupra Born",
  "last_charge": {
    "kwh": 41.2,
    "cost_gbp": 8.24,
    "network": "Osprey",
    "location": "Osprey (Land's End)",
    "end_soc_pct": 82,
    "ts": "2026-07-06T21:14:00"
  },
  "cost_per_mile_gbp": 0.11,
  "battery_soc_pct": 82,
  "odometer_mi": 12350.0,
  "annual_mileage": {
    "target_mi": 6000.0,
    "projected_mi": 11590.6,
    "pace": "under"
  },
  "month": {
    "spend_gbp": 42.10,
    "energy_kwh": 210.4,
    "miles": 640.0,
    "home_pct": 55,
    "public_pct": 45
  },
  "lifetime": {
    "energy_kwh": 3120.7,
    "cost_gbp": 610.44
  }
}
```

| Field | Meaning |
|---|---|
| `car` | Make + model of the primary active car. |
| `last_charge.*` | The most recent saved session: energy, cost, network, resolved location name, end state-of-charge, end timestamp. |
| `cost_per_mile_gbp` | Rolling 30-day cost per mile. |
| `battery_soc_pct` | Last-known battery level (end SoC of the latest charge). |
| `odometer_mi` | Current odometer — from mileage tracking if enabled, else the latest session's reading. |
| `annual_mileage.*` | Annual allowance target, projected year-end miles, and pace (`under` / `over`). |
| `month.*` | Month-to-date spend, energy, miles driven, and home/public kWh split. |
| `lifetime.*` | Lifetime energy and cost across the car's history. |

Fields without data (e.g. no odometer readings yet) are `null` — the matching HA sensor shows
`unavailable` rather than a wrong number.

## Home Assistant setup

### 1. Prerequisite

Home Assistant's [MQTT integration](https://www.home-assistant.io/integrations/mqtt/)
connected to the **same broker** PlugTrack publishes to.

### 2. Sensors

Add these to `configuration.yaml` under `mqtt:` (create the block if you don't have one),
then run **Developer tools → Check configuration** and restart. Because the message is
retained, every sensor populates the moment HA starts.

```yaml
mqtt:
  sensor:
    - name: "PlugTrack - Last Charge Energy"
      state_topic: "plugtrack/summary"
      value_template: "{{ value_json.last_charge.kwh }}"
      unit_of_measurement: "kWh"
      device_class: energy
      state_class: measurement

    - name: "PlugTrack - Last Charge Cost"
      state_topic: "plugtrack/summary"
      value_template: "{{ value_json.last_charge.cost_gbp }}"
      unit_of_measurement: "GBP"
      device_class: monetary

    - name: "PlugTrack - Last Charge Network"
      state_topic: "plugtrack/summary"
      value_template: "{{ value_json.last_charge.network }}"

    - name: "PlugTrack - Last Charge Location"
      state_topic: "plugtrack/summary"
      value_template: "{{ value_json.last_charge.location }}"

    - name: "PlugTrack - Last Charge End SoC"
      state_topic: "plugtrack/summary"
      value_template: "{{ value_json.last_charge.end_soc_pct }}"
      unit_of_measurement: "%"
      device_class: battery
      state_class: measurement

    - name: "PlugTrack - Cost Per Mile"
      state_topic: "plugtrack/summary"
      value_template: "{{ value_json.cost_per_mile_gbp }}"
      unit_of_measurement: "GBP"
      device_class: monetary

    - name: "PlugTrack - Battery SoC"
      state_topic: "plugtrack/summary"
      value_template: "{{ value_json.battery_soc_pct }}"
      unit_of_measurement: "%"
      device_class: battery
      state_class: measurement

    - name: "PlugTrack - Odometer"
      state_topic: "plugtrack/summary"
      value_template: "{{ value_json.odometer_mi }}"
      unit_of_measurement: "mi"
      state_class: total_increasing

    - name: "PlugTrack - Annual Mileage Pace"
      state_topic: "plugtrack/summary"
      value_template: "{{ value_json.annual_mileage.pace }}"

    - name: "PlugTrack - Month Spend"
      state_topic: "plugtrack/summary"
      value_template: "{{ value_json.month.spend_gbp }}"
      unit_of_measurement: "GBP"
      device_class: monetary

    - name: "PlugTrack - Month Energy"
      state_topic: "plugtrack/summary"
      value_template: "{{ value_json.month.energy_kwh }}"
      unit_of_measurement: "kWh"
      device_class: energy
      state_class: total_increasing

    - name: "PlugTrack - Month Miles"
      state_topic: "plugtrack/summary"
      value_template: "{{ value_json.month.miles }}"
      unit_of_measurement: "mi"
      state_class: measurement

    - name: "PlugTrack - Month Home Percent"
      state_topic: "plugtrack/summary"
      value_template: "{{ value_json.month.home_pct }}"
      unit_of_measurement: "%"
      state_class: measurement

    - name: "PlugTrack - Lifetime Energy"
      state_topic: "plugtrack/summary"
      value_template: "{{ value_json.lifetime.energy_kwh }}"
      unit_of_measurement: "kWh"
      device_class: energy
      state_class: total_increasing

    - name: "PlugTrack - Lifetime Cost"
      state_topic: "plugtrack/summary"
      value_template: "{{ value_json.lifetime.cost_gbp }}"
      unit_of_measurement: "GBP"
      device_class: monetary
```

If you changed the base topic in Admin, change `plugtrack/summary` to match.

### 3. Dashboard cards

Any card type works — the entities are ordinary sensors. A simple starting point:

```yaml
type: entities
title: EV Charging
entities:
  - entity: sensor.plugtrack_last_charge_energy
    name: Last charge
  - entity: sensor.plugtrack_last_charge_cost
    name: Cost
  - entity: sensor.plugtrack_last_charge_location
    name: Where
  - entity: sensor.plugtrack_month_spend
    name: This month
  - entity: sensor.plugtrack_battery_soc
    name: Battery
```

Or a tile-based view (works well in the modern *sections* layout):

```yaml
type: grid
cards:
  - type: heading
    heading: Last charge
    icon: mdi:battery-charging
  - type: tile
    entity: sensor.plugtrack_last_charge_energy
    name: Energy
  - type: tile
    entity: sensor.plugtrack_last_charge_cost
    name: Cost
  - type: tile
    entity: sensor.plugtrack_last_charge_end_soc
    name: Ended at
  - type: tile
    entity: sensor.plugtrack_cost_per_mile
    name: Cost / mile (30d)
  - type: heading
    heading: This month
    icon: mdi:calendar-month
  - type: tile
    entity: sensor.plugtrack_month_spend
    name: Spend
  - type: tile
    entity: sensor.plugtrack_month_energy
    name: Energy
  - type: tile
    entity: sensor.plugtrack_month_miles
    name: Miles driven
  - type: tile
    entity: sensor.plugtrack_month_home_percent
    name: Home charging
```

A long-term chart once statistics have accumulated (needs a few days of data):

```yaml
type: statistics-graph
title: Monthly charging energy
chart_type: bar
period: month
days_to_show: 365
stat_types:
  - change
entities:
  - sensor.plugtrack_lifetime_energy
```

### 4. Energy dashboard

`sensor.plugtrack_lifetime_energy` is a `total_increasing` kWh sensor, so it slots straight
into the Energy dashboard:

**Settings → Dashboards → Energy → Individual devices → Add device** →
pick **PlugTrack - Lifetime Energy**.

Your EV charging then appears in the per-device consumption breakdown. Note that Home
Assistant only attaches cost tracking to grid/gas *sources*, not individual devices — use the
`sensor.plugtrack_lifetime_cost` / `sensor.plugtrack_month_spend` sensors on a dashboard card
for the money view.

### 5. Automations

The sensors update the moment a charge is saved, so they make good triggers:

```yaml
alias: Notify on EV charge logged
triggers:
  - trigger: state
    entity_id: sensor.plugtrack_last_charge_energy
conditions:
  - condition: template
    value_template: "{{ trigger.from_state.state not in ['unknown', 'unavailable'] }}"
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: "EV charge logged"
      message: >-
        {{ states('sensor.plugtrack_last_charge_energy') }} kWh at
        {{ states('sensor.plugtrack_last_charge_location') }} —
        £{{ states('sensor.plugtrack_last_charge_cost') }}
```

## FAQ

**Why not a HACS custom integration?**
MQTT already delivers first-class native entities with almost no moving parts. A custom
integration would need an API to poll — PlugTrack's web API is cookie-session-only by design —
and would add a maintenance surface (HACS packaging, HA version churn) for no functional gain
over the retained-message pattern. If zero-YAML setup ever becomes a goal, the natural next
step is **MQTT discovery** (PlugTrack publishing `homeassistant/sensor/.../config` topics so
entities appear automatically) — still no custom integration required.

**Multi-car?**
The summary covers the *primary active* car. Per-car topics
(`plugtrack/car/<id>/summary`) are a possible future extension.

**A sensor shows `unavailable`.**
Its source field is `null` — e.g. no odometer readings yet, or no charges this month. It
recovers on the next publish that carries the value.

**Nothing is arriving on the topic.**
Check Admin → MQTT / Home Assistant is enabled and the broker details are right, then watch
the topic directly: `mosquitto_sub -h <broker> -u <user> -P <pass> -t 'plugtrack/#' -v`.
A retained message should print immediately. PlugTrack logs publish failures in the API
container's log.
