# Using a Bouncie tracker

[Bouncie](https://bouncie.com) is a GPS tracker that plugs into a vehicle's OBD-II port (for
example a carpool van or a driver's car). Bus Monitor can read its position instead of, or as
well as, a Traccar server. Each Bouncie account is a separate Bus Monitor entry. Everything after
setup works exactly as it does with Traccar: profiles, checkpoints, the map panel, alerts and
`describe_location`.

Bouncie has no shared app for Home Assistant, so you register your own (free) app once.

## 1. Register an app with Bouncie
1. Sign in at <https://www.bouncie.dev> with the Bouncie account that owns the vehicle.
2. Create an application.
3. Add this **Redirect URI** exactly as written:
   ```
   https://my.home-assistant.io/redirect/oauth
   ```
4. Copy the app's **Client ID** and **Client Secret**.

You don't need to set up webhooks. Bus Monitor polls the REST API.

## 2. Give Home Assistant the credentials
Settings → Devices & services → ⋮ → **Application credentials** → **Add**. Pick **Bus Monitor**,
then paste the Client ID and Client Secret.

The redirect goes through My Home Assistant, so make sure **My Home Assistant** is enabled (it is
by default through `default_config`). Your browser must be able to reach your Home Assistant URL.

## 3. Add the integration
Settings → Devices & services → Add → **Bus Monitor** → **Bouncie**.
1. Sign in to Bouncie and approve access.
2. Choose the vehicle(s) to track.
3. Choose **Add bus profile** under the Bouncie account, as with Traccar.

If Bouncie later asks you to sign in again, for example because the token wasn't used for a long
time, Home Assistant shows a **Reauthenticate** prompt. Sign in to the *same* Bouncie account.

## How fresh are the positions?
Bus Monitor asks Bouncie for each vehicle's last known location every 30 seconds by default (the
minimum is 15; change it under the Bouncie account's Configure). It only does this while a profile is
watching: inside its watch window, until the bus reaches the stop. Outside that it doesn't call
Bouncie at all, except once when you ask "where is the bus?".

Measured on real school-bus trips (October 2026, polling every 15 s): while driving, every poll
returned a new position. The positions were 10–20 s apart, and each one was about 7 s old (12 s at
most) when Home Assistant received it. So polling is enough and webhooks aren't needed.
Polling every 15 s keeps alerts about 20 s behind the bus; the 30 s default is up to about 40 s
behind. To measure your own vehicle, run the probe during a drive:

```bash
BOUNCIE_TOKEN=<access token> .venv/bin/python scripts/bouncie_probe.py 10 30
```

The "moved after" column shows the seconds between position changes.

Bouncie only reports while the engine is running. A parked vehicle keeps its last position, so
Bus Monitor waits for the bus to move before it announces "running late" or "no GPS fix" (see
*Holidays and summer* in the README).

## Using Traccar and Bouncie together
Add Bus Monitor twice, once per provider. Each bus profile follows one vehicle from its own
entry, and the map panel and services work across all entries.
