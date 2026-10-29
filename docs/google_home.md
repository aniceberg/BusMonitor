# "Hey Google, where is the bus?"

Google Home can't hand a custom sentence to an integration directly, so the supported path is:

```
Google Home routine (your phrase)  ->  Home Assistant script  ->  bus_monitor.describe_location
                                                                   -> speaks on your Nest/Google speakers
```

The sentence is spoken by Home Assistant's text-to-speech on the speakers you list, so it
sounds like a TTS voice, not the Assistant's own. A script can't tell which speaker you
spoke to, so list the speakers you want, or use a media player group.

Example of what it says:
> Bus 12 is on Oak Avenue between 3rd Street and 5th Street, heading north, about 0.8 miles
> from your stop, roughly 6 minutes away.

## 1. Create the script
Paste `examples/where_is_the_bus.yaml` into a new script (YAML mode). Set `profile` to your
profile id (the profile name in lowercase with underscores, e.g. `Morning` -> `morning`),
a `tts_entity`, and your speakers. Click **Run** once to test it.

You can also read the answer without speaking it, e.g. for a dashboard card:
```yaml
- action: bus_monitor.describe_location
  data: { profile: morning }
  response_variable: bus
- action: persistent_notification.create
  data: { message: "{{ bus.text }}" }
```
Response fields: `text`, `street`, `cross_street_behind`, `cross_street_ahead`, `heading`,
`latitude`, `longitude`, `distance_to_stop_m`, `eta_minutes`, `status`.

## 2. Expose the script to Google
Pick one:
- **Home Assistant Cloud (Nabu Casa):** Settings -> Home Assistant Cloud -> Google Assistant ->
  enable, expose the script, then link "Home Assistant" in the Google Home app. Exposed scripts
  show up in Google Home as scenes.
- **Self-managed:** follow the official Google Assistant integration guide (needs a Google
  Cloud project and an externally reachable HTTPS URL).

## 3. Make the voice command (Google Home app)
1. Automations -> **New** -> **Household** routine.
2. **Starter:** "When I say..." -> `where is the bus` (add variants like `where's the bus`).
3. **Action:** "Adjust home devices" (or "Activate scene") -> choose **Where is the bus**.
4. Save, then try "Hey Google, where is the bus".

Menu names in the Google Home app change from time to time; if a step looks different, look
for the option that runs a scene/script by voice.

## Notes
- This works the same whether the bus comes from Traccar or Bouncie.
- Street names come from OpenStreetMap through the public Overpass API; results are cached per
  ~55 m cell for a week, so a bus on its usual route triggers few lookups. If the lookup fails the
  sentence still works, it just won't name a street.
- "Minutes away" uses the last checkpoint the bus passed and the real timings recorded for it;
  until you have recorded trips it falls back to the checkpoint's nominal minutes.
- Without Nabu Casa you can still ask by saying the phrase to Assist, or press a dashboard button
  that runs the script.
