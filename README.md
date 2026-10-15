# Bus Monitor (Home Assistant / HACS)

School-bus arrival alerts for Home Assistant, fed by a **Traccar** GPS server
(tested with Traccar 4.1). Your bus company gives you the server address and login.

- Pick one or several buses from the server's device list.
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
3. Enter the server URL, shared login, and choose the bus(es).
4. Configure -> **Add a bus profile**, then **Add an alert checkpoint** (repeat per alert).
   Tip: tick *Use the bus's current position* while the bus is at the spot you want.

> Security: the server only speaks plain HTTP and the login is shared by all parents, so
> the credentials and bus positions travel unencrypted. They're stored only in the Home
> Assistant config entry. Ask the vendor for HTTPS or a separate login if you can.

## Announce on Google Home
```yaml
automation:
  - alias: Bus alerts on Google Home
    triggers:
      - trigger: event
        event_type: bus_monitor_alert
    actions:
      - action: tts.speak
        target:
          entity_id: tts.google_translate_en_com   # your TTS entity
        data:
          media_player_entity_id: media_player.kitchen_display
          message: >-
            {% set d = trigger.event.data %}
            {% if d.kind == 'checkpoint' %}{{ d.bus }} is about {{ d.minutes }} minutes away.
            {% elif d.kind == 'arrived' %}{{ d.bus }} has arrived.
            {% elif d.kind == 'late' %}{{ d.bus }} is running late.
            {% else %}{{ d.bus }} has stopped reporting its location.{% endif %}
```
Event data: `kind`, `profile`, `device_id`, `bus`, `label`, `minutes`, `time`, `latitude`, `longitude`.
Shadow crossings fire `bus_monitor_shadow` instead.

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
```

## Where is the bus? (Google Home)
`bus_monitor.describe_location` answers with the street the bus is on, the cross streets either
side, its heading, and distance/minutes to your stop, and can speak it on your speakers.
See [docs/google_home.md](docs/google_home.md) and [examples/where_is_the_bus.yaml](examples/where_is_the_bus.yaml).

## Roadmap
- WebSocket push (`/api/socket`) instead of polling; blueprint automation.
