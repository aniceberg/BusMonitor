# Reference

The details behind Bus Monitor, for anyone building automations or wondering why it did something.

## When it checks the bus
Bus Monitor asks for positions only while a profile is watching: inside its watch window, until the
bus reaches the stop.

Until the bus moves that day it checks once a minute. "Moving" means a fix from today's window
showing the bus faster than 2 m/s, or more than 200 m from where it was parked.

"Where is the bus?" works at any time, because it fetches one position on demand.

## Running late
"Running late" is announced once per trip. It fires only when the bus is more than the profile's
"minutes behind schedule" past the time it's due at a checkpoint and hasn't reached that checkpoint,
any later one, or your stop.

Due times come from the normal arrival time minus each checkpoint's measured minutes to the stop.
Until 3 trips are recorded, the checkpoint's own minutes setting is used. A detour that skips one
checkpoint but reaches the next isn't treated as late.

## Holidays and summer
Trackers know where a vehicle is, but not its route or school days. So Bus Monitor watches for the
bus itself to show it's running, and there's no holiday calendar to maintain.

- **If the bus never moves** by the normal arrival time plus the "minutes behind schedule" tolerance,
  today counts as a no-bus day. Checks stop and the status sensor shows `not_running`. Without a
  normal arrival time, it watches until the window ends.
- **"Running late" and "no GPS fix"** are only announced once the bus has moved that day.
- **After the *School year ends* date** (the coming June 30 by default), the profile pauses: no
  checks, no alerts, status `season_over`, and a notice under Settings → Repairs.
- **Recorded trips** are kept for 60 days, so last June's trips never place September's checkpoints.

## Checkpoints
- **Auto-place:** once 5 trips are recorded, a minutes-away checkpoint moves to where the bus usually
  is that many minutes before your stop. Late-running and detour days are left out, because only the
  trips that agree with the typical one are averaged. The position updates after every trip.
- **Street checkpoints** are named after the nearest cross street (you can edit the name) and aren't
  part of the running-late check.
- **Silent trial:** untick *Announce* to try a new spot. Crossings then fire `bus_monitor_shadow`
  instead of an alert.

## Names in alerts
Alerts and "where is the bus?" use the profile's *Announce as* name. Without one they use the vehicle's
name, and add "Bus" before a route number such as "12".

## Map
To hide the sidebar page, open your source's **Configure** on the integration page.

Trips are recorded while the bus is inside the profile's watch window, so start the window early
enough to cover the whole route if you want the map to show all of it.

Each alarm clock on the map marks where the bus usually is that many minutes before your stop, with
one for every minute when zoomed in. The route heatmap is built from every recorded trip: the usual
route is darkest, and occasional detours are lighter.

Map data © OpenStreetMap contributors.

## Alert event data
Every alert fires a `bus_monitor_alert` event with these fields:

`message`, `kind`, `type` (`time` or `street` for checkpoints), `bus` (the *Announce as* name, else
e.g. "Bus 12"), `profile`, `profile_name`, `device_id`, `label`, `minutes`, `street`, `time`,
`latitude`, `longitude`.

Late alerts also carry `checkpoint` (the first one missed), `due` and `minutes_late`.

## Entities
- **Per bus:** a device with a `device_tracker` showing its live location.
- **Per profile:** its own device, linked to its bus. Profiles added from v0.7.0 get entity IDs like
  `sensor.morning_status`, and older ones keep theirs. Each profile has:
  - status: `idle`, `en_route`, `near`, `arrived`, `not_running` or `season_over`
  - last alert
  - distance to stop
  - running late
  - "actual minutes" per checkpoint: the median of real trips, with p10, p90 and count as attributes

## Services
- `bus_monitor.describe_location` (`profile`, optional `tts_entity` and `media_player_entity`) returns
  `text` and details: the street the bus is on, the cross streets either side, its heading, and the
  distance and minutes to your stop. It can also speak the answer on your speakers.
- `bus_monitor.suggest_checkpoints` (`profile`, `minutes: [10, 5, 2]`) returns suggested coordinates
  from recorded trips, plus the actual minutes to the stop from each current checkpoint.
- `bus_monitor.reset_trip` (`profile`) clears today's alert state.
