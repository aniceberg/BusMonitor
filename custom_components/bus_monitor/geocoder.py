"""OpenStreetMap (Overpass API) lookup of named roads around a point, with caching."""

from __future__ import annotations

import asyncio
import time

import aiohttp

from .streets import Way, parse_overpass

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "HomeAssistant-BusMonitor/0.1 (school bus location announcements)"
SEARCH_RADIUS_M = 450
CACHE_TTL_S = 7 * 24 * 3600  # roads rarely change; one lookup per ~55 m cell per week
CELL_DEG = 0.0005
MIN_INTERVAL_S = 2.0  # be polite to the public Overpass servers


class GeocodeError(Exception):
    """Lookup failed (network, rate limit, bad response)."""


class OverpassGeocoder:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str = OVERPASS_URL,
        radius_m: int = SEARCH_RADIUS_M,
    ) -> None:
        self._session = session
        self._url = url
        self._radius = radius_m
        self._cache: dict[tuple[int, int], tuple[float, list[Way]]] = {}
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    @staticmethod
    def _cell(lat: float, lon: float) -> tuple[int, int]:
        return round(lat / CELL_DEG), round(lon / CELL_DEG)

    async def ways_near(self, lat: float, lon: float) -> list[Way]:
        cell = self._cell(lat, lon)
        hit = self._cache.get(cell)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
            return hit[1]
        async with self._lock:
            hit = self._cache.get(cell)  # another caller may have filled it
            if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
                return hit[1]
            wait = MIN_INTERVAL_S - (time.monotonic() - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            ways = await self._fetch(lat, lon)
            self._last_call = time.monotonic()
            self._cache[cell] = (self._last_call, ways)
            return ways

    async def _fetch(self, lat: float, lon: float) -> list[Way]:
        query = (
            f"[out:json][timeout:20];"
            f'way(around:{self._radius},{lat:.6f},{lon:.6f})["highway"]["name"];'
            f"out body geom;"
        )
        try:
            async with self._session.post(
                self._url,
                data={"data": query},
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=25),
            ) as resp:
                if resp.status != 200:
                    raise GeocodeError(f"Overpass returned HTTP {resp.status}")
                return parse_overpass(await resp.json(content_type=None))
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise GeocodeError(str(err)) from err
