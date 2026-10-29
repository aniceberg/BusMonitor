"""Watch how often Bouncie's REST API refreshes a vehicle's location during a drive.

BusMonitor polls GET /v1/vehicles. This shows whether that is fresh enough for alerts: run it
while the vehicle is driving and look at the "moved after" column.

Usage (the token comes from the environment, never from the repo). Copy the access token from
your Bouncie entry in .storage/core.config_entries, or from your own OAuth test:

    BOUNCIE_TOKEN=... .venv/bin/python scripts/bouncie_probe.py [interval_seconds] [minutes]
"""

import asyncio
import os
import sys
import time

import aiohttp
import homeassistant  # noqa: F401  (import first so its voluptuous shim loads cleanly)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from custom_components.bus_monitor.providers.bouncie import (  # noqa: E402
    BouncieClient,
    FixedToken,
    vehicle_name,
)

INTERVAL = float(sys.argv[1]) if len(sys.argv) > 1 else 10
MINUTES = float(sys.argv[2]) if len(sys.argv) > 2 else 30


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        client = BouncieClient(session, FixedToken({"access_token": os.environ["BOUNCIE_TOKEN"]}))
        names = {v["imei"]: vehicle_name(v) for v in await client.vehicles()}
        print(f"{len(names)} vehicles: {', '.join(names.values())}")
        last: dict[str, tuple[float, float, str]] = {}
        moved_at: dict[str, float] = {}
        gaps: dict[str, list[float]] = {}
        end = time.monotonic() + MINUTES * 60
        while time.monotonic() < end:
            now = time.monotonic()
            for p in await client.positions():
                key = (p.lat, p.lon, p.fix_time.isoformat())
                gap = ""
                if last.get(p.device_id) != key:
                    if p.device_id in moved_at:
                        secs = now - moved_at[p.device_id]
                        gaps.setdefault(p.device_id, []).append(secs)
                        gap = f"moved after {secs:4.0f}s"
                    moved_at[p.device_id] = now
                    last[p.device_id] = key
                print(
                    f"{time.strftime('%H:%M:%S')}  {names.get(p.device_id, p.device_id):<20} "
                    f"{p.lat:.5f},{p.lon:.5f} {p.speed_mps * 2.237:3.0f}mph "
                    f"fix {p.fix_time:%H:%M:%S}  {gap}"
                )
            await asyncio.sleep(INTERVAL)
        for imei, g in gaps.items():
            print(f"{names.get(imei, imei)}: {len(g)} updates, median gap {sorted(g)[len(g) // 2]:.0f}s")


asyncio.run(main())
