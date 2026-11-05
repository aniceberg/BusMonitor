# Following a tracker already in Home Assistant

Bus Monitor can follow any `device_tracker` entity that reports a latitude and longitude, whichever
integration created it. Use this when your bus or vehicle tracker already has a Home Assistant
integration, or when you feed a location into Home Assistant yourself, for example with an
[MQTT device tracker](https://www.home-assistant.io/integrations/device_tracker.mqtt/).

## Set it up
1. Check the tracker: in **Developer tools → States**, its `device_tracker` entity should have
   `latitude` and `longitude` attributes. Trackers based on a router or Bluetooth don't have them,
   so they aren't offered.
2. Add Bus Monitor and choose **A GPS tracker already in Home Assistant**. There's no login.
3. Pick the tracker, then set up the bus profile as usual.

You only add this provider once. To follow another tracker later, choose **Add bus profile** on the
Bus Monitor integration page.

## What to expect
- **Alerts are only as timely as the tracker.** Bus Monitor checks every 10 seconds by default, but
  a tracker that reports every few minutes can pass a checkpoint between reports. Alerts will be
  later and less reliable than with a tracker that reports every 10 to 30 seconds.
- **Speed and direction are worked out from movement** between reports, because integrations don't
  agree on the units of a speed attribute.
- **"No GPS fix" alerts need regular reports.** Bus Monitor treats the entity's last update as the
  time of the fix. Some integrations only update a tracker when it moves, so a parked vehicle can
  look offline. Leave that alert off (0) for those trackers.
- **Inaccurate fixes are ignored.** A report with `gps_accuracy` above 250 m doesn't trigger alerts.
- **Renaming the tracker's entity ID disconnects the profile.** Edit the profile and pick the tracker
  again.
