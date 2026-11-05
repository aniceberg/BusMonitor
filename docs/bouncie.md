# Using a Bouncie tracker

[Bouncie](https://bouncie.com) is a GPS tracker that plugs into a vehicle's OBD-II port (for
example a carpool van or a driver's car). Bus Monitor can read its position instead of, or as
well as, a Traccar server. Each Bouncie account is a separate Bus Monitor entry. Everything after
setup works exactly as it does with Traccar: profiles, checkpoints, the map panel, alerts and
`describe_location`.

Bouncie has no shared app for Home Assistant, so you register your own free app, once. Bus
Monitor's setup screen walks you through it, and this page has the same steps with more detail.

## Set it up
1. Start adding the integration:

   [![Add Bus Monitor to Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=bus_monitor)

   Or go to Settings → Devices & services → Add integration → **Bus Monitor**. Then choose **Bouncie**.
2. Keep that screen open. In another tab, sign in to the
   [Bouncie developer portal](https://www.bouncie.dev) with the Bouncie account that owns the
   vehicle, and create an application.
3. Add the **redirect URI** the setup screen shows, exactly as written. It's normally this one:
   ```
   https://my.home-assistant.io/redirect/oauth
   ```
   You don't need to set up webhooks. Bus Monitor polls the REST API.
4. Copy the app's **Client ID** and **Client Secret** into the setup screen and continue.
5. Sign in to Bouncie and approve access.
6. Choose the vehicle(s) to track. Setup then goes straight on to your first bus profile, as with
   Traccar.

The redirect goes through My Home Assistant, which is on by default through `default_config`. The
first time, it may ask for your Home Assistant address. Your browser must be able to reach that
address.

## Adding a second Bouncie account
Add the integration again and choose **Bouncie**. The app you registered is reused, so you go
straight to the Bouncie sign-in. Sign out of Bouncie first if your browser is still signed in to
the other account.

## If sign-in fails
A mistyped Client ID or Client Secret, or a different redirect URI, usually shows up as an error on
Bouncie's page or as "failed to obtain token". Check the app in the
[Bouncie developer portal](https://www.bouncie.dev), then delete the saved credentials and add the
integration again to enter them afresh:

[![Open application credentials in Home Assistant](https://my.home-assistant.io/badges/application_credentials.svg)](https://my.home-assistant.io/redirect/application_credentials/)

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
Add the integration again for the second source. Each bus profile follows one vehicle from the
source it's under, and the map panel and services work across all of them.
