"""IANA timezone catalog and canonicalization helpers."""

from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones


# tzdb retains compatibility links. Normalize links observed in PEKA data so
# tenant policy has one stable identifier while still accepting old clients.
IANA_TIMEZONE_ALIASES = {
    "Asia/Calcutta": "Asia/Kolkata",
    "Etc/UTC": "UTC",
    "Etc/GMT": "UTC",
    "GMT": "UTC",
}


def canonical_timezone(value: str) -> str:
    timezone_id = IANA_TIMEZONE_ALIASES.get(value.strip(), value.strip())
    try:
        ZoneInfo(timezone_id)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone must be a valid IANA timezone ID") from exc
    return timezone_id


@lru_cache
def iana_timezone_catalog() -> tuple[str, ...]:
    canonical = {
        IANA_TIMEZONE_ALIASES.get(timezone_id, timezone_id)
        for timezone_id in available_timezones()
    }
    canonical.add("UTC")
    return tuple(sorted(canonical))
