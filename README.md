<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="custom_components/bus_monitor/brand/dark_logo@2x.png">
    <img src="custom_components/bus_monitor/brand/logo@2x.png" alt="Bus Monitor" width="460">
  </picture>
</p>

# Bus Monitor for Home Assistant

Hear when the school bus is getting close. Bus Monitor follows the bus's GPS and announces it on your
speakers as it nears your stop.

- **Alerts as it gets close:** "Bus 12 is about 10 minutes away." "Bus 12 is at Elm Street." "Bus 12 has arrived."
- **Running late:** "Bus 12 is running about 12 minutes late."
- **Ask by voice:** "Where is the bus?" gets you the street, the nearest cross streets and the time to your stop.
- **Live map:** see the bus, your stop and the usual route in the Home Assistant sidebar.
- **Learns the route:** alert points can place themselves after 5 recorded trips.
- **Quiet on days off:** no false alarms on holidays or snow days, and it pauses for the summer.

## What you need
- Home Assistant 2026.10 or newer
- One of these sources for the bus's location:

| Source | Use it if | To connect |
| --- | --- | --- |
| **Traccar GPS server** | Your bus company gave you a Traccar tracking address and login | Paste the address and login |
| **[Bouncie](docs/bouncie.md)** | A Bouncie tracker is plugged into the vehicle | Register a free app, then sign in. Setup walks you through it |
| **[A GPS tracker already in Home Assistant](docs/ha_trackers.md)** | Another integration already shows the vehicle's location | Pick the tracker, with no login |

## Set it up
### 1. Install
Open **Settings → Marketplace**, search for **Bus Monitor** and choose **Install**. Restart Home
Assistant if it asks you to.

The Marketplace needs Home Assistant 2026.11 or newer; on older versions, use HACS. If the search
finds nothing yet, add `aniceberg/BusMonitor` by link in the Marketplace, which needs a GitHub
connection.

### 2. Connect your source
[![Add Bus Monitor to Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=bus_monitor)

Or go to **Settings → Devices & services → Add integration → Bus Monitor**. Then choose your source and
your bus.

### 3. Set up your first bus profile
A profile is one trip you want alerts for, such as "Morning" or "Afternoon". Setup goes straight on to
your first one: its name, stop and schedule. Make another profile for each trip with different times.

The stop starts at your home, so drag the pin to the real stop.

### 4. Make the alerts speak
Import the blueprint, then pick a voice and your speakers:

[![Open the blueprint in Home Assistant](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Faniceberg%2FBusMonitor%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fbus_monitor%2Fannounce_bus_alerts.yaml)

### 5. Add your alert points
Open **Bus Monitor** in the sidebar, then add checkpoints on the map. "Minutes away" and street alerts
come from these. Arrival, running-late and "no GPS fix" alerts work without them.

For "where is the bus?" by voice, Amazon Echo or phone alerts, see the
[automation guide](docs/automations.md), which has YAML you can paste.

## Using it
### The map and checkpoints
A checkpoint is a place on the route that triggers an alert when the bus reaches it.

- **Minutes away** says "Bus 12 is about 10 minutes away". Tick **Auto-place** and, after 5 recorded
  trips, it moves itself to where the bus usually is that many minutes out.
- **Street** says "Bus 12 is at Elm Street", and is named after the nearest cross street.

Click the map to add a checkpoint, or add one at the bus's current position. The alarm clocks on the
map show where the bus usually is each minute before your stop, and the shaded trace shows its usual
route. Choose **Save changes** when you're done (administrators only).

### Changing a profile
On the [Bus Monitor integration page](https://my.home-assistant.io/redirect/integration/?domain=bus_monitor),
open a profile's ⋮ menu and choose **Reconfigure** to:
- **Edit the profile:** change its name, bus, stop, schedule or school year. Its checkpoints and history are kept.
- **Add or remove checkpoints**, as an alternative to using the map.

The bus list shows every vehicle your source can see, so a new bus next year is just an edit. Delete
a profile from the same ⋮ menu.

To change how the bus is named in alerts, set **Announce as**, for example "Daniel's bus".

### Holidays and summer
There's no holiday calendar to maintain. If the bus doesn't move by its usual time, that day counts as
a no-bus day and you won't get alerts.

Each profile also pauses after its *School year ends* date, and Settings → Repairs shows a notice.
Before school starts again, edit the profile: check the times and stop, pick the new bus if it changed,
and set the new end date. If the route changed, tick *Forget recorded trips and relearn the route*.

### More than one source
Bus Monitor is installed once and can connect to several sources. To add another Traccar server or
Bouncie account, add the integration again as in step 2. The map shows the profiles from all of them
together, and each profile follows one vehicle from the source it's under.

## Security
Logins are stored in Home Assistant. If your Traccar address starts with `http://`, your login and the
bus's position travel unencrypted, so ask the bus company for HTTPS or a separate login if you can. If
you don't type `http://` or `https://`, Bus Monitor tries `https://` first but will use `http://` if
that's all that answers. To insist on encryption, type `https://`.

## Getting help
On the [integration page](https://my.home-assistant.io/redirect/integration/?domain=bus_monitor), open
your source's ⋮ menu and choose **Download diagnostics**, then attach the file to a
[GitHub issue](https://github.com/aniceberg/BusMonitor/issues).

The file leaves out server addresses, logins, tokens, names, vehicle IDs and all coordinates. It does
include schedule times, such as the normal arrival time.

## More
- [Automations and voice](docs/automations.md)
- [Using a Bouncie tracker](docs/bouncie.md)
- [Following a tracker already in Home Assistant](docs/ha_trackers.md)
- [Reference](docs/reference.md): how alerts work, event data, entities and services
- [Contributing](CONTRIBUTING.md)
