"""Minimal async client for the Mapa Reve external API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from aiohttp import ClientError, ClientSession
from homeassistant.util import dt as dt_util
from yarl import URL

from .const import API_BASE_URL


class ReveError(Exception):
    """Base error."""


class ReveConnectionError(ReveError):
    """The API could not be reached."""


class ReveAuthError(ReveError):
    """The API key was rejected."""


class ReveNotFoundError(ReveError):
    """The requested resource does not exist."""


class ReveRateLimitError(ReveError):
    """The hourly quota was exceeded (HTTP 429)."""

    def __init__(self, retry_after: int | None = None) -> None:
        super().__init__("Rate limit exceeded")
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class ReveStatus:
    """Live status of an EVSE."""

    status: str
    last_updated: datetime | None


class ReveApi:
    """Client for www.mapareve.es."""

    def __init__(self, session: ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        # Keep "*" unescaped: EVSE ids look like ES*IBD*E142206*1 and the
        # per-URL rate limit is applied on the canonical URL.
        url = URL(f"{API_BASE_URL}{path}", encoded=True)
        if params:
            url = url.with_query(params)
        try:
            async with self._session.get(
                url, headers={"x-api-key": self._api_key}, timeout=30
            ) as resp:
                if resp.status in (401, 403):
                    raise ReveAuthError
                if resp.status == 404:
                    raise ReveNotFoundError
                if resp.status == 429:
                    retry = resp.headers.get("Retry-After", "")
                    raise ReveRateLimitError(int(retry) if retry.isdigit() else None)
                if resp.status >= 400:
                    raise ReveError(f"Unexpected HTTP {resp.status}")
                return await resp.json(content_type=None)
        except ClientError as err:
            raise ReveConnectionError(str(err)) from err
        except TimeoutError as err:
            raise ReveConnectionError("Timeout") from err

    async def validate(self) -> None:
        """Check that the API key works (cheap call on its own URL)."""
        await self._get("/cpos", {"limit": 1})

    async def get_evse(self, evse_id: str) -> dict[str, Any]:
        """Return the static description of an EVSE."""
        data = await self._get(f"/evses/{evse_id}")
        if isinstance(data, list):
            if not data:
                raise ReveNotFoundError
            data = data[0]
        return data

    async def get_status(self, evse_id: str) -> ReveStatus:
        """Return the live status of an EVSE."""
        data = await self._get(f"/evses/{evse_id}/status")
        if isinstance(data, list):
            if not data:
                raise ReveNotFoundError
            data = data[0]
        return ReveStatus(
            status=str(data.get("status", "UNKNOWN")).upper(),
            last_updated=dt_util.parse_datetime(data.get("last_status_updated") or ""),
        )
