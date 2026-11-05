"""Constants for the Reve integration."""

from __future__ import annotations

import math
from typing import Final

DOMAIN: Final = "reve"
API_BASE_URL: Final = "https://www.mapareve.es/api/external/v1"

SUBENTRY_TYPE_CHARGER: Final = "charger"

CONF_API_KEY: Final = "api_key"
CONF_RATE_TIER: Final = "rate_tier"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_EVSE_ID: Final = "evse_id"
CONF_EVSE_UID: Final = "evse_uid"
CONF_LOCATION_ID: Final = "location_id"
CONF_LOCATION_NAME: Final = "location_name"
CONF_CONNECTORS: Final = "connectors"
CONF_COORDINATES: Final = "coordinates"
CONF_PHYSICAL_REFERENCE: Final = "physical_reference"

# Rate-limit tiers published in the API docs (requests per hour).
TIER_STANDARD: Final = "standard"
TIER_SPECIAL: Final = "special"
RATE_LIMITS: Final = {
    # tier: (requests per URL per hour, total requests per hour)
    TIER_STANDARD: (5, 1000),
    TIER_SPECIAL: (100, 3000),
}
DEFAULT_INTERVAL_MINUTES: Final = {TIER_STANDARD: 20, TIER_SPECIAL: 5}
MAX_INTERVAL_MINUTES: Final = 24 * 60
# Only use this share of the quota so reloads / validation calls never hit a 429.
QUOTA_SAFETY: Final = 0.8

# EVSE status values reported by the API.
STATUS_AVAILABLE: Final = "AVAILABLE"
STATUS_CHARGING: Final = "CHARGING"
STATUS_FAULT: Final = frozenset({"INOPERATIVE", "OUTOFORDER", "REMOVED"})
STATUS_OPTIONS: Final = [
    "available",
    "blocked",
    "charging",
    "inoperative",
    "outoforder",
    "planned",
    "removed",
    "reserved",
    "unknown",
]

# Availability watch.
ATTR_NOTIFY_ENTITIES: Final = "notify_entity_id"
ATTR_DURATION: Final = "duration"
ATTR_MESSAGE: Final = "message"
SERVICE_WATCH: Final = "watch_availability"
SERVICE_CANCEL_WATCH: Final = "cancel_watch"
EVENT_CHARGER_AVAILABLE: Final = "reve_charger_available"
STORAGE_VERSION: Final = 1


def min_interval_minutes(tier: str, chargers: int) -> int:
    """Shortest polling interval (minutes) that stays inside the API quota."""
    per_url, total = RATE_LIMITS[tier]
    per_url_seconds = 3600 / max(1, int(per_url * QUOTA_SAFETY))
    total_seconds = 3600 * max(1, chargers) / (total * QUOTA_SAFETY)
    return max(1, math.ceil(max(per_url_seconds, total_seconds) / 60))
