# Reve EV chargers for Home Assistant

Monitor public EV chargers listed on [Mapa Reve](https://www.mapareve.es) and get notified when an occupied one is free again.

## Installation

**HACS (custom repository):** HACS → ⋮ → *Custom repositories* → add `https://github.com/ArnyminerZ/ha-reve` as type *Integration* → install *Reve* → restart Home Assistant. Then *Settings → Devices & services → Add integration → Reve*.

**Manual:** copy `custom_components/reve` into your Home Assistant `custom_components` folder and restart.

## How it works

* **Hub (gateway)** – add the integration once with your personal Reve API key.
* **Chargers (subentries)** – use *Add charger* on the integration and enter the EVSE id (e.g. `ES*IBD*E142206*1`). Each charger becomes a device; each of its connectors a child device.
* The API key is validated with one cheap call; the charger is validated against `/evses/{id}`, and its static data (connectors, power) is stored so it is not re-fetched.

### Entities per charger

| Entity | Notes |
|---|---|
| Status sensor | available / charging / reserved / blocked / out of order … (main entity) |
| Free, Problem | binary sensors |
| Last status change, Availability alert until | timestamps |
| Availability alert | `event` entity, fires `available` |
| Connector *n* (child device) | max power, max current, connector type |

## Get notified when a charger is free

Call the action **Reve: Notify when available** (`reve.watch_availability`) on the status sensor:

```yaml
action: reve.watch_availability
target:
  entity_id: sensor.garage
data:
  duration: { hours: 3 }          # up to 7 days
  notify_entity_id:
    - notify.mobile_app_phone     # any notify entity; omit for a persistent notification
  message: "Charger is free!"     # optional
```

When the status becomes `AVAILABLE` within the window the alert is sent once, the `event` entity fires and the `reve_charger_available` bus event is emitted. Cancel with `reve.cancel_watch`. Pending alerts survive restarts. Because they are plain actions, a dashboard button or a phone notification action can arm them too.

## API limits (important)

Reve limits each key per hour: **standard keys 5 requests per URL and 1000 in total; special keys 100 / 3000**. Since every charger status is its own URL, the default polling is **every 20 minutes** (standard) or 5 minutes (special). Choose your plan when adding the integration; the polling interval option cannot go below what the quota allows. Reloading the integration re-polls every charger, which counts against the quota. Alerts are therefore only as fast as your polling interval.

## Requirements

Home Assistant 2026.11 (config subentries, child devices, integration categories).

## Development

```
uv venv && uv pip install homeassistant pytest-homeassistant-custom-component
pytest
```
