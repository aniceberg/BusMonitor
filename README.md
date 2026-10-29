<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="custom_components/bus_monitor/brand/dark_logo@2x.png">
    <img src="custom_components/bus_monitor/brand/logo@2x.png" alt="Bus Monitor" width="460">
  </picture>
</p>

# Bus Monitor (Home Assistant / HACS)

School-bus arrival alerts for Home Assistant, fed by a vehicle-tracking provider:
- a **Traccar** GPS server (tested with Traccar 4.1); your bus company gives you the server
  address and login;
- a **Bouncie** OBD-II tracker (see [docs/bouncie.md](docs/bouncie.md)).

To use several providers, add Bus Monitor once per account (e.g. one Traccar server and one
Bouncie login). Each bus profile follows one vehicle from its entry.

- Pick one or several buses from the provider's vehicle list.
- Per bus *profile* (e.g. "Morning", "Afternoon"): a stop, a watch window,
  and any number of **checkpoints** ("about 10 / 5 / 2 minutes away").
- Fires a `bus_monitor_alert` event for each checkpoint, arrival, running-late
  and (optional) no-GPS-fix. Use any automation to announce it on Google Home.
- **Baseline recorder**: every completed trip's trail and checkpoint timings are
  stored, so after a few weeks `bus_monitor.suggest_checkpoints` tells you where the bus
  really is 10/5/2 minutes before the stop. *Shadow* checkpoints (announce off) let you
  trial new locations silently.

## Install
1. HACS -> Custom repositories -> add this repo as an *Integration*.
2. Install, restart Home Assistant, then Settings -> Devices & services -> Add -> **Bus Monitor**.
3. Choose **Traccar GPS server** and enter the server URL and shared login, or choose
   **Bouncie** and sign in (one-time app setup: [docs/bouncie.md](docs/bouncie.md)). Then
   choose the bus(es).
4. Configure -> **Add a bus profile**, then **Add an alert checkpoint** (repeat per alert).
   Tip: tick *Use the bus's current position* while the bus is at the spot you want.

> Security (Traccar): the server only speaks plain HTTP and the login is shared by all parents, so
> the credentials and bus positions travel unencrypted. They're stored only in the Home
> Assistant config entry. Ask the vendor for HTTPS or a separate login if you can.

## Announce on Google Home
Every alert fires a `bus_monitor_alert` event. Create an automation with an **Event** trigger
for `bus_monitor_alert` and a **Text-to-speech: Speak** action that targets your Google Home
speakers, with the message set to `{{ trigger.event.data.message }}`. Every alert carries a
ready-to-speak sentence, e.g. "Bus 12 is about 10 minutes away.", "Bus 12 is at Elm Street.",
"Bus 12 has arrived." or "Bus 12 is running about 12 minutes late."

Event data: `message`, `kind`, `type` (`time`/`street` for checkpoints), `bus` (e.g. "Bus 12"), `profile`,
`profile_name`, `device_id`, `label`, `minutes`, `street`, `time`, `latitude`, `longitude`. Late alerts also carry `checkpoint` (the first missed one), `due` and `minutes_late`.

**Running late** is announced once per trip, and only when the bus is more than the profile's
"minutes behind schedule" past the time it's due at a checkpoint and hasn't reached that checkpoint,
any later one, or your stop. Due times come from the normal arrival time minus each checkpoint's
measured minutes-to-stop (its nominal minutes until 3 trips are recorded). A detour that skips one
checkpoint but reaches the next isn't treated as late.
Shadow crossings fire `bus_monitor_shadow` instead.

## Map panel
Bus Monitor adds a **Bus Monitor** page to the sidebar (turn it off under Configure → Settings).
For each bus profile it shows:
- your stop, the bus's live position, the latest recorded trip and today's trip so far;
- the **checkpoints**, in two types:
  - **Minutes away** ("Bus 12 is about 10 minutes away"). Tick **Auto-place** and, once 5 trips are
    recorded, the checkpoint moves itself to where the bus usually is that many minutes before your
    stop. Late-running or detour days are left out (only the trips that agree with the typical one are
    averaged), and the position updates after every trip.
  - **Street** ("Bus 12 is at Elm Street"): named after the nearest cross street automatically
    (editable); not part of the late check.

  Drag manual checkpoints to move them, add one by clicking the map or at the bus's current position,
  change name/minutes/radius, untick *Announce* for a silent trial, then **Save changes**
  (administrators only);
- **minutes-away clocks** along the route: each alarm clock marks where the bus usually is that many
  minutes before your stop (every minute when zoomed in), so you can drop checkpoints exactly;
- a **route heatmap** built from every recorded trip: the usual route is the darkest trace and
  occasional detours show lighter, depending on how often the bus takes them.

Trips are recorded while the bus is inside the profile's watch window, so start the window early
enough to cover the whole route if you want the heatmap to show all of it.
Map data © OpenStreetMap contributors.

## Entities
Per bus: `device_tracker` (live location). Per profile: status, last alert,
distance to stop, running-late, and per-checkpoint "actual minutes" (median of real trips,
with p10/p90/count as attributes).

## Services
- `bus_monitor.suggest_checkpoints` (`profile`, `minutes: [10,5,2]`) returns suggested coordinates plus
  the actual minutes-to-stop of each current checkpoint.
- `bus_monitor.describe_location` (`profile`, optional `tts_entity` + `media_player_entity`) returns `text` and details.
- `bus_monitor.reset_trip` (`profile`) clears today's state.

## Development
```bash
uv venv --python 3.14 && uv pip install pytest-homeassistant-custom-component ruff
.venv/bin/python -m pytest
TRACCAR_URL=http://your-server:8082 TRACCAR_USER=... TRACCAR_PASS=... .venv/bin/python scripts/probe.py   # list buses + positions
BOUNCIE_TOKEN=... .venv/bin/python scripts/bouncie_probe.py 10 30   # how often Bouncie positions refresh
```

## Where is the bus? (Google Home)
`bus_monitor.describe_location` answers with the street the bus is on, the cross streets either
side, its heading, and distance/minutes to your stop, and can speak it on your speakers.
See [docs/google_home.md](docs/google_home.md) and [examples/where_is_the_bus.yaml](examples/where_is_the_bus.yaml).

## Brand images
`custom_components/bus_monitor/brand/` holds the icon and logo (light and `dark_` variants) used by
HACS and the Home Assistant UI. Regenerate them with `.venv/bin/python scripts/make_brand.py`
(needs the Nunito Sans font, SIL Open Font License).

## Roadmap
- WebSocket push (`/api/socket`) instead of polling; blueprint automation.
- Bouncie `tripData` webhooks for live positions (needs Home Assistant reachable over HTTPS).
