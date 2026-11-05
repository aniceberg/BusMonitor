# Contributing

## Development
```bash
uv venv --python 3.14 && uv pip install pytest-homeassistant-custom-component ruff
.venv/bin/python -m pytest
TRACCAR_URL=http://your-server:8082 TRACCAR_USER=... TRACCAR_PASS=... .venv/bin/python scripts/probe.py   # list buses + positions
BOUNCIE_TOKEN=... .venv/bin/python scripts/bouncie_probe.py 10 30   # how often Bouncie positions refresh
```

## Brand images
`custom_components/bus_monitor/brand/` holds the icon and logo (light and `dark_` variants) used by
HACS and the Home Assistant UI. Regenerate them with `.venv/bin/python scripts/make_brand.py`
(needs the Nunito Sans font, SIL Open Font License).

## Roadmap
- WebSocket push (`/api/socket`) instead of polling.
- Bouncie `tripData` webhooks: not needed so far, since polling returned a new position every 15 s on real trips (see [docs/bouncie.md](docs/bouncie.md)).
