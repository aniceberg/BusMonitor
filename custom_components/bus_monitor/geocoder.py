"""OpenStreetMap (Overpass API) lookup of named roads around a point, with caching.

The public Overpass servers are often busy, so this tries several mirrors, backs
off after a failure, and keeps a persistent cache: a bus route is the same every
day, so after the first few trips almost every lookup is answered locally.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import aiohttp

from .streets import Way, parse_overpass

OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
OVERPASS_URL = OVERPASS_URLS[0]
USER_AGENT = "HomeAssistant-BusMonitor (school bus location announcements)"
CELL_DEG = 0.002  # ~220 m cells; each is fetched once around its centre
SEARCH_RADIUS_M = 550  # covers any point in the cell plus ~400 m around it
CACHE_TTL_S = 30 * 24 * 3600  # roads rarely change
MIN_INTERVAL_S = 2.0  # be polite to the public servers
FAILURE_BACKOFF_S = 60.0


class GeocodeError(Exception):
    """Lookup failed (network, rate limit, bad response)."""


class OverpassGeocoder:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        urls: tuple[str, ...] = OVERPASS_URLS,
        cache: dict[str, Any] | None = None,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._session = session
        self._urls = urls
        # Serialisable cache: {"cells": {key: {"t": epoch, "ways": [ids]}}, "ways": {id: [...]}}
        self.cache: dict[str, Any] = cache or {"cells": {}, "ways": {}}
        self.cache.setdefault("cells", {})
        self.cache.setdefault("ways", {})
        self._on_change = on_change
        self._lock = asyncio.Lock()
        self._last_call = 0.0
        self._failed_until = 0.0

    @staticmethod
    def _cell(lat: float, lon: float) -> tuple[str, float, float]:
        i, j = round(lat / CELL_DEG), round(lon / CELL_DEG)
        return f"{i},{j}", i * CELL_DEG, j * CELL_DEG

    def _cached(self, key: str) -> list[Way] | None:
        cell = self.cache["cells"].get(key)
        if not cell or time.time() - cell["t"] > CACHE_TTL_S:
            return None
        ways = self.cache["ways"]
        return [
            Way(int(wid), w[0], tuple(w[1]), tuple(tuple(p) for p in w[2]))
            for wid in cell["ways"]
            if (w := ways.get(str(wid)))
        ]

    def _store(self, key: str, ways: list[Way]) -> None:
        for w in ways:
            self.cache["ways"][str(w.id)] = [w.name, list(w.nodes), [list(p) for p in w.geometry]]
        self.cache["cells"][key] = {"t": time.time(), "ways": [w.id for w in ways]}
        if self._on_change:
            self._on_change()

    async def ways_near(self, lat: float, lon: float) -> list[Way]:
        key, clat, clon = self._cell(lat, lon)
        if (hit := self._cached(key)) is not None:
            return hit
        async with self._lock:
            if (hit := self._cached(key)) is not None:
                return hit  # another caller filled it while we waited
            if time.monotonic() < self._failed_until:
                raise GeocodeError("street lookup servers are busy; retrying shortly")
            wait = MIN_INTERVAL_S - (time.monotonic() - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                ways = await self._fetch_any(clat, clon)
            except GeocodeError:
                self._failed_until = time.monotonic() + FAILURE_BACKOFF_S
                raise
            finally:
                self._last_call = time.monotonic()
            self._store(key, ways)
            return ways

    async def _fetch_any(self, lat: float, lon: float) -> list[Way]:
        errors = []
        for url in self._urls:
            try:
                return await self._fetch(url, lat, lon)
            except GeocodeError as err:
                errors.append(f"{url.split('/')[2]}: {err}")
        raise GeocodeError("; ".join(errors))

    async def _fetch(self, url: str, lat: float, lon: float) -> list[Way]:
        query = (
            f"[out:json][timeout:20];"
            f'way(around:{SEARCH_RADIUS_M},{lat:.6f},{lon:.6f})["highway"]["name"];'
            f"out body geom;"
        )
        try:
            async with self._session.post(
                url,
                data={"data": query},
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=25),
            ) as resp:
                if resp.status != 200:
                    raise GeocodeError(f"HTTP {resp.status}")
                return parse_overpass(await resp.json(content_type=None))
        except TimeoutError as err:
            raise GeocodeError("timed out") from err
        except (aiohttp.ClientError, ValueError) as err:
            raise GeocodeError(str(err) or type(err).__name__) from err
