"""List buses and their latest positions from the Traccar server.

Usage (credentials come from the environment, never from the repo):

    TRACCAR_URL=http://your-server:8082 TRACCAR_USER=... TRACCAR_PASS=... \
        .venv/bin/python scripts/probe.py
"""

import asyncio
import os
import sys

import aiohttp
import homeassistant  # noqa: F401  (import first so its voluptuous shim loads cleanly)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from custom_components.bus_monitor.traccar_client import TraccarClient  # noqa: E402

BASE = os.environ["TRACCAR_URL"]


async def main() -> None:
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
        client = TraccarClient(session, BASE, os.environ["TRACCAR_USER"], os.environ["TRACCAR_PASS"])
        await client.login()
        devices = await client.devices()
        positions = {p.device_id: p for p in await client.positions()}
        print(f"{len(devices)} devices")
        for d in sorted(devices, key=lambda d: d.name):
            p = positions.get(d.id)
            where = f"{p.lat:.5f},{p.lon:.5f} {p.speed_mps * 2.237:.0f}mph {p.fix_time:%H:%M:%S}" if p else "no position"
            print(f"  id={d.id:<5} {d.name:<20} {d.status or '?':<8} {where}")


asyncio.run(main())
