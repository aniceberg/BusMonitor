<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="custom_components/bus_monitor/brand/dark_logo@2x.png">
    <img src="custom_components/bus_monitor/brand/logo@2x.png" alt="Bus Monitor" width="460">
  </picture>
</p>

# Bus Monitor for Home Assistant

School-bus arrival alerts for Home Assistant, fed by a vehicle-tracking provider:
- a **Traccar** GPS server (tested with Traccar 4.1); your bus company gives you the server
  address and login;
- a **Bouncie** OBD-II tracker (see [docs/bouncie.md](docs/bouncie.md));
- **any GPS tracker already in Home Assistant**, from whichever integration made it (see
  [docs/ha_trackers.md](docs/ha_trackers.md)).

To use several providers, add Bus Monitor once per account (e.g. one Traccar server and one
Bouncie login). Each bus profile follows one vehicle from its entry.

- Pick one or several buses from the provider's vehicle list.
- Per bus *profile* (e.g. "Morning", "Afternoon"): a stop, a watch window,
  and any number of **checkpoints** ("about 10 / 5 / 2 minutes away").
- Polls the provider only while a profile is watching: inside its watch window, until the bus
  reaches the stop. Until the bus moves that day it polls once a minute, and it gives up on
  days the bus never comes (see [Holidays and summer](#holidays-and-summer)). "Where is the
  bus?" still works any time (it fetches once on demand).
- Fires a `bus_monitor_alert` event for each checkpoint, arrival, running-late
  and (optional) no-GPS-fix. Use any automation to announce it on Google Home.
- **Baseline recorder**: every completed trip's trail and checkpoint timings are
  stored, so after a few weeks `bus_monitor.suggest_checkpoints` tells you where the bus
  really is 10/5/2 minutes before the stop. *Shadow* checkpoints (announce off) let you
  trial new locations silently.

## Install
You need Home Assistant 2026.10 or newer. Installing from the Marketplace needs 2026.11, or HACS
on older versions.

1. Open **Settings → Marketplace**, search for **Bus Monitor** and choose **Install**. If Home
   Assistant asks for a restart, restart it. If the search finds nothing yet, add this repository
   by link in the Marketplace (that needs a GitHub connection).
2. Add the integration:

   [![Add Bus Monitor to Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=bus_monitor)

   Or go to Settings → Devices & services → Add integration → **Bus Monitor**.
3. Choose your provider:
   - **Traccar GPS server**: paste the server address and login. Copying the address from your
     browser is fine, with or without `http://`.
   - **Bouncie**: register a free app, then sign in. The setup screen walks you through it, and
     [docs/bouncie.md](docs/bouncie.md) has the details.
   - **A GPS tracker already in Home Assistant**: no login, just pick the tracker. See
     [docs/ha_trackers.md](docs/ha_trackers.md).
4. Choose the bus(es). Setup goes straight on to your first bus profile: its name, stop and
   schedule. The stop starts at your home, so drag the pin to the real stop. If you close that screen, choose **Add bus profile** under that
   provider on the Bus Monitor integration page.
5. Make alerts speak with the [announcement blueprint](#announcements-and-voice).

Each profile is listed on the integration page with its own device and entities. To change one,
open its ⋮ menu → **Reconfigure**:
   - **Edit the profile**: rename it, or change its bus, stop, schedule or school year. Its
     checkpoints, recorded trips and entity IDs are kept.
   - **Add an alert checkpoint** (repeat per alert), or **Remove checkpoints**.

   Delete a profile from the same ⋮ menu. The bus list shows every vehicle the
   Traccar login or Bouncie account can see, not only the ones picked at setup, so a new bus
   number next school year is just an edit (no need to remove and re-add the integration).
   *Announce as* (optional) sets what alerts and "where is the bus?" call the bus, e.g.
   "Daniel's bus"; otherwise the vehicle's name is used ("Bus" is added before a route number
   such as "12").
   Tip: tick *Use the bus's current position* while the bus is at the spot you want.

> Security (Traccar): the server only speaks plain HTTP and the login is shared by all parents, so
> the credentials and bus positions travel unencrypted. They're stored only in the Home
> Assistant config entry. Ask the vendor for HTTPS or a separate login if you can.

## Announcements and voice
The quickest way to hear alerts is the announcement blueprint. Pick a voice and speakers, and
optionally which alerts and profiles to announce:

[![Open the blueprint in Home Assistant](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Faniceberg%2FBusMonitor%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fbus_monitor%2Fannounce_bus_alerts.yaml)

Every alert fires a `bus_monitor_alert` event, and an automation speaks it. For anything else,
**[docs/automations.md](docs/automations.md) has paste-ready YAML** for Google Home, Amazon Echo and phones, plus "where is the bus?" for
Assist, Google and Alexa. Every alert carries a ready-to-speak sentence, e.g. "Bus 12 is about 10 minutes away.", "Bus 12 is at Elm Street.",
"Bus 12 has arrived." or "Bus 12 is running about 12 minutes late."

Event data: `message`, `kind`, `type` (`time`/`street` for checkpoints), `bus` (the *Announce as* name, else e.g. "Bus 12"), `profile`,
`profile_name`, `device_id`, `label`, `minutes`, `street`, `time`, `latitude`, `longitude`. Late alerts also carry `checkpoint` (the first missed one), `due` and `minutes_late`.

**Running late** is announced once per trip, and only when the bus is more than the profile's
"minutes behind schedule" past the time it's due at a checkpoint and hasn't reached that checkpoint,
any later one, or your stop. Due times come from the normal arrival time minus each checkpoint's
measured minutes-to-stop (its nominal minutes until 3 trips are recorded). A detour that skips one
checkpoint but reaches the next isn't treated as late.
Shadow crossings fire `bus_monitor_shadow` instead.

## Map panel
Bus Monitor adds a **Bus Monitor** page to the sidebar (turn it off under the provider's Configure).
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

## Holidays and summer
Neither Traccar nor Bouncie knows about routes or school days, only where the vehicle is, so
Bus Monitor watches for the bus itself to show it's running. There's no holiday calendar to keep
up to date:
- **Until the bus moves**, it polls once a minute instead of at the normal rate. "Moving" means a
  fix from today's window showing the bus faster than 2 m/s, or more than 200 m from where it was
  parked.
- **If it never moves** by the normal arrival time plus the "minutes behind schedule"
  tolerance, today counts as a no-bus day (a holiday or snow day). Polling stops and the status
  sensor shows `not_running`. Without a normal arrival time it watches until the window ends.
- **No false alarms.** "Running late" and "no GPS fix" are only announced once the bus has
  moved that day.
- **The school year ends.** Each profile has a *School year ends* date (the coming June 30 by
  default). After it the profile pauses: no polling, no alerts, status `season_over`, and a
  notice under Settings → Repairs. Before school starts, open the profile's ⋮ → **Reconfigure** → **Edit the profile** to check
  the times and stop (they often change), pick the new bus if it changed, and set the new end date. Tick *Forget recorded
  trips and relearn the route* if the route changed. Trips are kept for 60 days anyway, so
  last June's trips never place September's checkpoints.

## Entities
Per bus: a device with a `device_tracker` (live location). Per profile: its own device (linked to
its bus; profiles added from v0.7.0 get entity IDs like `sensor.morning_status`, while older ones
keep theirs) with status (`idle`, `en_route`, `near`,
`arrived`, `not_running`, `season_over`), last alert,
distance to stop, running-late, and per-checkpoint "actual minutes" (median of real trips,
with p10/p90/count as attributes).

## Services
- `bus_monitor.suggest_checkpoints` (`profile`, `minutes: [10,5,2]`) returns suggested coordinates plus
  the actual minutes-to-stop of each current checkpoint.
- `bus_monitor.describe_location` (`profile`, optional `tts_entity` + `media_player_entity`) returns `text` and details.
- `bus_monitor.reset_trip` (`profile`) clears today's state.

## Reporting a problem
On the Bus Monitor integration page, open the ⋮ menu of the Traccar server or Bouncie account and
choose **Download diagnostics**, then attach the file to a
[GitHub issue](https://github.com/aniceberg/BusMonitor/issues). It shows the provider, polling
state, schedules and checkpoint counts. It leaves out server addresses, logins, tokens, names,
vehicle ids and every coordinate, and refers to vehicles and profiles as `vehicle_1` and
`profile_1`. Schedule times such as the normal arrival time are included.

## Development
```bash
uv venv --python 3.14 && uv pip install pytest-homeassistant-custom-component ruff
.venv/bin/python -m pytest
TRACCAR_URL=http://your-server:8082 TRACCAR_USER=... TRACCAR_PASS=... .venv/bin/python scripts/probe.py   # list buses + positions
BOUNCIE_TOKEN=... .venv/bin/python scripts/bouncie_probe.py 10 30   # how often Bouncie positions refresh
```

## Where is the bus?
`bus_monitor.describe_location` answers with the street the bus is on, the cross streets either
side, its heading, and distance/minutes to your stop, and can speak it on your speakers. See
[docs/automations.md](docs/automations.md#where-is-the-bus-by-voice).

## Brand images
`custom_components/bus_monitor/brand/` holds the icon and logo (light and `dark_` variants) used by
HACS and the Home Assistant UI. Regenerate them with `.venv/bin/python scripts/make_brand.py`
(needs the Nunito Sans font, SIL Open Font License).

## Roadmap
- WebSocket push (`/api/socket`) instead of polling.
- Bouncie `tripData` webhooks: not needed so far, since polling returned a new position every 15 s on real trips (see docs/bouncie.md).
